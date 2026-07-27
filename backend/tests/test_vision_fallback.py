"""The scanned-image vision fallback must route to the LOCAL multimodal model
(mmproj), never the text-only default, and must stay on the PII allowlist."""

from __future__ import annotations

import pytest

from app.config import settings
from app.intake import ocr


def test_vision_model_is_on_the_pii_allowlist():
    # _resolve_model drops any id not in allowed_models → the fallback would be
    # silently downgraded to the text model without this.
    assert settings.vision_model in settings.allowed_models


def test_text_model_and_vision_model_both_allowed():
    allowed = settings.allowed_models
    assert settings.llm_model in allowed
    assert settings.vision_model in allowed


@pytest.mark.asyncio
async def test_ocr_service_routes_to_dots_engine(monkeypatch):
    # engine=dots → OpenAI vision path (dots.ocr on the 3060), NOT the paddle
    # multipart path.
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr-host:8094/v1")
    monkeypatch.setattr(settings, "ocr_engine", "dots")
    calls = {}

    async def _dots(base, img, ct):
        calls["dots"] = base
        return "DOTS TEXT"

    async def _paddle(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("paddle called while engine=dots")

    monkeypatch.setattr(ocr, "_ocr_dots", _dots)
    monkeypatch.setattr(ocr, "_ocr_paddle", _paddle)
    out = await ocr._ocr_service(b"img", "scan.png", "image/png")
    assert out == "DOTS TEXT"
    assert calls["dots"] == "http://ocr-host:8094/v1"


@pytest.mark.asyncio
async def test_ocr_service_defaults_to_paddle_engine(monkeypatch):
    monkeypatch.setattr(settings, "ocr_base_url", "http://host:8097")
    monkeypatch.setattr(settings, "ocr_engine", "paddle")

    async def _paddle(base, img, name, ct):
        return "PADDLE TEXT"

    async def _dots(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("dots called while engine=paddle")

    monkeypatch.setattr(ocr, "_ocr_paddle", _paddle)
    monkeypatch.setattr(ocr, "_ocr_dots", _dots)
    out = await ocr._ocr_service(b"img", "scan.png", "image/png")
    assert out == "PADDLE TEXT"


@pytest.mark.asyncio
async def test_no_ocr_base_url_skips_service(monkeypatch):
    monkeypatch.setattr(settings, "ocr_base_url", "")
    monkeypatch.delenv("OCR_BASE_URL", raising=False)
    assert await ocr._ocr_service(b"img", "scan.png", "image/png") == ""


@pytest.mark.asyncio
async def test_empty_vision_model_disables_fallback(monkeypatch):
    # No vision model configured → fallback returns '' WITHOUT calling the
    # gateway (so an image never hits the text-only model).
    monkeypatch.setattr(settings, "vision_model", "")

    async def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("gateway called despite no vision model configured")

    monkeypatch.setattr(ocr, "gateway", type("G", (), {"complete": staticmethod(_boom)})(), raising=False)
    out = await ocr._vision_transcribe(b"\x89PNG...", "image/png")
    assert out == ""


@pytest.mark.asyncio
async def test_crossread_pairs_paddle_as_the_second_engine(monkeypatch):
    # ocr_crossread_engine=paddle (+ a base url) → the cross-read's SECOND read is
    # PaddleOCR — the decorrelated pairing with a dots-OCR primary — not the vision
    # model. This is the "wire up Paddle so we can compare / use it if it's better".
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr-host:8094/v1")
    monkeypatch.setattr(settings, "ocr_engine", "dots")
    monkeypatch.setattr(settings, "ocr_crossread_engine", "paddle")
    monkeypatch.setattr(settings, "ocr_crossread_base_url", "http://paddle:8097")
    calls = {}

    async def _dots(base, img, ct):
        return "DOTS PRIMARY 50%"

    async def _paddle(base, img, name, ct):
        calls["paddle_base"] = base
        return "PADDLE SECOND 50%"

    async def _vision(*a, **k):  # pragma: no cover — must not be the second read here
        raise AssertionError("vision used as the second read while crossread_engine=paddle")

    monkeypatch.setattr(ocr, "_ocr_dots", _dots)
    monkeypatch.setattr(ocr, "_ocr_paddle", _paddle)
    monkeypatch.setattr(ocr, "_vision_transcribe", _vision)
    primary, second = await ocr._ocr_crossread(b"img", "scan.png", "image/png")
    assert primary == "DOTS PRIMARY 50%"
    assert second == "PADDLE SECOND 50%"        # the decorrelated second read
    assert calls["paddle_base"] == "http://paddle:8097"


@pytest.mark.asyncio
async def test_crossread_second_engine_defaults_to_vision(monkeypatch):
    # Unconfigured → the cross-read's second engine is the local vision model
    # (backward-compatible: single-engine deployments unchanged).
    monkeypatch.setattr(settings, "ocr_base_url", "http://ocr-host:8094/v1")
    monkeypatch.setattr(settings, "ocr_engine", "dots")
    monkeypatch.setattr(settings, "ocr_crossread_engine", "vision")
    monkeypatch.setattr(settings, "ocr_crossread_base_url", "")

    async def _dots(base, img, ct):
        return "DOTS PRIMARY"

    async def _vision(img, ct):
        return "VISION SECOND"

    async def _paddle(*a, **k):  # pragma: no cover — not used when engine=vision
        raise AssertionError("paddle used while crossread_engine=vision")

    monkeypatch.setattr(ocr, "_ocr_dots", _dots)
    monkeypatch.setattr(ocr, "_vision_transcribe", _vision)
    monkeypatch.setattr(ocr, "_ocr_paddle", _paddle)
    primary, second = await ocr._ocr_crossread(b"img", "scan.png", "image/png")
    assert primary == "DOTS PRIMARY" and second == "VISION SECOND"
