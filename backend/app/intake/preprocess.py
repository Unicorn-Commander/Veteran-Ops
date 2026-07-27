"""Optional image preprocessing before OCR — deskew, upscale, denoise, contrast.

A scanned C-file page is often skewed, low-DPI, and speckled; TRADITIONAL OCR
(PaddleOCR / Tesseract) is sensitive to all three. This cleans a page image
BEFORE it reaches the OCR engines. It is Pillow + numpy ONLY — deliberately no
OpenCV, so it adds no system libraries to the deploy image (the backend already
ships both) — and it NEVER raises: any failure returns the ORIGINAL bytes so
intake degrades to the raw page rather than dropping the document.

Gated by settings.ocr_preprocess (default off). Whether it HELPS is engine-
dependent: a vision-LLM primary (dots.ocr) can prefer the raw colour image while
a traditional engine prefers a deskewed, binarized one. MEASURE with
tools/ocr-bench before enabling in prod — do not assume it is a win everywhere.
"""

from __future__ import annotations

import io

# Upscale so the short side reaches this (helps low-DPI scans) but never explode a
# page that is already large.
_MIN_SIDE = 1000
_MAX_SIDE = 4000
# Deskew search: ±_SKEW_RANGE degrees at _SKEW_STEP resolution.
_SKEW_RANGE = 8.0
_SKEW_STEP = 0.5
# Cap the copy used for skew ESTIMATION so the 33-rotation search stays fast; the
# correction is then applied once to the full-resolution page.
_SKEW_ESTIMATE_MAX = 1200


def _estimate_skew_degrees(gray_small) -> float:
    """Projection-profile deskew angle. Text rows, when horizontal, make the
    row-sum profile spike (dark rows, light gaps) → its VARIANCE is maximal. We
    rotate a downscaled copy across the search range and pick the angle that
    maximizes that variance. Returns degrees to rotate the page (PIL convention:
    positive = counter-clockwise)."""
    import numpy as np
    from PIL import Image

    best_angle, best_score = 0.0, -1.0
    steps = int((2 * _SKEW_RANGE) / _SKEW_STEP) + 1
    for i in range(steps):
        angle = -_SKEW_RANGE + i * _SKEW_STEP
        rot = gray_small.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=255)
        profile = (255.0 - np.asarray(rot, dtype=np.float32)).sum(axis=1)
        score = float(np.var(profile))
        if score > best_score:
            best_score, best_angle = score, angle
    return best_angle


def _otsu_threshold(arr) -> int:
    """Otsu's method: the 8-bit threshold that maximizes between-class variance."""
    import numpy as np

    hist, _ = np.histogram(arr.ravel(), bins=256, range=(0, 256))
    total = int(arr.size)
    sum_all = float(np.dot(np.arange(256), hist))
    w_b = 0.0
    sum_b = 0.0
    best_t, best_var = 127, -1.0
    for t in range(256):
        w_b += float(hist[t])
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f <= 0:
            break
        sum_b += t * float(hist[t])
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > best_var:
            best_var, best_t = var_between, t
    return best_t


def preprocess_page(image_bytes: bytes, *, binarize: bool = False) -> bytes:
    """Clean one page image for OCR. Grayscale → deskew → upscale-if-small →
    light denoise → autocontrast, and (optionally) an Otsu binarize. Returns PNG
    bytes; on ANY failure (Pillow/numpy missing, undecodable bytes) returns the
    input unchanged so the caller can still OCR the raw page."""
    try:
        import numpy as np
        from PIL import Image, ImageFilter, ImageOps
    except Exception:  # noqa: BLE001 — deps absent → no-op
        return image_bytes
    try:
        im = Image.open(io.BytesIO(image_bytes))
        im.load()
        gray = ImageOps.grayscale(im)

        # 1. Deskew — estimate on a downscaled copy (fast), apply to the full page.
        est = gray
        longest = max(gray.size)
        if longest > _SKEW_ESTIMATE_MAX:
            r = _SKEW_ESTIMATE_MAX / longest
            est = gray.resize((max(1, int(gray.width * r)), max(1, int(gray.height * r))), Image.BILINEAR)
        angle = _estimate_skew_degrees(est)
        if abs(angle) >= _SKEW_STEP:
            gray = gray.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)

        # 2. Upscale a low-DPI page so glyphs are big enough for the recognizer.
        short = min(gray.size)
        if short < _MIN_SIDE:
            scale = min(_MIN_SIDE / short, _MAX_SIDE / max(gray.size))
            if scale > 1.01:
                gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.LANCZOS)

        # 3. Light speckle removal + stretch contrast.
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
        gray = ImageOps.autocontrast(gray, cutoff=1)

        # 4. Optional hard binarize — helps traditional OCR, usually HURTS a vision LLM.
        if binarize:
            arr = np.asarray(gray, dtype=np.uint8)
            thr = _otsu_threshold(arr)
            gray = Image.fromarray(np.where(arr >= thr, 255, 0).astype("uint8"), mode="L")

        buf = io.BytesIO()
        gray.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — never break intake on a preprocessing miss
        return image_bytes
