# Golden evaluation gate

Veteran-Ops has a deterministic, de-identified release gate for eight
high-consequence behaviors: OCR cross-read disagreement, evidence gaps, combined
rating math, deadline ordering, source citations, abstention from invented
ratings or diagnostic codes, presumptive matching (ALS/POW branching), and
condition-name auto-alias collapse from chart/OCR spellings.

Run it from the backend directory:

```bash
python -m evals.golden
```

The command prints a machine-readable report and exits nonzero if any expected
result changes. CI runs the same command. The cases in
`backend/evals/fixtures/golden_cases.json` are synthetic and derived from existing
regression-test vectors; they contain no veteran records.

This gate detects deterministic regressions. It is not a clinical, legal, OCR, or
model-accuracy certification. Before changing an expected result, require review
from the product owner and a VA-accredited domain expert. Expand the suite only
with de-identified or synthetic cases whose expected outcomes have been reviewed.
