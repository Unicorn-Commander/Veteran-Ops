"""Best-effort text extraction for uploaded veteran documents.

Chain (mirrors the battle-tested Glitter Mane rag/ocr.py):
  txt   → read directly.
  pdf   → pypdf text layer; if effectively empty (a scan), rasterize (PyMuPDF,
          optional) and OCR each page.
  image → OCR directly.
OCR of an image = dedicated OCR service (OCR_BASE_URL, multipart POST /ocr,
optional) first, then the LOCAL vision-capable model via the LLM gateway as a
fallback. Every failure degrades to the next step; when nothing works the
caller gets a human-readable error to surface in the UI.

PII note: the vision fallback goes through backend/app/llm/gateway.py with the
DEFAULT model — the deny-by-default allowlist keeps document images on the
local fleet.
"""

from __future__ import annotations

import base64
import os

import httpx
from anyio import to_thread

from ..config import settings

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic", ".heif")
# Office / structured-text documents — parsed DETERMINISTICALLY (no OCR, no LLM);
# each maps to an extractor in _extract_office.
_OFFICE_EXTS = (".docx", ".doc", ".rtf", ".odt", ".xlsx", ".xls", ".csv")
# Below this many characters from the PDF text layer, treat the PDF as scanned.
_TEXT_LAYER_MIN = 40
_MAX_PIXELS = 8_000_000  # ~8 MP per rendered page — bounds memory
# C-file PDFs can run to thousands of pages. Past this budget we cap extraction
# work to the head + tail (decisions/letters up front, newest records at the
# end) and flag the result as truncated so the pipeline can say so honestly.
_PDF_PAGE_BUDGET = 200
_PDF_HEAD_PAGES = 150
_PDF_TAIL_PAGES = 20
# Max pages OCR'd from a SCANNED (image-only) PDF. Rasterizing + OCR-ing every
# page is the expensive path, but OCR runs on a dedicated GPU (dots.ocr on the
# 3060), so this can be generous; past it the result is flagged truncated.
_OCR_MAX_PAGES = 60

NO_TEXT_ERROR = (
    "We couldn't read any text from this file. It may be a low-quality scan or "
    "photo — try a clearer copy, or a PDF with selectable text. You can also "
    "delete this and re-upload, then press Reprocess."
)


def _ocr_base_url() -> str:
    """settings.ocr_base_url when BACKEND-CORE adds it; OCR_BASE_URL env meanwhile."""
    return (getattr(settings, "ocr_base_url", "") or os.environ.get("OCR_BASE_URL", "")).strip()


def _ocr_engine() -> str:
    """'dots' (GPU vLLM vision, e.g. ocr-host 3060) or 'paddle' (multipart /ocr)."""
    raw = getattr(settings, "ocr_engine", "") or os.environ.get("OCR_ENGINE", "")
    return (raw or "paddle").strip().lower()


def _maybe_preprocess(image_bytes: bytes) -> bytes:
    """Deskew/upscale/denoise the page image before OCR when settings.ocr_preprocess
    is on; a straight passthrough otherwise. Applied ONCE per page so BOTH cross-read
    engines see the same cleaned image. Never raises (preprocess_page degrades to the
    original bytes on any failure)."""
    if not getattr(settings, "ocr_preprocess", False):
        return image_bytes
    from .preprocess import preprocess_page

    return preprocess_page(image_bytes, binarize=getattr(settings, "ocr_preprocess_binarize", False))


def _is_image(path: str, content_type: str | None) -> bool:
    if content_type and content_type.startswith("image/"):
        return True
    return path.lower().endswith(_IMAGE_EXTS)


def _is_pdf(path: str, content_type: str | None) -> bool:
    return bool(content_type and "pdf" in content_type) or path.lower().endswith(".pdf")


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return ""


def _pdf_page_indices(page_count: int, full_read: bool = False) -> tuple[list[int], bool]:
    """Which pages to extract, and whether that truncates the document. Over the
    budget we read the first _PDF_HEAD_PAGES + last _PDF_TAIL_PAGES only — UNLESS
    full_read, when EVERY page is read (the cheap text layer, quality-first)."""
    if full_read or page_count <= _PDF_PAGE_BUDGET:
        return list(range(page_count)), False
    head = list(range(_PDF_HEAD_PAGES))
    tail = list(range(page_count - _PDF_TAIL_PAGES, page_count))
    return head + tail, True


def _pdf_text_layer(path: str, full_read: bool = False) -> tuple[list[str], bool]:
    """(pages, truncated). truncated=True when the page budget capped extraction
    (never under full_read — the whole text layer is read)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = reader.pages
        indices, truncated = _pdf_page_indices(len(pages), full_read=full_read)
        return ([(pages[i].extract_text() or "") for i in indices], truncated)
    except Exception:  # noqa: BLE001
        return [], False


def _rasterize_pdf(
    path: str, max_pages: int = _OCR_MAX_PAGES, dpi: int = 200, full_read: bool = False
) -> tuple[list[bytes], bool]:
    """Render PDF pages to PNG bytes for OCR of image-only PDFs. Returns
    (pages, truncated); truncated=True when the PDF had more pages than the cap.
    Under full_read the cap rises to settings.ocr_full_read_max_pages (a giant
    scanned file still needs SOME ceiling — rasterize+OCR is the expensive path).
    [] when PyMuPDF is unavailable. Per-page zoom is clamped so an oversized
    MediaBox can't blow up memory."""
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001
        return [], False
    cap = max(max_pages, getattr(settings, "ocr_full_read_max_pages", 500)) if full_read else max_pages
    out: list[bytes] = []
    truncated = False
    try:
        doc = fitz.open(path)
        truncated = doc.page_count > cap
        zoom = dpi / 72.0
        for page in doc[:cap]:
            rect = page.rect
            z = zoom
            area = (rect.width or 1) * (rect.height or 1)
            if area * z * z > _MAX_PIXELS:
                z = (_MAX_PIXELS / area) ** 0.5
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
            out.append(pix.tobytes("png"))
        doc.close()
    except Exception:  # noqa: BLE001
        return out, truncated
    return out, truncated


_DOTS_OCR_PROMPT = (
    "Extract all text from this document image verbatim, preserving reading "
    "order. Keep table rows together (label then value). Output only the text, "
    "with no commentary."
)


async def _ocr_dots(base: str, image_bytes: bytes, content_type: str) -> str:
    """dots.ocr — a vLLM OpenAI VISION model on the fleet 3060. POST the page
    image to {base}/chat/completions and return the transcribed text. `base` is
    the OpenAI base (…/v1). '' on any failure (caller falls through)."""
    data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"
    url = base.rstrip("/") + "/chat/completions"
    headers = {}
    key = (getattr(settings, "ocr_api_key", "") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": getattr(settings, "ocr_model", "") or "dots-ocr",
        "temperature": 0.0,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _DOTS_OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def _ocr_paddle(base: str, image_bytes: bytes, name: str, content_type: str) -> str:
    """PaddleOCR-style service (multipart POST /ocr → {text}). '' on failure."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                base.rstrip("/") + "/ocr",
                files={"file": (name, image_bytes, content_type)},
            )
            resp.raise_for_status()
            return (resp.json().get("text") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def _ocr_service(image_bytes: bytes, name: str, content_type: str) -> str:
    """Dedicated OCR service — engine-aware. '' when unset/fails (the caller then
    falls through to the vision-model fallback)."""
    base = _ocr_base_url()
    if not base:
        return ""
    if _ocr_engine() == "dots":
        return await _ocr_dots(base, image_bytes, content_type)
    return await _ocr_paddle(base, image_bytes, name, content_type)


async def _vision_transcribe(image_bytes: bytes, content_type: str) -> str:
    """Fallback: ask the LOCAL VISION model (via the allowlisted gateway) to
    transcribe. Routes explicitly to settings.vision_model — the default text
    llm_model has no mmproj projector and rejects images ("Failed to load
    image"), so this must NOT fall through to it. '' when no vision model is
    configured or on any failure — the caller reports a readable error."""
    from ..config import settings

    if not (settings.vision_model or "").strip():
        return ""
    data_url = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"
    from ..llm.gateway import gateway  # lazy — keeps this module importable sans SDK

    try:
        return await gateway.complete(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Transcribe ALL text in this image verbatim. Preserve "
                                "layout where it matters (keep table rows together: "
                                "label then value). Output only the transcribed text, "
                                "no commentary."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            model=settings.vision_model,
            temperature=0.0,
            max_tokens=2000,
        )
    except Exception:  # noqa: BLE001
        return ""


async def _ocr_one(image_bytes: bytes, name: str, content_type: str = "image/png") -> str:
    text = await _ocr_service(image_bytes, name, content_type)
    if text.strip():
        return text
    return await _vision_transcribe(image_bytes, content_type)


async def _ocr_second(image_bytes: bytes, name: str, content_type: str) -> str:
    """The SECOND, decorrelated read for the cross-read. Configurable
    (ocr_crossread_engine): "paddle" pairs a TRADITIONAL OCR service — different
    failure modes than the vision-LLM primary, so it catches more, and it offloads to
    CPU — while anything else (default) uses the local vision model. '' on failure."""
    engine = (getattr(settings, "ocr_crossread_engine", "") or "vision").strip().lower()
    base = (getattr(settings, "ocr_crossread_base_url", "") or "").strip()
    if engine == "paddle" and base:
        return await _ocr_paddle(base, image_bytes, name, content_type)
    return await _vision_transcribe(image_bytes, content_type)


async def _ocr_crossread(
    image_bytes: bytes, name: str, content_type: str = "image/png"
) -> tuple[str, str | None]:
    """Read the SAME page image with TWO engines for a cross-read (not a fallback).

    Returns (primary_text, second_text): primary is the dedicated OCR service
    (dots.ocr / paddle) when it succeeds; second_text is an INDEPENDENT read of the
    same image by the configured cross-read engine (a decorrelated PaddleOCR, or the
    vision model by default) so intake/crossread.py can catch a 50-vs-70 misread.
    When the dedicated service is unset or misses, the second engine's read becomes
    the primary and there is nothing to compare against (second_text is None) — the
    caller records no cross-read for that page rather than comparing a read to itself.
    The stored text is always the primary, so a single-engine deployment is
    unchanged."""
    service_text = await _ocr_service(image_bytes, name, content_type)
    if service_text.strip():
        second_text = await _ocr_second(image_bytes, name, content_type)
        return service_text, (second_text.strip() or None)
    second_text = await _ocr_second(image_bytes, name, content_type)
    return second_text, None


def _page_offsets(pages: list[str]) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for i, page in enumerate(pages):
        offsets.append(cursor)
        cursor += len(page)
        if i < len(pages) - 1:
            cursor += 2
    return offsets


# ── Office / structured-document extractors (deterministic, no OCR) ──────────

def _extract_docx(path: str) -> str:
    from docx import Document as _Docx  # python-docx

    doc = _Docx(path)
    parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:  # tables carry a lot of a records form's content
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_doc(path: str) -> str:
    """Legacy binary Word (.doc) via the `antiword` system binary."""
    import subprocess

    try:
        out = subprocess.run(
            ["antiword", path], capture_output=True, timeout=60, check=False
        )
        return (out.stdout or b"").decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 — binary missing / unreadable doc
        return ""


def _extract_rtf(path: str) -> str:
    from striprtf.striprtf import rtf_to_text

    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return rtf_to_text(fh.read())


def _extract_odt(path: str) -> str:
    from odf import teletype, text as odftext
    from odf.opendocument import load as odfload

    doc = odfload(path)
    return "\n".join(
        teletype.extractText(el) for el in doc.getElementsByType(odftext.P)
    )


def _extract_xlsx(path: str) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"# {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    wb.close()
    return "\n".join(lines)


def _extract_xls(path: str) -> str:
    import xlrd

    book = xlrd.open_workbook(path)
    lines: list[str] = []
    for sheet in book.sheets():
        lines.append(f"# {sheet.name}")
        for r in range(sheet.nrows):
            cells = [str(v) for v in sheet.row_values(r) if str(v).strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _extract_office(path: str, ext: str) -> str:
    """Dispatch a structured-document extension to its extractor. Never raises —
    '' on any failure so the caller reports a readable error."""
    try:
        if ext == ".docx":
            return _extract_docx(path)
        if ext == ".doc":
            return _extract_doc(path)
        if ext == ".rtf":
            return _extract_rtf(path)
        if ext == ".odt":
            return _extract_odt(path)
        if ext == ".xlsx":
            return _extract_xlsx(path)
        if ext == ".xls":
            return _extract_xls(path)
        if ext == ".csv":
            return _read_text(path)
    except Exception:  # noqa: BLE001 — corrupt file / missing optional dep
        return ""
    return ""


def _normalize_image_to_png(image_bytes: bytes) -> bytes | None:
    """Transcode any Pillow-readable image (HEIC, BMP, WebP, GIF, TIFF, …) to
    PNG so the OCR model always receives a format it can decode. Returns None
    when Pillow is unavailable or the bytes aren't a readable image — the caller
    then sends the original bytes (the OCR service may still handle common
    formats)."""
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001 — Pillow not installed
        return None
    # HEIC/HEIF (iPhone) needs the extra opener; other formats work with Pillow
    # alone, so a missing pillow-heif only costs HEIC support, not the rest.
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001
        pass
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


async def extract_text(
    path: str, content_type: str | None, *, full_read: bool = False
) -> tuple[str, str | None, dict]:
    """Best-effort text from any supported document.

    Returns (text, error, meta): non-empty text with error=None on success;
    empty text with a human-readable error (shown by the UI) when every
    fallback failed. meta["truncated"]=True when a very large PDF was read
    head+tail only (the page budget) — the stored text may be partial. When
    full_read, the whole PDF text layer is read (no head+tail cap) and the
    scanned-OCR ceiling rises to settings.ocr_full_read_max_pages.
    """
    ext = ("." + path.rsplit(".", 1)[-1].lower()) if "." in path.rsplit("/", 1)[-1] else ""

    # Office / structured-text documents — deterministic extraction, no OCR.
    if ext in _OFFICE_EXTS:
        text = await to_thread.run_sync(_extract_office, path, ext)
        if text.strip():
            return text, None, {}
        return "", NO_TEXT_ERROR, {}

    if _is_image(path, content_type):
        img = await to_thread.run_sync(_read_bytes, path)
        # Normalize odd formats (HEIC/BMP/WebP/GIF) to PNG so the OCR model can
        # always decode them; fall back to the original bytes if Pillow can't.
        png = await to_thread.run_sync(_normalize_image_to_png, img)
        if png is not None:
            img, ct = png, "image/png"
        else:
            ct = content_type if (content_type or "").startswith("image/") else "image/png"
        img = await to_thread.run_sync(_maybe_preprocess, img)
        text, vision_text = await _ocr_crossread(img, path.rsplit("/", 1)[-1], ct)
        if text.strip():
            # A single-image cross-read: both engines read the one page.
            meta = (
                {"page_reads": [{"page": 0, "ocr": text, "vision": vision_text}]}
                if vision_text is not None
                else {}
            )
            return text, None, meta
        return "", NO_TEXT_ERROR, {}

    if _is_pdf(path, content_type):
        layer_pages, truncated = await to_thread.run_sync(_pdf_text_layer, path, full_read)
        meta = {"truncated": True} if truncated else {}
        layer = "\n\n".join(layer_pages)
        if len(layer.strip()) >= _TEXT_LAYER_MIN:
            if layer_pages:
                meta = {**meta, "page_offsets": _page_offsets(layer_pages)}
            return layer, None, meta
        # Scanned PDF — rasterize and OCR page by page, cross-reading each page with
        # both engines so a per-page misread of a rating/DC/date is caught.
        pages, ras_truncated = await to_thread.run_sync(_rasterize_pdf, path, _OCR_MAX_PAGES, 200, full_read)
        if ras_truncated:
            meta = {**meta, "truncated": True}
        texts: list[str] = []
        page_reads: list[dict] = []
        unreadable = 0
        for i, png in enumerate(pages):
            png = await to_thread.run_sync(_maybe_preprocess, png)
            primary, vision_text = await _ocr_crossread(png, f"page-{i + 1}.png")
            texts.append(primary)
            if not primary.strip():
                unreadable += 1
            if vision_text is not None:
                page_reads.append({"page": i, "ocr": primary, "vision": vision_text})
        joined = "\n\n".join(texts)
        if joined.strip():
            if texts:
                meta = {**meta, "page_offsets": _page_offsets(texts)}
            if page_reads:
                meta = {**meta, "page_reads": page_reads}
            if unreadable:
                meta = {**meta, "unreadable_pages": unreadable}
            return joined, None, meta
        if layer.strip():  # a few chars beat nothing
            if layer_pages:
                meta = {**meta, "page_offsets": _page_offsets(layer_pages)}
            return layer, None, meta
        return "", NO_TEXT_ERROR, {}

    # Plain text (.txt) and anything text-like.
    text = await to_thread.run_sync(_read_text, path)
    if text.strip():
        return text, None, {}
    return "", NO_TEXT_ERROR, {}
