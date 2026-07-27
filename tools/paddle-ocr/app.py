"""Self-contained PaddleOCR HTTP service for valor-ops document intake.

Contract (matches backend/app/intake/ocr.py `_ocr_paddle`):
  POST /ocr   multipart form, single file field named exactly `file`.
              -> {"text": "<transcription>", "engine": "paddleocr", "version": "<pp-ocr>"}
  GET  /health -> {"status": "ok"} (200) once the model is loaded; 503 while loading.

Engine: PaddleOCR PP-OCRv5, English, CPU-only. The model is built once at
startup and reused. Recognition results are re-ordered top-to-bottom then
left-to-right and grouped into visual lines (label + value on one line) so
table rows stay together and single-column prose reads naturally.

Robustness: any image Pillow can open is accepted and converted to RGB. A
decode failure or an OCR error never 500s — it returns {"text": "", ...} so the
caller (which treats a failure as an empty read and falls through) behaves
predictably.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("valor-paddle-ocr")

OCR_LANG = os.environ.get("OCR_LANG", "en")

# PaddleOCR's predict() is CPU-bound and not guaranteed re-entrant on one
# instance; serialize it. It runs in a threadpool so the event loop (and
# /health) stays responsive.
_OCR_LOCK = threading.Lock()
_STATE: dict = {"ocr": None, "ready": False, "version": "PP-OCRv6"}


def _build_ocr():
    """Construct the OCR pipeline, CPU-only, English. Orientation and
    document-unwarping sub-models are disabled: they add model downloads and
    latency but do nothing for the upright, single-column scans valor ingests.

    Model line: paddleocr 3.7.0's English default is PP-OCRv6_medium (det+rec).
    Override with OCR_DET_MODEL / OCR_REC_MODEL to pin a different line
    (e.g. PP-OCRv5_server_det / PP-OCRv5_server_rec) — rebuild to bake those.
    """
    from paddleocr import PaddleOCR

    kwargs = dict(
        lang=OCR_LANG,
        device=os.environ.get("OCR_DEVICE", "cpu"),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    det = os.environ.get("OCR_DET_MODEL")
    rec = os.environ.get("OCR_REC_MODEL")
    if det:
        kwargs["text_detection_model_name"] = det
    if rec:
        kwargs["text_recognition_model_name"] = rec
    return PaddleOCR(**kwargs)


def _detect_version() -> str:
    """Honest PP-OCR version string. PP_OCR_VERSION env wins; otherwise read the
    ACTUAL recognition model that got loaded/baked from the model cache dir
    (…/.paddlex/official_models/<name>_rec); constant fallback last."""
    env = os.environ.get("PP_OCR_VERSION")
    if env:
        return env
    try:
        base = os.path.join(os.path.expanduser("~"), ".paddlex", "official_models")
        recs = sorted(d for d in os.listdir(base) if d.endswith("_rec"))
        if recs:
            return recs[0][: -len("_rec")]  # PP-OCRv6_medium_rec -> PP-OCRv6_medium
    except Exception:  # noqa: BLE001
        pass
    return "PP-OCRv6"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("loading PaddleOCR (lang=%s, cpu) ...", OCR_LANG)
    _STATE["ocr"] = await run_in_threadpool(_build_ocr)
    _STATE["version"] = _detect_version()
    # Warm the graph with a tiny synthetic image so the first real request isn't
    # the one that pays JIT/allocation cost.
    try:
        warm = np.full((32, 160, 3), 255, dtype=np.uint8)
        await run_in_threadpool(_predict_text, warm)
    except Exception:  # noqa: BLE001
        log.warning("warmup predict failed (non-fatal)", exc_info=True)
    _STATE["ready"] = True
    log.info("PaddleOCR ready (engine=%s)", _STATE["version"])
    yield


app = FastAPI(title="valor-paddle-ocr", lifespan=lifespan)


def _poly_points(poly) -> list[tuple[float, float]]:
    """Normalize a detection result box into [(x, y), ...].

    PaddleOCR 3.x gives per-line polygons as an (N, 2) array. Some versions/paths
    instead give an axis-aligned box [x1, y1, x2, y2]; handle that too.
    """
    arr = np.asarray(poly, dtype=float).reshape(-1)
    if arr.size == 4:  # [x1, y1, x2, y2]
        x1, y1, x2, y2 = arr.tolist()
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    pts = arr.reshape(-1, 2)
    return [(float(x), float(y)) for x, y in pts]


def _reading_order(boxes: list[list[tuple[float, float]]], texts: list[str]) -> str:
    """Join recognized lines in human reading order.

    Cluster boxes into visual lines by vertical center (threshold = a fraction of
    the median line height), sort lines top-to-bottom and each line's boxes
    left-to-right. Within a line, tokens join with a space (keeps a table row's
    label and value on the same output line); lines join with newlines.
    """
    items = []
    for box, txt in zip(boxes, texts):
        if txt is None or not str(txt).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        y_top, y_bot = min(ys), max(ys)
        items.append(
            {
                "x": min(xs),
                "yc": (y_top + y_bot) / 2.0,
                "h": max(1.0, y_bot - y_top),
                "t": str(txt).strip(),
            }
        )
    if not items:
        return ""

    heights = sorted(i["h"] for i in items)
    med_h = heights[len(heights) // 2]
    thresh = max(4.0, med_h * 0.6)

    items.sort(key=lambda i: (i["yc"], i["x"]))
    lines: list[list[dict]] = [[items[0]]]
    line_y = items[0]["yc"]
    for it in items[1:]:
        if abs(it["yc"] - line_y) <= thresh:
            lines[-1].append(it)
        else:
            lines.append([it])
        line_y = sum(x["yc"] for x in lines[-1]) / len(lines[-1])

    out = []
    for ln in lines:
        ln.sort(key=lambda i: i["x"])
        out.append(" ".join(i["t"] for i in ln))
    return "\n".join(out)


def _extract(result) -> str:
    """Pull (texts, boxes) out of a PaddleOCR predict() result and order them.

    3.x predict() returns a list with one dict-like OCRResult per image. We read
    the single image's result and prefer recognition polygons (`rec_polys`),
    falling back to detection polygons / axis-aligned boxes across versions.
    """
    if not result:
        return ""
    res = result[0]

    def _get(obj, key):
        try:
            return obj[key]
        except Exception:  # noqa: BLE001
            return getattr(obj, key, None)

    texts = _get(res, "rec_texts")
    if not texts:
        return ""
    boxes_raw = _get(res, "rec_polys")
    if boxes_raw is None:
        boxes_raw = _get(res, "dt_polys")
    if boxes_raw is None:
        boxes_raw = _get(res, "rec_boxes")

    # No geometry at all -> preserve model order (already reading order for one column).
    if boxes_raw is None or len(boxes_raw) != len(texts):
        return "\n".join(str(t).strip() for t in texts if t and str(t).strip())

    boxes = [_poly_points(b) for b in boxes_raw]
    return _reading_order(boxes, list(texts))


def _predict_text(img_rgb: np.ndarray) -> str:
    """Run OCR on an RGB HxWx3 uint8 array and return ordered text."""
    # PaddleOCR (cv2 lineage) expects BGR channel order for ndarray input.
    bgr = np.ascontiguousarray(img_rgb[:, :, ::-1])
    with _OCR_LOCK:
        result = _STATE["ocr"].predict(bgr)
    return _extract(result)


def _decode_to_rgb(raw: bytes) -> np.ndarray | None:
    """Any Pillow-openable image -> RGB uint8 ndarray. None on failure."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            if im.mode != "RGB":
                im = im.convert("RGB")
            return np.asarray(im, dtype=np.uint8)
    except Exception:  # noqa: BLE001
        return None


@app.get("/health")
async def health():
    if not _STATE["ready"]:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    body = {"text": "", "engine": "paddleocr", "version": _STATE["version"]}
    if not _STATE["ready"] or _STATE["ocr"] is None:
        return JSONResponse({**body, "detail": "model not ready"}, status_code=503)
    try:
        raw = await file.read()
    except Exception:  # noqa: BLE001
        return body
    if not raw:
        return body
    img = _decode_to_rgb(raw)
    if img is None:
        log.info("undecodable upload (%s, %d bytes) -> empty text", file.filename, len(raw))
        return body
    try:
        text = await run_in_threadpool(_predict_text, img)
    except Exception:  # noqa: BLE001
        log.warning("OCR failed for %s -> empty text", file.filename, exc_info=True)
        return body
    body["text"] = text or ""
    return body
