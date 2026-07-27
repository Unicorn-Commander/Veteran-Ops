# valor-paddle-ocr

Self-contained **PaddleOCR** HTTP OCR service, CPU-only, in one Docker image.

It is two things at once:
1. A **benchmark target** for the OCR A/B (PaddleOCR vs. dots.ocr).
2. The **artifact we deploy to the fleet** if PaddleOCR wins.

It implements the exact contract the valor backend already calls
(`backend/app/intake/ocr.py` → `_ocr_paddle`): a multipart `POST /ocr` that
returns `{"text": ...}`.

---

## Contract

| Method | Path      | Request                                             | Response |
|--------|-----------|-----------------------------------------------------|----------|
| `POST` | `/ocr`    | multipart form, one file field named exactly `file` | `{"text": "<transcription>", "engine": "paddleocr", "version": "<pp-ocr>"}` |
| `GET`  | `/health` | —                                                   | `{"status": "ok"}` (HTTP 200) once models are loaded; `503 {"status":"loading"}` before |

- A bad/undecodable image never 500s — it returns `{"text": "", ...}` (the
  caller treats an empty read as a miss and falls through).
- Text is returned in reading order: detected boxes are clustered into visual
  lines, lines sorted top-to-bottom, boxes within a line left-to-right. A table
  row's label and value land on the **same output line** (space-joined); lines
  are newline-joined. Keeps `Label   Value` rows together and single-column
  prose readable.

---

## Build

Run from the repo root (`/Users/aaronstransky/valor-ops`):

```bash
docker build -t valor-paddle-ocr tools/paddle-ocr
```

The build **bakes the OCR models into the image** (a warmup step downloads the
PP-OCR det+rec models, ~133 MB, into `/root/.paddlex`), so the first real
request is fast — no cold-start download.

### Architecture note (important)

One arch-agnostic Dockerfile; `pip` picks the right `paddlepaddle` wheel per
platform:

- **On this Apple-Silicon Mac** `docker build` defaults to `linux/arm64` → the
  native aarch64 wheel. Fast, and the right choice for the local bench.
- **For the x86_64 fleet** build `--platform linux/amd64` → the `x86_64` wheel:

  ```bash
  docker build --platform linux/amd64 -t valor-paddle-ocr tools/paddle-ocr
  ```

`paddlepaddle==3.2.0` is pinned precisely because it is the **newest release
that ships BOTH** an `x86_64` (AVX, fleet) and an `aarch64` (Apple Silicon)
cp311 wheel. 3.3.x dropped aarch64.

> The stock `x86_64` paddle wheel is **AVX-compiled**. It runs on real fleet
> CPUs (which have AVX/AVX2) but **SIGILLs under macOS/Rosetta emulation**
> (Rosetta exposes only up to SSE4.2). So the local image is built/run native
> arm64; the amd64 image is for the real fleet, not for Rosetta. See Pitfalls.

---

## Run (host port 8099)

```bash
docker run -d --name valor-paddle-ocr -p 8099:8099 valor-paddle-ocr

# wait for readiness
curl -s http://localhost:8099/health      # -> {"status":"ok"} once loaded
```

Wire the valor backend to it:

```
OCR_ENGINE=paddle
OCR_BASE_URL=http://localhost:8099
```

### Smoke test

```bash
curl -s -F "file=@/path/to/page.png" http://localhost:8099/ocr
# {"text":"...","engine":"paddleocr","version":"PP-OCRv6_medium"}
```

---

## Configuration (env)

| Var | Default | Meaning |
|-----|---------|---------|
| `OCR_LANG` | `en` | PaddleOCR language. |
| `PP_OCR_VERSION` | auto-detected from the baked recognition model | Overrides the `version` string in responses. |
| `OCR_DET_MODEL` | (unset → PP-OCRv6_medium_det) | Pin a specific detection model. |
| `OCR_REC_MODEL` | (unset → PP-OCRv6_medium_rec) | Pin a specific recognition model. |

### PP-OCRv6 vs. PP-OCRv5

The task asked for **PP-OCRv5** (fallback v4). In `paddleocr==3.7.0` the English
default is actually the newer **PP-OCRv6_medium** det/rec pair — it installs
cleanly and reads the VA test tokens perfectly, so it is the shipped default and
the `version` field honestly reports `PP-OCRv6_medium`.

To pin **PP-OCRv5** instead (e.g. for strict A/B comparability), set the model
names and rebuild so they bake:

```dockerfile
ENV OCR_DET_MODEL=PP-OCRv5_server_det \
    OCR_REC_MODEL=PP-OCRv5_server_rec
```
(or `PP-OCRv5_mobile_det` / `PP-OCRv5_mobile_rec` for the smaller/faster CPU
pair). Setting them only at `docker run` works too, but the models then download
on first startup instead of being baked.

---

## Pinned versions (verified working together)

| Package | Version | Note |
|---------|---------|------|
| `paddlepaddle` | `3.2.0` | newest with **both** x86_64 + aarch64 cp311 wheels |
| `paddleocr` | `3.7.0` | default English engine = PP-OCRv6_medium |
| `paddlex` | `3.7.2` | pulled by `paddleocr[ocr-core]`; pinned to lock resolution |
| `numpy` | `2.3.5` | paddlex requires `<2.4,>=1.24`; 2.3.5 verified (no ABI break) |
| `pillow` | `12.3.0` | |
| `fastapi` | `0.115.6` | |
| `uvicorn[standard]` | `0.34.0` | |
| `python-multipart` | `0.0.20` | multipart upload parsing |

Base image `python:3.11-slim-bookworm`. System libs: `libgomp1` (paddle OpenMP),
`libgl1` + `libglib2.0-0` (opencv runtime).

---

## Pitfalls hit (and how they were solved)

1. **AVX SIGILL under Rosetta.** The stock PyPI `paddlepaddle` x86_64 wheel is
   AVX-compiled; on this Mac the amd64 image crashes with `Illegal instruction`
   (exit 132) on `import paddle`, because Rosetta advertises only up to
   `sse4_2` (no `avx`/`avx2`/`fma`). This is emulation-only — real fleet x86_64
   CPUs have AVX. **Fix:** build/run native per arch. The local image is
   `linux/arm64` (native aarch64 wheel, no AVX involved); the fleet image is
   `--platform linux/amd64`.

2. **paddlepaddle 3.3.x has no aarch64 wheel.** Can't build natively on Apple
   Silicon. **Fix:** pinned `paddlepaddle==3.2.0`, the newest release that still
   ships both x86_64 and aarch64 cp311 wheels — one Dockerfile, both arches.

3. **`libgomp.so.1: cannot open shared object file`.** `python:3.11-slim` lacks
   the OpenMP runtime paddle needs. **Fix:** `apt-get install libgomp1`.

4. **opencv `libGL.so.1` missing.** `paddlex[ocr-core]` pulls the non-headless
   `opencv-contrib-python`, which needs system GL libs. **Fix:** `apt-get
   install libgl1 libglib2.0-0`.

5. **`paddlepaddle` is NOT a `paddleocr` dependency.** `paddleocr`→`paddlex` does
   not declare (or pin) `paddlepaddle` — you must install it yourself. Good news:
   there is therefore **no paddle/paddlex version-conflict trap**; pin paddle
   independently.

6. **paddleocr 3.7.0 defaults to PP-OCRv6, not v5** (see the section above).
   Documented + made configurable rather than silently shipped.

7. **Model download during build.** Models fetch from HuggingFace Hub at build
   time. **Fix:** a warmup `RUN` bakes them into the image; a slow pre-download
   "connectivity check" is skipped with
   `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`. If HF is unreachable in your
   build env, set `PADDLE_PDX_MODEL_SOURCE=BOS` to use Baidu's mirror.
