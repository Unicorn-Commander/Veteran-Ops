"""OCR image preprocessing (deskew / upscale / denoise / binarize), Pillow+numpy
only. Deterministic, no fleet, no new deps. The deskew is proved on synthetic
horizontal-bar 'text' images where the correct angle is known."""

from __future__ import annotations

import io

import pytest

from app.intake.preprocess import _estimate_skew_degrees, preprocess_page

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _bars(size: int = 480, n: int = 16, tilt: float = 0.0):
    """A grayscale image of evenly spaced black horizontal bars on white — a clean
    projection-profile signal. `tilt` rotates it (PIL: positive = CCW)."""
    im = Image.new("L", (size, size), 255)
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    step = size // (n + 1)
    for i in range(1, n + 1):
        y = i * step
        d.rectangle([size // 8, y, size - size // 8, y + step // 3], fill=0)
    if tilt:
        im = im.rotate(tilt, resample=Image.BILINEAR, expand=False, fillcolor=255)
    return im


def _png_bytes(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_estimate_skew_is_near_zero_on_a_straight_page():
    assert abs(_estimate_skew_degrees(_bars(tilt=0.0))) <= 1.0


def test_estimate_skew_detects_a_known_tilt():
    # Bars tilted +5° CCW → the variance-maximizing correction is ≈ -5°.
    detected = _estimate_skew_degrees(_bars(tilt=5.0))
    assert abs(detected - (-5.0)) <= 1.5


def test_preprocess_returns_a_grayscale_png():
    out = preprocess_page(_png_bytes(_bars()))
    im = Image.open(io.BytesIO(out))
    assert im.format == "PNG"
    assert im.mode == "L"


def test_preprocess_upscales_a_small_page():
    small = _bars(size=300)
    out = preprocess_page(_png_bytes(small))
    im = Image.open(io.BytesIO(out))
    assert min(im.size) >= 1000  # short side lifted toward the recognizer's sweet spot


def test_binarize_yields_a_two_tone_image():
    import numpy as np

    out = preprocess_page(_png_bytes(_bars()), binarize=True)
    arr = np.asarray(Image.open(io.BytesIO(out)).convert("L"))
    assert set(np.unique(arr)).issubset({0, 255})


def test_never_raises_on_undecodable_bytes():
    junk = b"this is not an image"
    assert preprocess_page(junk) == junk  # degrades to the original, never throws


def test_maybe_preprocess_is_a_passthrough_when_flag_off():
    from app.config import settings
    from app.intake import ocr

    assert settings.ocr_preprocess is False  # guard: default keeps intake unchanged
    raw = _png_bytes(_bars())
    assert ocr._maybe_preprocess(raw) is raw  # identical object, no work done
