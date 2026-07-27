"""Host-aware SSO redirect: a login lands the veteran back on the host they came
from (allowlisted), and an un-allowlisted host falls back to the single base —
so a forged Host can never steer the OIDC redirect off-domain."""
from __future__ import annotations

from app.config import Settings
from app.security import make_sso_state, verify_sso_state


def _s() -> Settings:
    return Settings(
        jwt_secret="test-secret-please-ignore",
        sso_redirect_base="https://valor.magicunicorn.dev",
        sso_allowed_hosts="valor.magicunicorn.dev,valor-ops.magicunicorn.dev,valor-ops.unicorncommander.ai,valorops.unicorncommander.ai",
    )


def test_allowlisted_host_keeps_domain():
    s = _s()
    for host in ("valor-ops.unicorncommander.ai", "valorops.unicorncommander.ai", "valor-ops.magicunicorn.dev"):
        assert s.sso_base_for_host(host) == f"https://{host}"
        assert s.sso_callback_url_for(s.sso_base_for_host(host)) == f"https://{host}/api/auth/keycloak/callback"


def test_unlisted_or_forged_host_falls_back():
    s = _s()
    assert s.sso_base_for_host("evil.example.com") == "https://valor.magicunicorn.dev"
    assert s.sso_base_for_host(None) == "https://valor.magicunicorn.dev"
    assert s.sso_base_for_host("valor-ops.unicorncommander.ai:8443") == "https://valor-ops.unicorncommander.ai"


def test_state_round_trips_the_base(monkeypatch):
    import app.security as sec
    monkeypatch.setattr(sec.settings, "jwt_secret", "test-secret-please-ignore")
    base = "https://valor-ops.unicorncommander.ai"
    assert verify_sso_state(make_sso_state(base)) == base
    assert verify_sso_state(make_sso_state()) is None  # single-host deploys unaffected
