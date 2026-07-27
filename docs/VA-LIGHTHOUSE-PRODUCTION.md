# VA Lighthouse — production access package

Operator checklist for requesting **production** credentials at
[developer.va.gov](https://developer.va.gov) for Rating Raider (Valor host:
`https://valor.magicunicorn.dev`).

**Do not enable production without approved credentials.** Empty `VA_CLIENT_ID`
keeps `va_enabled=False` and every `/api/va/*` endpoint degrades cleanly. Never
commit secrets into the repo.

---

## 1. What was sandbox-tested

### Connector design (`backend/app/va/`)

| Module | Role |
|--------|------|
| `lighthouse.py` | OAuth2 **Authorization Code + PKCE (S256)** against per-API Lighthouse authorization servers; confidential client (HTTP Basic) when `VA_CLIENT_SECRET` is set, public PKCE-only when empty |
| `normalize.py` | Pure response normalizers + diff-style sync suggestions (never auto-applies) |
| `service.py` | RLS-fenced `va_connections` token store; encrypt-at-rest; refresh; reconnect bookkeeping |
| `legal.py` | Plain-language terms + privacy served at `GET /api/legal` (prod prerequisite) |
| `routers/va.py` | Connect / callback / sync / claims / disconnect surfaces |

API families wired in `APIS` (see `lighthouse.py`):

1. **Veteran Service History and Eligibility** (`verification`)
   - OAuth slug: `veteran-verification`
   - Data: `/services/veteran_verification/v2`
   - Scopes: `openid profile offline_access service_history.read disability_rating.read permanent_and_total_disability.read veteran_status.read`
2. **Benefits Claims** (`claims`)
   - OAuth slug: `claims`
   - Data: `/services/claims/v1`
   - Scopes: `openid profile offline_access claim.read claim.write`

Redirect URI built as `{VA_REDIRECT_BASE or SSO_REDIRECT_BASE}/api/va/callback`
and must match the developer portal registration **exactly**.

### Sandbox validator (non-interactive)

```bash
# From backend/ with network access:
VA_BASE_URL=https://sandbox-api.va.gov \
  python scripts/validate_va_sandbox.py
# or:  .venv/bin/python scripts/validate_va_sandbox.py
```

`backend/scripts/validate_va_sandbox.py` fetches each API family's live sandbox
`.well-known/openid-configuration` and asserts that authorization, token, and
revocation URLs, requested scopes, and `client_secret_basic` match what our
connector constructs. This is the automated "tested against sandbox" gate for
endpoint / scope / auth-method drift.

**What it cannot prove** (needs interactive OAuth as a VA sandbox test user):

- Live authorization-code exchange
- Real `/disability_rating` + `/service_history` data pull

Those remaining E2E steps are covered by `backend/tests/manual_va_sandbox.py`
(operator-driven; not collected by pytest). Response **parsing** is covered by
`normalize` unit tests.

### Readiness script

```bash
# From repo root (optional VALOR_BASE_URL override):
./scripts/va-production-readiness.sh
```

Checks public legal + meta surfaces, optionally re-runs the sandbox validator,
and reports whether `VA_CLIENT_ID` is set in the environment **without printing
secret values**.

---

## 2. developer.va.gov production request checklist

Apply at [https://developer.va.gov/onboarding](https://developer.va.gov/onboarding)
(or your existing app's **Request production access** flow).

### APIs to request

- [ ] **Veteran Service History and Eligibility**
- [ ] **Benefits Claims**

### OAuth grant

- [ ] **Authorization Code** grant
- [ ] **PKCE** required (S256 — the only method VA documents for these families)

### Redirect URI(s)

Register **exactly**:

| Environment | Redirect URI |
|-------------|--------------|
| Dogfood / current public host | `https://valor.magicunicorn.dev/api/va/callback` |
| Additional prod host (if any) | `https://<prod-host>/api/va/callback` |

Optional local/dev redirects only if the portal allows them on the **sandbox**
client; production clients should list only production HTTPS callbacks.

### Public terms & privacy URLs

VA reviews live, public terms and privacy pages.

| Surface | URL | Notes |
|---------|-----|--------|
| **SPA page (prefer for the portal)** | `https://valor.magicunicorn.dev/legal` | Frontend route `/legal` renders markdown from the API |
| **JSON API (source of truth)** | `https://valor.magicunicorn.dev/api/legal` | Unauthenticated `GET` → `{ "terms": "...", "privacy": "..." }` markdown |

Both are live today. Submit the **SPA** URL unless the reviewer asks for the
raw API. Keep copy in `backend/app/va/legal.py` as the single source of truth.

### Privacy posture summary (from `app/va/legal.py`)

Use this language (or paste the full privacy markdown) in the application:

- **Self-help educational software** — not a VA-accredited representative; not
  affiliated with VA; the veteran always drives.
- **No sale of veteran data. Ever.** Not to advertisers, lead generators,
  partners, aggregate, or anonymized resale.
- **VA connection is consented at VA.gov** (Login.gov / ID.me). We never receive
  the veteran's VA.gov password. Tokens are stored per-account, encrypted at
  rest, never logged; disconnect revokes and deletes them.
- **No write-back without explicit per-action confirmation** (e.g. Intent to File
  only when the veteran confirms).
- **Access & deletion rights** — export and full account deletion available in-app.
- **AI default local** — document/PII text is not sent to third-party AI unless
  the veteran deliberately opts in.

### Demo video / screenshots checklist

Prepare short clips or stills that show:

- [ ] Login / first-run legal disclaimer (from `GET /api/meta`)
- [ ] Settings → Connect VA (OAuth handoff framing; no password collection)
- [ ] VA.gov consent screen (sandbox test user is fine for the recording)
- [ ] Post-callback “connected” state and **Disconnect** control
- [ ] Sync **preview** of service history / ratings (confirm-before-apply, no silent overwrite)
- [ ] Claims status view (read path)
- [ ] Intent-to-File flow if demoed: explicit confirm step + audit trail mention
- [ ] Terms (`/legal`) and Privacy sections visible publicly without login
- [ ] Account export / delete controls (privacy rights)

Keep demos on **sandbox** credentials until production keys are issued.

---

## 3. Env vars after approval

Set on the **host** (e.g. `infrastructure/.env` on app-host). **Do not commit values.**

| Variable | Required | Value / notes |
|----------|----------|----------------|
| `VA_CLIENT_ID` | Yes | Production client id from developer.va.gov |
| `VA_CLIENT_SECRET` | Optional | Set for confidential client; leave empty for public PKCE-only |
| `VA_TOKEN_ENCRYPTION_KEY` | Yes (≥32 chars) | Independent high-entropy secret; **not** `JWT_SECRET` |
| `VA_BASE_URL` | Yes | `https://api.va.gov` (production; sandbox is `https://sandbox-api.va.gov`) |
| `VA_REDIRECT_BASE` | Recommended | `https://valor.magicunicorn.dev` (falls back to `SSO_REDIRECT_BASE` if empty) |

Feature gate (`settings.va_enabled`) is true only when **all** of:

- non-empty `VA_CLIENT_ID`
- non-empty `VA_BASE_URL`
- non-empty public base (`VA_REDIRECT_BASE` or `SSO_REDIRECT_BASE`)
- `VA_TOKEN_ENCRYPTION_KEY` length ≥ 32

Until then, dogfood correctly reports `va_enabled: false` in `GET /api/meta`.

---

## 4. Post-approval smoke steps

1. **Config gate**
   - `GET /api/meta` → `"va_enabled": true`
   - `GET /api/legal` → non-empty `terms` and `privacy`
2. **OAuth round-trip (production, real veteran or approved test account)**
   - Settings → Connect VA → complete Login.gov/ID.me consent
   - Land on `/settings` with connected state; no token material in browser storage logs
3. **Data read**
   - Trigger sync; confirm service history / disability rating preview appears
   - Confirm claims list loads when the claims connection is authorized
4. **Write path (only if demoing ITF)**
   - Explicit confirm UI; audit log entry; no silent file
5. **Disconnect**
   - Disconnect in-app; confirm tokens cleared and VA endpoints require reconnect
6. **Readiness script**
   ```bash
   VALOR_BASE_URL=https://valor.magicunicorn.dev ./scripts/va-production-readiness.sh
   ```
7. **Regression**
   - Sandbox validator is **not** valid against `api.va.gov` for production
     metadata drift; re-run it only with `VA_BASE_URL=https://sandbox-api.va.gov`
     if you still maintain a sandbox client.

---

## Related paths

| Path | Purpose |
|------|---------|
| `backend/app/va/lighthouse.py` | OAuth + API client |
| `backend/app/va/legal.py` | Terms + privacy markdown |
| `backend/scripts/validate_va_sandbox.py` | Live sandbox metadata checks |
| `backend/tests/manual_va_sandbox.py` | Interactive sandbox E2E |
| `scripts/va-production-readiness.sh` | Public surface + config readiness |
| `infrastructure/.env.example` | Documented env keys (no secrets) |
