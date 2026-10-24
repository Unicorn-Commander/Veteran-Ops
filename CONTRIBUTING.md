# Contributing to Veteran-Ops

Thanks for helping make Veteran-Ops clearer, safer, and more useful.

## Where this project actually lives

Veteran-Ops is developed on our own **Forgejo** instance at
`git.unicorncommander.ai/UnicornCommander/veteran-ops-oss`. That is the canonical
repository. Self-hosted, sovereign infrastructure is the point — this is software for
veterans' records, and we would rather not have its home depend on a platform we do not
control.

**GitHub is a downstream mirror.** It exists because that is where people look. It is
kept in sync automatically, one-way, from Forgejo.

**One consequence you need to know:** because the mirror force-syncs, *anything pushed
directly to the GitHub repository is overwritten on the next sync.* A branch created on
GitHub disappears; a pull request merged on GitHub is undone. This is not a policy
preference, it is how the mirror works. So:

| What you want to do | Where |
|---|---|
| **Report a bug, ask a question, propose an idea** | **GitHub Issues** — open to everyone, no account request needed. This is the fastest way to reach us. |
| **Send a code change** | **Open a PR on GitHub.** We will review it there and land it through Forgejo, then the mirror republishes it with your authorship intact. Do not be alarmed when the PR closes rather than showing as merged — your commit is in `master`. |
| **Work directly in the canonical repo** | Ask for a Forgejo account in a GitHub issue. Registration is invite-based, so this is a manual step, not a signup form. |

If you would rather your contribution never touch GitHub at all, say so in an issue and
we will arrange a Forgejo account or take a patch by email. That preference is
respected, not argued with.

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

## License

Contributions are made under the Apache License 2.0, the same licence as the repository (section 5). By opening a pull request you confirm you wrote the change or have the right to submit it under that licence.

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
