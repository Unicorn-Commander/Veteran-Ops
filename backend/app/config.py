"""Application settings (pydantic-settings, `.env`).

Mirrors the Glitter Mane suite pattern, trimmed to what Veteran-Ops needs:
Postgres+RLS, native JWT auth, uchub Keycloak SSO (entitlement-gated),
the UC LiteLLM gateway (deny-by-default model allowlist), bge-m3 embeddings,
and the optional Glitter Mane trusted-caller bridge. Product name: Veteran-Ops;
flagship agent: Rating Raider.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # populate_by_name: a field carrying a validation_alias (e.g. privacy_mode ←
    # VALOR_PRIVACY_MODE) stays constructible by its plain field name too, so direct
    # Settings(privacy_mode=…) construction (tests, programmatic use) still works.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Veteran-Ops"

    # Database — must be the non-superuser valor_app role for RLS to apply
    # (superusers and BYPASSRLS roles skip row-level security entirely).
    database_url: str = (
        "postgresql+asyncpg://valor_app:change_me_valor_app_pw@localhost:5434/valor"
    )

    # Auth
    jwt_secret: str = "change_me_to_a_long_random_string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days

    # Trusted suite callers (Brigade) — per-user auth via a SHARED SECRET, kept separate
    # from jwt_secret so a Brigade token can never be a native user token and vice versa.
    # Brigade sends Authorization: Bearer <HS256 JWT {sub|email:<user email>,
    # aud:"valor-ops", exp}>; Valor validates sig+aud+exp, resolves email -> its user,
    # and scopes RLS to them. Empty brigade_jwt_secret = this path is disabled.
    brigade_jwt_secret: str = ""
    brigade_audience: str = "valor-ops"
    brigade_auto_provision: bool = False  # opt-in: create a Valor user on first Brigade call

    # Open self-registration. True (dev default) = anyone can POST /auth/register. For a
    # public instance set ALLOW_REGISTRATION=false → registration is CLOSED, except the
    # very first account (bootstrap) so the operator can create their own login once;
    # after that the endpoint 403s. Existing users always log in normally.
    allow_registration: bool = True
    # Local email/password authentication can be disabled for an SSO-only hosted
    # instance. The public capability contract and auth endpoints both enforce this.
    password_login_enabled: bool = True
    # Instance-wide service settings change every workspace. Workspace ownership is
    # therefore not sufficient authority; only explicitly allowlisted operator emails
    # may read or mutate them. Empty (the default) disables the surface entirely.
    platform_admin_emails: str = ""

    # ── Transactional email (verify / reset / org invites / deadline digests) ────────
    # EMAIL_PROVIDER:
    #   "postmark" — Postmark HTTP API (POSTMARK_SERVER_TOKEN + EMAIL_FROM)
    #   "smtp"     — direct SMTP (SMTP_HOST + EMAIL_FROM; optional auth/TLS)
    #   "" / other — console fallback: LOG the message, never deliver (dev/degraded)
    email_provider: str = ""                     # "postmark" | "smtp" | "" (console/log)
    postmark_server_token: str = ""
    email_from: str = ""                         # e.g. "veteran-ops@magicunicorn.dev"
    email_from_name: str = "Veteran-Ops"
    # SMTP (used when EMAIL_PROVIDER=smtp). Password never logged.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True                    # STARTTLS (typical port 587)
    smtp_use_ssl: bool = False                   # implicit TLS (typical port 465)
    # Deadline Guardian email digests. Default on when a real mail provider is
    # configured; set DEADLINE_EMAILS_ENABLED=false to silence all deadline mail.
    # Per-user opt-out can land later; until then this instance flag is the gate.
    deadline_emails_enabled: bool = True
    # Token lifetimes (minutes) for the signed email-verify / password-reset links.
    verify_token_minutes: int = 60 * 24 * 3      # 3 days
    reset_token_minutes: int = 60                # 1 hour
    invite_expire_days: int = 14                 # org invitation validity

    # Require a verified email before sensitive org actions (creating/inviting to a
    # team). Individual veteran self-help is NEVER gated on verification.
    require_verified_email_for_orgs: bool = True

    # ── Billing (Wave 14 — suite-aligned; Lago drives subscriptions) ──────────────────
    # Valor-Ops does NOT own billing: an org's plan_tier is set by the suite's billing /
    # entitlement service (Lago). This app exposes a RECEIVER the suite calls to push a
    # tenant's tier, and reads plan_tier locally for feature gating. We never write to
    # Lago or the shared entitlement store from here.
    #
    # The receiver (POST /billing/tenant-tier) authenticates a suite service caller with
    # this bearer token (constant-time compared). EMPTY = the receiver is DISABLED (503)
    # so it can never be left accidentally open. Set to a strong shared secret that the
    # entitlement service / Lago webhook presents.
    billing_service_token: str = ""
    # Where an org owner manages their subscription — the suite billing portal (Lago
    # customer portal or the uchub billing page). Shown as "Manage billing"; empty hides
    # the link. Not a secret.
    billing_portal_url: str = ""
    # Whether self-serve upgrade is live yet. False (default) = the UI shows plans +
    # "contact us / managed by your account" instead of a checkout button, since the Lago
    # grant is operated by Aaron + the entitlement-service owner. Flip to true once the
    # portal/checkout is wired suite-side.
    billing_self_serve: bool = False

    # Maximum aggregate size of original uploads included in one account archive.
    # The JSON-only export remains available when an account exceeds this bound.
    account_export_max_bytes: int = 2 * 1024 * 1024 * 1024

    # Durable comprehensive-analysis worker. The API enqueues into Postgres; an
    # embedded worker is convenient for local development, while production compose
    # disables it on the API and runs the same worker loop as a separate service.
    analysis_worker_enabled: bool = True
    analysis_worker_required: bool = False
    analysis_worker_poll_seconds: float = 1.0
    analysis_job_lease_seconds: int = 300
    analysis_job_heartbeat_seconds: int = 30
    analysis_job_max_attempts: int = 3
    analysis_job_backoff_seconds: int = 15
    analysis_job_backoff_max_seconds: int = 300
    analysis_job_stale_kb_retry_seconds: int = 3600

    # Credit metering ENFORCEMENT. Off by default so the credit ledger ships dormant:
    # AI operations stay free and no veteran is ever blocked at 0 balance. Flip to true
    # ONLY once checkout is live and veterans can actually buy/receive credits — otherwise
    # this would 402 every existing user out of analysis/decode/intake.
    credits_enabled: bool = False

    # Stripe self-serve checkout for the consumer credit surface. Fail closed when these
    # are unset: no checkout session creation, no webhook processing, no live money path.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_currency: str = "usd"
    stripe_checkout_success_path: str = "/billing/success"
    stripe_checkout_cancel_path: str = "/billing"

    # ── Keycloak / unicorncommander.ai (uchub) SSO — OIDC Authorization Code ──────────
    # When keycloak_url is set, the app offers "Sign in with Unicorn Commander": the
    # backend redirects to Keycloak, handles the callback (code→token), validates the
    # id_token via JWKS, ENFORCES an entitlement gate, then mints a native Valor
    # session. Empty keycloak_url = SSO off (local email/password only).
    keycloak_url: str = ""                       # e.g. https://auth.unicorncommander.ai
    keycloak_realm: str = "uchub"
    keycloak_client_id: str = "valor-ops"
    keycloak_client_secret: str = ""
    # Public base of THIS app (used to build the OIDC redirect_uri + the frontend
    # landing). Must match the redirect URI registered on the Keycloak client.
    sso_redirect_base: str = ""                  # e.g. https://valor.magicunicorn.dev
    # Multi-host: valor is served at several hostnames (per suite instance), and we
    # want a veteran who signs in from one to LAND BACK on that same host. This is a
    # comma-separated allowlist of external hosts we may build an OIDC redirect for;
    # a login request whose Host is on this list uses https://<host> as its redirect
    # base (and each such callback URL must be registered on the Keycloak client).
    # Anything not listed falls back to sso_redirect_base — so the default single-host
    # deploy is unaffected. e.g. "valor.magicunicorn.dev,valor-ops.magicunicorn.dev".
    sso_allowed_hosts: str = ""
    # Entitlement gate (self-service is OFF): a uchub user may sign in ONLY if their
    # token carries sso_required_entitlement (looked up in the sso_entitlement_claim
    # list AND in realm/client roles) OR their email/domain is on the bootstrap
    # allowlist. Nobody else.
    sso_entitlement_claim: str = "entitlements"  # OIDC claim holding product keys
    sso_required_entitlement: str = "valor-ops"
    # Interim bootstrap allowlist: "a@x.com,@magicunicorn.tech". The spec names the env
    # var VALOR_SSO_ALLOWED_EMAILS; plain SSO_ALLOWED_EMAILS also works.
    sso_allowed_emails: str = Field(
        default="",
        validation_alias=AliasChoices("VALOR_SSO_ALLOWED_EMAILS", "SSO_ALLOWED_EMAILS"),
    )
    sso_auto_provision: bool = True              # create the Valor user on first ENTITLED login

    # ── LLM gateway (OpenAI-compatible; UC LiteLLM) ────────────────────────────────────
    # Points at the tailnet LiteLLM gateway routing to LOCAL models — veteran PII stays
    # on the fleet by default.
    llm_base_url: str = "http://localhost:4000/v1"
    llm_api_key: str = "sk-local"
    # Must match the id the gateway actually exposes for the local Qwen — it's
    # "qwen3.6-35b" on the UC gateway (NOT "…-a3b", which the gateway rejects with a
    # model-access 401 → the app would silently fall back to deterministic-only output).
    llm_model: str = "qwen3.6-35b"
    # Qwen3.x / many local servers emit a (possibly empty) <think> block unless told
    # not to. We pass chat_template_kwargs.enable_thinking=false AND strip
    # <think>…</think> from output as a belt-and-suspenders guarantee.
    llm_disable_thinking: bool = True
    # PII guard, deny-by-default: only the configured llm_model plus ids listed here
    # may be requested by a caller; anything else (e.g. a cloud id the gateway also
    # exposes) is dropped → the default LOCAL model is used. Add a cloud id here ONLY
    # to deliberately opt into off-box use.
    llm_allowed_models: str = ""

    # ── Model tiers ────────────────────────────────────────────────────────────────
    # The default llm_model handles per-record work (reading a veteran's documents,
    # enrichment on their own text) and ALWAYS stays local — PII never leaves the
    # fleet. `reasoning_model` is a (usually larger) model for the agent's
    # ORCHESTRATION + final-pass REVIEW, which reason over the deterministic findings +
    # public 38 CFR (not the raw record) — so it may be a bigger local model or, when
    # explicitly opted in, a frontier model. It falls back to llm_model when unset.
    reasoning_model: str = ""
    # Per-job-class tiers (quality-first): a job may route to a better (possibly
    # frontier) model without every call going through the heavy reasoning tier.
    # Empty = inherit reasoning_model → llm_model, so an unconfigured install runs
    # fully local. Wire real ids via env (BRIEFING_MODEL, EXTRACTION_MODEL,
    # CLASSIFICATION_MODEL) to turn quality-first on for those job classes.
    briefing_model: str = ""        # Battle-Plan narrative prose
    extraction_model: str = ""      # identity / decode / canonicalization (temp 0)
    classification_model: str = ""  # doc-type + field classification (temp 0, cheap)
    # PRIVACY MODE: when ON, any request carrying the veteran's own record text uses
    # ONLY a local/on-fleet model — inference never leaves the hardware the operator
    # controls. This is a selectable privacy guarantee (open-source self-hosters keep
    # it ON; the hosted unicorncommander.ai offering can let a user choose). When OFF,
    # PII-touching calls may use the configured (possibly hosted/cloud) reasoning tier.
    # `allow_cloud_for_pii` is the inverse of privacy_mode, kept as the operative flag.
    # DEFAULT True (privacy-first) is deliberately unchanged — self-host/OSS stays fully
    # local. The alias lets the hosted deploy set VALOR_PRIVACY_MODE=false (the name the
    # activation doc uses); plain PRIVACY_MODE also works. No env set → still True.
    privacy_mode: bool = Field(
        default=True,
        validation_alias=AliasChoices("VALOR_PRIVACY_MODE", "PRIVACY_MODE"),
    )

    @property
    def allow_cloud_for_pii(self) -> bool:
        return not self.privacy_mode

    # ── Embeddings (OpenAI-compatible; bge-m3) — optional; KB vector search degrades
    # gracefully to ILIKE when unset. ─────────────────────────────────────────────────
    embeddings_base_url: str = ""
    embeddings_api_key: str = "sk-local"
    embeddings_model: str = "bge-m3"
    embedding_dim: int = 1024

    # ── Reranker (cross-encoder; bge-reranker-v2-m3) — optional two-stage retrieval.
    # When set, retrieval widens the vector-recall net to `rerank_candidate_k` and a
    # cross-encoder reorders it for precision (the exact-DC-card win the firm needs).
    # UNSET = single-stage vector order (graceful, unchanged behaviour). The reranker
    # lives on the SAME fleet host as embeddings (Infinity :8086) so PII stays local.
    reranker_base_url: str = ""
    reranker_api_key: str = "sk-local"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidate_k: int = 20

    # ── KB freshness + curated refresh receiver ─────────────────────────────────────
    # Center Deep / a maintainer agent / a manual curator can POST curated, sourced,
    # dated KB updates to /kb/refresh with this bearer token. EMPTY = receiver disabled
    # (503) so it can never be left accidentally open.
    kb_refresh_service_token: str = ""
    # Periodic eCFR freshness check cadence. 0 disables the background loop while
    # leaving the explicit /kb/freshness endpoint available.
    kb_freshness_interval_hours: float = 24
    # Operational context recorded on refresh-needed signals. The current slice still
    # watches Title 38 as a whole; phase 2 can use these terms to route Center Deep.
    kb_freshness_monitored_terms: str = "38 CFR Part 4, VA rating schedule"

    # OCR service for scanned-document intake — optional; unset = pypdf text
    # layer then the vision-model fallback. Two engines (ocr_engine):
    #   "dots"   — a GPU-backed vLLM OpenAI VISION model (dots.ocr) called via
    #              {ocr_base_url}/chat/completions with the page image. ocr_base_url
    #              is the OpenAI base (…/v1); ocr_model is the model id. This is
    #              the fleet's real OCR: dots.ocr on the ocr-host RTX 3060.
    #   "paddle" — a PaddleOCR-style multipart POST {ocr_base_url}/ocr → {text}.
    # Default "paddle" for back-compat; prod runs "dots" on the 3060.
    ocr_base_url: str = ""
    ocr_engine: str = "paddle"
    ocr_model: str = "dots-ocr"
    ocr_api_key: str = ""  # optional bearer if the vLLM server was started with --api-key

    # Vision-capable LOCAL model for the scanned-image fallback (when the OCR
    # service misses or is unset). MUST be a multimodal id — the default text
    # llm_model has no mmproj projector and rejects image input. Auto-allowlisted
    # (see allowed_models) so the PII guard permits it for image transcription
    # while still keeping it on the fleet. Empty = no vision fallback.
    vision_model: str = "qwen3.6-vision"

    # Cross-read SECOND engine: each scanned page is read by a second, decorrelated
    # engine so a misread (50 vs 70) is caught, not silently filed. "vision" (default)
    # = the local vision model; "paddle" = a traditional PaddleOCR service at
    # ocr_crossread_base_url. Pairing a TRADITIONAL OCR (paddle) with a VISION-LLM
    # primary (dots) is the MOST decorrelated pairing — they fail differently — and
    # offloads one read to CPU. Empty base_url falls back to the vision model. The
    # cross-read's per-page disagreements ARE the dots-vs-paddle comparison — turn
    # this on to see which engine to trust before switching ocr_engine wholesale.
    ocr_crossread_engine: str = "vision"     # "vision" | "paddle"
    ocr_crossread_base_url: str = ""

    # Image preprocessing before OCR (deskew / upscale / denoise / contrast, Pillow+
    # numpy — no OpenCV, so no new deploy deps). Helps TRADITIONAL OCR on skewed,
    # low-DPI, speckled scans; a vision-LLM primary may not need it (and hard
    # binarize can hurt it), so it is OFF by default — MEASURE with tools/ocr-bench
    # before enabling. ocr_preprocess_binarize adds an Otsu two-tone pass (good for
    # PaddleOCR/Tesseract, usually bad for a vision model).
    ocr_preprocess: bool = False
    ocr_preprocess_binarize: bool = False

    # Max documents processed (OCR + LLM) concurrently by the intake pipeline.
    # A massive dump (a whole C-file, hundreds of files) drains as an orderly
    # queue of this width instead of stampeding the OCR service / LLM gateway.
    # Env: INTAKE_CONCURRENCY.
    # Default 4: fills multi-GPU batch capacity without stampeding OCR (see
    # docs/FLEET-LLM-ROUTING.md). Env: INTAKE_CONCURRENCY.
    intake_concurrency: int = 4
    # Cap how many ~24k-char classify windows we run per document (head/tail +
    # evenly spaced middle samples). A 600k Blue Button is ~27 windows; without
    # a cap serial/parallel LLM work pegs the fleet for 30–60+ min per file and
    # blocks the intake queue for every customer behind it. Env:
    # INTAKE_CLASSIFY_MAX_SEGMENTS.
    intake_classify_max_segments: int = 9
    # Concurrent classify segments within one document (match batch P40 slots).
    # Env: INTAKE_CLASSIFY_CONCURRENCY.
    intake_classify_concurrency: int = 3
    # Hard wall-clock budget for one document's full intake (OCR+classify+…).
    # Prevents a hung OCR/LLM call from holding a semaphore slot forever.
    # Env: INTAKE_DOC_TIMEOUT_SECONDS.
    intake_doc_timeout_seconds: int = 900
    # On boot (and recoverable ops), fail docs stuck in status=processing longer
    # than this — worker restarts used to leave them pegging UX forever.
    # Env: INTAKE_STUCK_MINUTES.
    intake_stuck_minutes: int = 20
    # Whole-document read (quality-first): read EVERY page (not head+tail) and
    # classify every segment so a condition buried deep in a C-file is seen, not
    # dropped. The cheap PDF text layer is always read in full under full_read;
    # ocr_full_read_max_pages bounds the expensive scanned-OCR path even then (a
    # giant scanned file still needs a ceiling). Default ON.
    full_read_default: bool = True
    ocr_full_read_max_pages: int = 500

    # ── Phase 3 intake: extract-verify + whole-C-file comprehension ────────────────
    # A veteran-data-fidelity guarantee, but each is an EXTRA model pass over the
    # record, so they're switchable like the heavier deep-dive entry points.
    # intake_verify_default: a 2nd (decorrelated) pass that must QUOTE the source for
    #   every extracted (condition,%,DC,decision); a disputed/unsupported value is
    #   flagged for the veteran to reconcile — NEVER silently persisted. Default OFF so
    #   an unconfigured/offline install (and the unit suite) never depends on a live
    #   gateway during intake; turn ON in prod (INTAKE_VERIFY=true) for the fidelity gate.
    # comprehension_on_intake: run the whole-C-file map-reduce (mappass→CFilePicture)
    #   as a background job after a document lands ready. Default OFF for the same
    #   reason; the OCR cross-read (pure, no model) is always on when two engines ran.
    intake_verify_default: bool = False
    comprehension_on_intake: bool = False

    # ── Exhaustive rating deep dive ────────────────────────────────────────────────
    # Candidate experts share one bounded gateway fan-out.  Each proactive entry
    # point is independently switchable so an operator can pause one source without
    # disabling the veteran-requested read/run endpoints.  The periodic sweep is OFF
    # by default; when enabled it uses the interval below.
    # Parallel firm/deep-dive experts. Gateway least-busy spreads across GPUs.
    # Env: DEEP_DIVE_CONCURRENCY.
    deep_dive_concurrency: int = 6
    # on_analysis OFF by default: a cache-miss deep dive is a MANY-expert LLM fan-out
    # (far heavier than the single-call briefing), so we never run it synchronously
    # inside GET /strategy/deepdive — that risks a slow battle-plan load / gateway
    # timeout. The dive still populates proactively on intake + rule-change (both
    # background) and on the explicit POST /deepdive/run; GET just serves cache.
    deep_dive_on_analysis: bool = False
    deep_dive_on_intake: bool = True
    deep_dive_on_schedule: bool = False
    deep_dive_on_rule_change: bool = True
    deep_dive_schedule_interval_hours: float = 24

    # ── Theory origination (Phase 2b) ──────────────────────────────────────────────
    # The firm may ORIGINATE reasoned service-connection / nexus / secondary theories
    # ABOVE the deterministic floor — cited, confidence-tagged, and passed through the
    # reviewer's well-foundedness gates. OFF by default: the deterministic floor ships
    # ALONE until the theory layer is validated. Flip to true to let the opted-in
    # TheorySpecialist propose theories the pure rules did not. The floor NEVER changes.
    theory_origination_enabled: bool = False
    # A theory's confidence is CLAMPED into this band so an originated theory can never
    # present as the deterministic floor (1.0) nor as zero-confidence noise — it always
    # reads as an opinion (0 < confidence < 1), never as settled fact.
    theory_confidence_floor: float = 0.05
    theory_confidence_ceiling: float = 0.85

    # ── Glitter Mane seam (optional; empty = off) ──────────────────────────────────────
    # Env-level trusted caller: Valor mints a brigade-style HS256 JWT
    # {email, aud: glitter_audience, exp} signed with glitter_bridge_secret and calls
    # the Glitter Mane REST API to pull conditions/continuity for the SAME email.
    glitter_base_url: str = ""       # e.g. https://glittermane.magicunicorn.dev
    glitter_bridge_secret: str = ""  # must equal GM's BRIGADE_JWT_SECRET
    glitter_audience: str = "glitter-mane"

    # ── Center Deep research (per suite deployment) ───────────────────────────────────
    # A nexus letter is strongest when the provider's rationale cites medical
    # literature. We hand the veteran/provider a Center Deep deep-research link with a
    # DE-IDENTIFIED query (the condition + causal theory — never the veteran's record),
    # on the Center Deep instance that matches the valor host they're on. Default map
    # keeps unicorncommander.ai → the prod research instance, everything else → the dev
    # one; override per env if a host needs a specific instance.
    center_deep_url_default: str = "https://research.magicunicorn.dev"
    center_deep_url_unicorncommander: str = "https://research.unicorncommander.ai"

    # ── VA Lighthouse (developer.va.gov) — veteran-consented connection ───────────────
    # OAuth2 Authorization Code Grant + PKCE (S256): the VETERAN signs in at VA.gov
    # (Login.gov / ID.me) and consents; Rating Raider only ever holds tokens issued on
    # their behalf. Lighthouse OAuth is per-API family (each has its own authorization
    # server under {va_base_url}/oauth2/{api}/v1/...). Empty va_client_id = feature off
    # (endpoints degrade cleanly). va_client_secret set → confidential client
    # (HTTP Basic at the token endpoint) IN ADDITION to PKCE; empty → public PKCE-only.
    va_client_id: str = ""
    va_client_secret: str = ""
    # Application-layer encryption for veteran-consented OAuth credentials at rest.
    # This must be an independent, high-entropy secret (>=32 chars), not JWT_SECRET.
    # VA connectivity stays disabled until it is configured so plaintext tokens can
    # never be introduced by an otherwise-valid Lighthouse configuration.
    va_token_encryption_key: str = ""
    va_base_url: str = "https://sandbox-api.va.gov"  # prod: https://api.va.gov
    # Public base used to build the registered redirect URI; falls back to
    # sso_redirect_base so one env var covers the common single-host deploy.
    va_redirect_base: str = ""

    cors_origins: str = "http://localhost:5174,http://localhost:8080"

    # ── Derived helpers ────────────────────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.embeddings_base_url)

    @property
    def reranker_enabled(self) -> bool:
        return bool(self.reranker_base_url)

    def _tier_model(self, tier: str) -> str:
        """Map a job-class tier to its configured model id, inheriting
        reasoning_model then the local llm_model when a tier is unconfigured. With
        every tier field empty (the default) this returns llm_model for ALL tiers,
        so an unconfigured install is fully local."""
        m = {
            "reasoning": self.reasoning_model,
            "briefing": self.briefing_model or self.reasoning_model,
            "extraction": self.extraction_model or self.reasoning_model,
            "classification": self.classification_model or self.reasoning_model,
        }.get(tier, "")
        return m or self.llm_model

    @staticmethod
    def is_off_fleet_model(model_id: str) -> bool:
        """True when *model_id* is a cloud / frontier id that must not see PII
        under privacy mode.

        On-fleet local aliases (qwen3.6-35b, qwen3.6-35b-64k long pool, vision,
        strix, …) return False so a local long-context model is allowed even
        when it differs from llm_model. Cloud-looking ids return True.
        """
        m = (model_id or "").strip().lower()
        if not m:
            return False
        # Explicit on-fleet / local naming — never treat as off-box.
        if m.startswith((
            "qwen", "strix", "medgemma", "llama", "kokoro", "tts-", "dots",
            "local", "custom-",
        )):
            return False
        markers = (
            "cloud", "frontier", "gpt-", "claude", "openai", "anthropic",
            "openrouter", "deepseek", "gemini",
        )
        return any(x in m for x in markers)

    def model_for(
        self, *, tier: str = "default", touches_pii: bool = False,
        privacy_mode: bool | None = None,
    ) -> str:
        """Resolve the model id for a call. `tier` selects a job-class model
        (reasoning/briefing/extraction/classification); 'default' → local llm_model.
        A call that touches the veteran's own record is FORCED off cloud/frontier
        models when privacy mode is ON — PII stays on the fleet. Other *local*
        aliases (e.g. long-context qwen3.6-35b-64k) remain allowed. `privacy_mode`
        overrides the env/global default for THIS call (e.g. a per-workspace
        toggle); None → the global."""
        pm = self.privacy_mode if privacy_mode is None else privacy_mode
        chosen = self._tier_model(tier)
        if touches_pii and pm and self.is_off_fleet_model(chosen):
            return self.llm_model
        return chosen

    @property
    def allowed_models(self) -> set[str]:
        """Model ids a caller may request (the steer-guard allowlist). Includes the
        vision model (a LOCAL multimodal id) and every configured tier id so
        quality-first routing isn't silently dropped back to local by the gateway.
        This is the steer-guard, NOT the PII guard — model_for enforces PII→local."""
        s = {
            self.llm_model, self.vision_model, self.reasoning_model,
            self.briefing_model, self.extraction_model, self.classification_model,
        }
        s |= {m.strip() for m in self.llm_allowed_models.split(",") if m.strip()}
        return {m for m in s if m}

    @property
    def public_base(self) -> str:
        """Public https base of THIS app, used to build email links (verify / reset /
        invite). Reuses the SSO redirect base (the one already registered)."""
        return (self.sso_redirect_base or self.va_redirect_base).rstrip("/")

    @property
    def email_enabled(self) -> bool:
        """Real email delivery is configured. False → the console/log fallback."""
        if not self.email_from:
            return False
        provider = (self.email_provider or "").strip().lower()
        if provider == "postmark":
            return bool(self.postmark_server_token)
        if provider == "smtp":
            return bool(self.smtp_host)
        return False

    @property
    def keycloak_enabled(self) -> bool:
        return bool(
            self.keycloak_url
            and self.keycloak_client_id
            and self.keycloak_client_secret
            and self.sso_redirect_base
        )

    @property
    def oidc_issuer(self) -> str:
        return f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def sso_allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.sso_allowed_hosts.split(",") if h.strip()}

    def sso_base_for_host(self, host: str | None) -> str:
        """Redirect base to use for a login arriving at `host`. An allowlisted host
        keeps the veteran on their own domain; anything else falls back to the single
        configured base (so the default deploy and any unknown host are unaffected)."""
        h = (host or "").split(":")[0].strip().lower()  # strip any :port
        if h and h in self.sso_allowed_host_set:
            return f"https://{h}"
        return self.sso_redirect_base.rstrip("/")

    def sso_callback_url_for(self, base: str) -> str:
        return f"{base.rstrip('/')}/api/auth/keycloak/callback"

    def sso_frontend_landing_for(self, base: str) -> str:
        return f"{base.rstrip('/')}/auth/sso-callback"

    @property
    def sso_callback_url(self) -> str:
        return f"{self.sso_redirect_base.rstrip('/')}/api/auth/keycloak/callback"

    @property
    def sso_frontend_landing(self) -> str:
        return f"{self.sso_redirect_base.rstrip('/')}/auth/sso-callback"

    @property
    def sso_allowed_list(self) -> list[str]:
        return [e.strip().lower() for e in self.sso_allowed_emails.split(",") if e.strip()]

    def sso_email_allowed(self, email: str) -> bool:
        """Bootstrap allowlist: exact email, or a '@domain' entry the email ends with."""
        email = (email or "").strip().lower()
        if not email:
            return False
        for entry in self.sso_allowed_list:
            if entry.startswith("@") and email.endswith(entry):
                return True
            if entry == email:
                return True
        return False

    @property
    def platform_admin_list(self) -> list[str]:
        return [e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()]

    def platform_admin_email_allowed(self, email: str) -> bool:
        return (email or "").strip().lower() in self.platform_admin_list

    @property
    def glitter_enabled(self) -> bool:
        return bool(self.glitter_base_url and self.glitter_bridge_secret)

    # ── VA Lighthouse helpers ──────────────────────────────────────────────────────────
    @property
    def va_public_base(self) -> str:
        return (self.va_redirect_base or self.sso_redirect_base).rstrip("/")

    @property
    def va_enabled(self) -> bool:
        return bool(
            self.va_client_id
            and self.va_base_url
            and self.va_public_base
            and len(self.va_token_encryption_key) >= 32
        )

    @property
    def va_redirect_uri(self) -> str:
        """Must exactly match a redirect URI registered on the Lighthouse client."""
        return f"{self.va_public_base}/api/va/callback"

    @property
    def va_settings_landing(self) -> str:
        """SPA settings page the callback bounces the browser back to."""
        return f"{self.va_public_base}/settings"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
