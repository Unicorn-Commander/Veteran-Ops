# Evaluation card: <synthetic capability or rule set>

## Identity

- Card schema version: 1
- Evaluation ID: `<stable-slug>`
- Product release: `<release-id>`
- Rule version: `<rule-version>`
- KB verified as of: `<YYYY-MM-DD>`
- Evaluated commit/image: `<immutable revision>`
- Evaluation date: `<YYYY-MM-DD>`

## Safety classification

- Consequence level: `<low | medium | high>`
- Domains: `<rating math | evidence | deadline | OCR | citation | abstention | other>`
- Required reviewers: `<engineering | privacy | legal | VA-accredited domain expert>`
- Deployment decision: `<pass | conditional | fail>`

## Data statement

- Fixture origin: `<fully synthetic | de-identified public regression vector>`
- Contains real veteran records: `no` (required)
- Contains names, claim/file numbers, credentials, exact real dates, or document text: `no`
- Re-identification review completed by: `<reviewer/date>`
- Retention/location: `<repository fixture path; no external upload>`

Do not attach screenshots, prompts, traces, or logs copied from a veteran workspace.
Replace realistic identifiers with reserved UUIDs and `example.test` addresses.

## Claim under test

State one falsifiable behavior, the expected result, and the harm if it fails. Do not
state that an evaluation proves legal, medical, or VA accuracy beyond its fixtures.

## Method

- Entry point and command:
- Synthetic fixture IDs:
- Deterministic controls/seeds:
- Models/services and versions, if any:
- Primary sources and verification dates:
- Acceptance thresholds fixed before execution:

## Results

| Metric/case | Threshold | Result | Pass |
|---|---:|---:|---|
| `<case>` | `<threshold>` | `<result>` | `<yes/no>` |

- Abstentions reviewed:
- Citation/source fidelity reviewed:
- Cross-tenant/privacy negative cases reviewed:
- Accessibility or workflow impact reviewed:

## Limitations and residual risk

List unsupported populations, unseen document classes, model variance, stale-source
risk, and what requires live operator or accredited review. A passing card never
authorizes use of real veteran data in CI or synthetic monitoring.

## Approval

- Engineering:
- Privacy/security:
- Legal/domain:
- Product/operator:
- Follow-up owner and due date:
