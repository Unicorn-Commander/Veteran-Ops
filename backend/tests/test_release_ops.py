"""Release identity, operational metrics, and credential-free canary gates."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading

import pytest

from app import __version__, main, release as release_mod
from app.analysis import jobs
from app.kb import freshness
from app.release import release_inventory, release_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_release_manifest_versions_fingerprints_and_changelog_match():
    inventory = release_inventory()
    frontend_package = json.loads(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    frontend_lock = json.loads(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    assert inventory["valid"] is True
    assert {
        inventory["version"],
        frontend_package["version"],
        frontend_lock["version"],
        frontend_lock["packages"][""]["version"],
    } == {__version__}
    assert inventory["release_id"].startswith(f"{__version__}-")
    assert inventory["checks"] == {
        "app_version_matches": True,
        "rule_fingerprint_matches": True,
        "benefits_fingerprint_matches": True,
        "rule_changelog_matches": True,
    }
    assert inventory["rule_changelog"]
    assert all(change["sources"] for change in inventory["rule_changelog"])


def test_release_snapshot_is_privacy_safe_and_meta_reports_identity(monkeypatch):
    async def _fresh():
        return {
            "status": "current",
            "stale": False,
            "kb_verified_as_of": "2026-07-05",
            "title38_latest_amended_on": "2026-07-05",
        }

    monkeypatch.setattr(freshness, "effective_freshness", _fresh)
    meta = asyncio.run(main.meta())
    release = asyncio.run(main.release())
    assert meta.version == release.version == __version__
    assert meta.release_id == release.release_id
    assert meta.rule_version == release.rules["version"]
    assert release.manifest_valid is True
    encoded = release.model_dump_json().lower()
    assert not {"email", "user_id", "document", "prompt", "token"} & set(
        release.model_dump()
    )
    assert "synthetic@example.test" not in encoded


@pytest.mark.parametrize(
    ("release_sha", "built_at"),
    [
        ("token=synthetic-secret", "token=synthetic-secret"),
        ("https://example.test/revision", "https://example.test/build"),
        ("abcdef0\ninjected", "2026-07-20T12:00:00Z\ninjected"),
        ("ABCDEF0", "2026-02-30T12:00:00Z"),
    ],
)
def test_release_snapshot_rejects_unsafe_build_metadata(
    monkeypatch, release_sha, built_at
):
    monkeypatch.setenv("RELEASE_SHA", release_sha)
    monkeypatch.setenv("RELEASE_BUILT_AT", built_at)
    snapshot = release_snapshot(kb_verified_as_of="2026-07-05", kb_status="current")
    assert snapshot["source_revision"] == "development"
    assert snapshot["built_at"] == "unknown"
    encoded = json.dumps(snapshot)
    assert release_sha not in encoded
    assert built_at not in encoded


def test_release_snapshot_accepts_strict_build_metadata(monkeypatch):
    monkeypatch.setenv("RELEASE_SHA", "abcdef0123456789")
    monkeypatch.setenv("RELEASE_BUILT_AT", "2026-07-20T12:34:56Z")
    snapshot = release_snapshot(kb_verified_as_of="2026-07-05", kb_status="current")
    assert snapshot["source_revision"] == "abcdef0123456789"
    assert snapshot["built_at"] == "2026-07-20T12:34:56Z"


def _queue_snapshot() -> dict:
    return {
        "workers_alive": 1,
        "workers_stale": 0,
        "queued": 2,
        "running": 1,
        "retryable": 1,
        "expired_leases": 0,
        "unsynced_runs": 0,
        "failed": 0,
        "failed_recent": 0,
        "retried_jobs": 1,
        "oldest_active_seconds": 12.5,
        "status_counts": {
            "queued": 1,
            "retryable": 1,
            "leased": 0,
            "running": 1,
            "completed": 2,
            "failed": 0,
            "cancelled": 0,
        },
    }


class _Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return None


class _Engine:
    def connect(self):
        return _Connection()


def test_invalid_release_manifest_blocks_readiness(monkeypatch):
    async def _queue():
        return _queue_snapshot()

    async def _fresh():
        return {"status": "current", "stale": False, "kb_verified_as_of": "2026-07-05"}

    monkeypatch.setattr(main, "engine", _Engine())
    monkeypatch.setattr(jobs, "queue_health", _queue)
    monkeypatch.setattr(freshness, "effective_freshness", _fresh)
    monkeypatch.setattr(
        release_mod,
        "release_snapshot",
        lambda **_kwargs: {"manifest_valid": False},
    )
    response = asyncio.run(main.readyz())
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["dependencies"]["release_manifest"] == "invalid"


def test_fingerprint_mismatch_blocks_readiness(monkeypatch, tmp_path):
    manifest = json.loads(release_mod.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["rule_content_sha256"] = "0" * 64
    invalid_manifest = tmp_path / "release-manifest.json"
    invalid_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    async def _queue():
        return _queue_snapshot()

    async def _fresh():
        return {"status": "current", "stale": False, "kb_verified_as_of": "2026-07-05"}

    monkeypatch.setattr(main, "engine", _Engine())
    monkeypatch.setattr(jobs, "queue_health", _queue)
    monkeypatch.setattr(freshness, "effective_freshness", _fresh)
    monkeypatch.setattr(release_mod, "MANIFEST_PATH", invalid_manifest)
    release_inventory.cache_clear()
    try:
        response = asyncio.run(main.readyz())
    finally:
        release_inventory.cache_clear()

    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["dependencies"]["release_manifest"] == "invalid"


def test_metrics_export_queue_kb_dependency_and_release_gauges(monkeypatch):
    if not main._METRICS_ON:
        pytest.skip("prometheus-client is optional in the local test environment")

    async def _queue():
        return _queue_snapshot()

    async def _fresh():
        return {"status": "current", "stale": False, "kb_verified_as_of": "2026-07-05"}

    monkeypatch.setattr(main, "engine", _Engine())
    monkeypatch.setattr(jobs, "queue_health", _queue)
    monkeypatch.setattr(freshness, "effective_freshness", _fresh)
    response = asyncio.run(main.metrics())
    body = response.body.decode()
    assert 'valor_dependency_up{dependency="database"} 1.0' in body
    assert 'valor_dependency_up{dependency="release_manifest"} 1.0' in body
    assert 'valor_kb_status{status="current"} 1.0' in body
    assert 'valor_analysis_jobs{status="retryable"} 1.0' in body
    assert "valor_analysis_queue_oldest_seconds 12.5" in body
    assert "valor_release_info{" in body


def _load_canary_module():
    path = ROOT / "scripts" / "valor-canary.py"
    spec = importlib.util.spec_from_file_location("valor_canary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_canary_passes_synthetic_release_fixture():
    snapshot = release_snapshot(kb_verified_as_of="2026-07-05", kb_status="current")
    payloads = {
        "/api/healthz": {"ok": True, "status": "alive", "version": __version__},
        "/api/readyz": {"ok": True, "status": "ready"},
        "/api/meta": {
            "version": __version__,
            "release_id": snapshot["release_id"],
            "kb_status": "current",
        },
        "/api/release": snapshot,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract.
            body = json.dumps(payloads.get(self.path, {"detail": "not found"})).encode()
            self.send_response(200 if self.path in payloads else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        canary = _load_canary_module()
        report = canary.run_canary(f"http://127.0.0.1:{server.server_port}")
        metrics = canary.prometheus_text(report)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert report["ok"] is True
    assert all(report["invariants"].values())
    assert 'valor_synthetic_journey_success{journey="public_readiness"} 1' in metrics


def test_backup_script_contains_no_embedded_remote_credentials():
    script = (ROOT / "scripts" / "valor-backup.sh").read_text(encoding="utf-8")
    assert "export AWS_ACCESS_KEY_ID=" not in script
    assert "export AWS_SECRET_ACCESS_KEY=" not in script
    assert "VALOR_BACKUP_REMOTE_URI" in script
