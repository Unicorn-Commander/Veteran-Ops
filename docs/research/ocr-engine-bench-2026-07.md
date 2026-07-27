# OCR engine A/B — dots.ocr vs PaddleOCR vs Tesseract (2026-07-12)

**Question:** does PaddleOCR read VA-claim documents better than dots.ocr, and does
image preprocessing help? **Answer:** they are near-parity on the tokens that decide
a rating; the real win is **preprocessing the page before dots** (96.5 → 99.3
critical-F1), and paddle's value is as a **decorrelated second reader**, not a
replacement.

## Method

- **Corpus:** `tools/ocr-bench/` — 24 images = 6 synthetic VA-doc base pages (2 rating
  decisions, 2 C&P exams, 2 DBQs; PII-free, known ground truth) × 4 degradation levels
  (L0 clean, L1 mild skew+blur, L2 JPEG+contrast, L3 low-DPI+noise+heavy skew). Seed
  1337, byte-reproducible.
- **Scoring:** overall CER accuracy (1 − normalized Levenshtein) plus — the number that
  matters — **critical-token F1** over the four classes a rating turns on (evaluation
  percent, 4-digit diagnostic code, date, decision word), using the *production*
  extractors in `backend/app/intake/crossread.py` so the bench measures exactly what
  intake cares about.
- **Engines:** dots.ocr (vLLM vision on the fleet 3060), PaddleOCR PP-OCRv6_medium
  (`tools/paddle-ocr/`, CPU), Tesseract 5.5.2 baseline — each run raw and with the
  `backend/app/intake/preprocess.py` transform.

## Result (critical-token F1, all 24 pages)

| Engine | Critical-F1 | L0 clean | L3 low-DPI (hardest) | Latency med |
|---|---:|---:|---:|---:|
| dots-ocr | 96.5 | 100.0 | 85.3 | 5.5s |
| **dots-ocr + preprocess** | **99.3** | 100.0 | **97.2** | 6.6s |
| paddle | 97.9 | 100.0 | 92.5 | 15.0s |
| paddle + preprocess | 97.9 | 100.0 | 91.2 | 16.3s |
| tesseract | 83.8 | 100.0 | 31.1 | 0.3s |
| tesseract + preprocess | 77.0 | 83.6 | 0.0 | 0.6s |

## What the numbers say

1. **Preprocessing dots is the single biggest win.** Deskew + upscale + denoise (the
   *gentle*, non-binarize mode) lifts dots from 96.5 → **99.3** by rescuing the low-DPI
   tier, where raw dots transposed diagnostic-code digits (L3 DC-F1 63.2 → 90.0). No
   regression on clean/mild tiers. This inverts the naive assumption that a vision model
   never benefits from preprocessing — upscaling small glyphs clearly helps it.
2. **Paddle ≈ dots on rating fidelity** (97.9 vs 96.5 raw) and is *more robust than raw
   dots on bad scans* (L3 92.5 vs 85.3) — but ~3× slower (CPU vs dots on GPU) and not
   better than dots+preprocess. So paddle is not a primary-engine replacement; it is the
   best **decorrelated second reader** — a traditional OCR that fails *differently* from
   a vision LLM, which is exactly what the cross-read needs to catch dots' residual
   digit errors.
3. **Never binarize.** Otsu two-tone wrecks traditional OCR on noise (tesseract L3 →
   0.0) and adds nothing for dots. `ocr_preprocess_binarize` stays off.
4. **Tesseract is not a viable rating reader** — it collapses on noisy scans (L3 31.1,
   and 0.0 with binarize). Baseline only.

## Recommended production config

- `OCR_ENGINE=dots` — unchanged primary (GPU, fast, and now preprocessing-boosted).
- `OCR_PREPROCESS=true`, `OCR_PREPROCESS_BINARIZE=false` — the measured best (99.3).
- `OCR_CROSSREAD_ENGINE=paddle` + `OCR_CROSSREAD_BASE_URL=<fleet paddle>` — deploy the
  paddle service (`tools/paddle-ocr/`, built `--platform linux/amd64` for the fleet) as
  the decorrelated second reader so dots' residual low-DPI digit errors get flagged.

## Caveat

The corpus is *synthetic* (rendered text + programmatic degradation), so it validates
direction and relative ordering, not absolute field accuracy on real faxed/stamped
C-file scans. The production two-engine cross-read on real documents is the ongoing
real-world A/B — its per-page disagreement log is the live signal. Re-run any time:
`tools/ocr-bench/.venv/bin/python tools/ocr-bench/bench.py --dots-url <…> --dots-model dots-ocr --paddle-url <…> --tesseract --preprocess`.
