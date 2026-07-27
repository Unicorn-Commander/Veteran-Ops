# Contributing to Veteran-Ops

Thanks for helping make Veteran-Ops clearer, safer, and more useful.

## Before you start

- Read the project [README](README.md), legal boundary, and relevant docs.
- Keep changes small and explain the user-facing behavior they affect.
- Never use real veteran records, credentials, API keys, or private deployment details in code, tests, issues, or pull requests.

## Pull requests

Please include:

1. The problem and intended behavior.
2. Tests or behavior checks run.
3. Any legal, privacy, authorization, migration, or operator gates that remain.

Changes involving claim guidance, ranking, evidence language, or Rating Raider prompts need extra review for educational wording, non-fabrication, and no-outcome-promise behavior.

## Local checks

```bash
npm ci --prefix frontend
npm run build --prefix frontend
npm run test --prefix frontend -- --run
python -m pytest -q backend/tests/test_coach.py backend/tests/test_strategy.py
git diff --check
gitleaks detect --source .
trufflehog filesystem . --no-update
```

## Code of conduct

Be precise, patient, and respectful. Veterans may be working through stressful records and life circumstances. Do not provide individualized legal or medical advice in project discussions; point people toward a qualified provider or VA-accredited VSO.
