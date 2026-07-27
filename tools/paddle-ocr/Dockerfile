# valor-paddle-ocr — self-contained PaddleOCR (PP-OCRv5) HTTP service, CPU-only.
#
# One arch-agnostic image: pip selects the right paddlepaddle wheel per platform.
#   - default build on Apple Silicon  -> linux/arm64, aarch64 wheel (native, fast)
#   - fleet build: --platform linux/amd64 -> x86_64 AVX wheel (real server CPUs)
# paddlepaddle 3.2.0 is the newest release that ships BOTH cp311 wheels, which is
# why it is pinned (see requirements.txt / README).
#
# NOTE: the standard x86_64 paddle wheel is AVX-compiled and will SIGILL under
# macOS/Rosetta emulation (Rosetta exposes only up to SSE4.2). That is a
# local-emulation limitation only — real fleet x86_64 CPUs have AVX. Build/run
# this image natively per host arch.
FROM python:3.11-slim-bookworm

# System libs: libgomp1 (paddle OpenMP runtime), libgl1 + libglib2.0-0 (opencv
# runtime that paddlex pulls in). ca-certificates for model download at build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/root \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GLOG_minloglevel=2

WORKDIR /app

# Dependencies first (pinned, verified — see README) so the heavy layer caches.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Bake the detection + recognition models into the image so the first real
# request doesn't pay a model download. Uses the SAME PaddleOCR construction as
# app.py, cached under $HOME/.paddlex (HOME is fixed above for build AND run).
# DISABLE_MODEL_SOURCE_CHECK skips a slow/flaky pre-download connectivity probe.
# (paddleocr 3.7.0 default English models = PP-OCRv6_medium det/rec, ~133 MB.)
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN python -c "import numpy as np; from paddleocr import PaddleOCR; \
    o = PaddleOCR(lang='en', device='cpu', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False); \
    o.predict(np.full((60, 300, 3), 255, dtype=np.uint8)); print('models baked into image')"

EXPOSE 8099

# Container-level readiness: /health flips to 200 only after the model loads.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=3).status==200 else 1)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099", "--workers", "1"]
