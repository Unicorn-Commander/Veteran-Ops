#!/usr/bin/env python3
"""Credential-free, read-only Valor-Ops public readiness canary.

The canary never sends veteran data, credentials, or mutation requests. It can write
Prometheus textfile-collector metrics atomically for node_exporter/Center Deep.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ENDPOINTS = {
    "liveness": "/api/healthz",
    "readiness": "/api/readyz",
    "metadata": "/api/meta",
    "release": "/api/release",
}


def _fetch_json(base_url: str, path: str, timeout: float) -> tuple[dict[str, Any], float]:
    url = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "valor-canary/1"})
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied URL.
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        body = response.read(1024 * 1024)
    elapsed = time.monotonic() - started
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")
    return payload, elapsed


def run_canary(
    base_url: str,
    *,
    timeout: float = 10.0,
    allow_not_ready: bool = False,
    allow_stale_kb: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    checks: dict[str, dict[str, Any]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for name, path in ENDPOINTS.items():
        try:
            payload, duration = _fetch_json(base_url, path, timeout)
            payloads[name] = payload
            checks[name] = {"ok": True, "duration_seconds": round(duration, 6)}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            checks[name] = {
                "ok": False,
                "duration_seconds": round(time.monotonic() - started, 6),
                "error_type": type(exc).__name__,
            }

    health = payloads.get("liveness", {})
    ready = payloads.get("readiness", {})
    meta = payloads.get("metadata", {})
    release = payloads.get("release", {})
    invariants = {
        "process_alive": health.get("ok") is True and health.get("status") == "alive",
        "service_ready": allow_not_ready or ready.get("ok") is True,
        "version_consistent": bool(meta.get("version"))
        and meta.get("version") == release.get("version") == health.get("version"),
        "release_consistent": bool(meta.get("release_id"))
        and meta.get("release_id") == release.get("release_id"),
        "manifest_valid": release.get("manifest_valid") is True,
        "rules_fingerprinted": release.get("rules", {}).get("fingerprint_verified") is True,
        "benefits_fingerprinted": release.get("benefits", {}).get("fingerprint_verified") is True,
        "knowledge_acceptable": allow_stale_kb
        or (
            meta.get("kb_status") == "current"
            and release.get("kb", {}).get("status") == "current"
        ),
    }
    endpoints_ok = all(check["ok"] for check in checks.values())
    ok = endpoints_ok and all(invariants.values())
    return {
        "ok": ok,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 6),
        "checks": checks,
        "invariants": invariants,
        "release": {
            "version": release.get("version"),
            "release_id": release.get("release_id"),
            "rule_version": release.get("rules", {}).get("version"),
            "kb_version": release.get("kb", {}).get("version"),
        },
    }


def _label(value: Any) -> str:
    return str(value or "unknown").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def prometheus_text(report: dict[str, Any]) -> str:
    lines = [
        "# HELP valor_synthetic_journey_success Public read-only journey status.",
        "# TYPE valor_synthetic_journey_success gauge",
        f'valor_synthetic_journey_success{{journey="public_readiness"}} {1 if report["ok"] else 0}',
        "# HELP valor_synthetic_journey_duration_seconds Public journey wall time.",
        "# TYPE valor_synthetic_journey_duration_seconds gauge",
        f'valor_synthetic_journey_duration_seconds{{journey="public_readiness"}} {report["duration_seconds"]}',
        "# HELP valor_synthetic_check_success Individual public canary check status.",
        "# TYPE valor_synthetic_check_success gauge",
    ]
    for name, check in sorted(report["checks"].items()):
        lines.append(
            f'valor_synthetic_check_success{{check="{_label(name)}"}} {1 if check["ok"] else 0}'
        )
    lines.extend(
        [
            "# HELP valor_synthetic_last_run_timestamp_seconds Canary completion time.",
            "# TYPE valor_synthetic_last_run_timestamp_seconds gauge",
            f"valor_synthetic_last_run_timestamp_seconds {time.time():.3f}",
        ]
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--allow-not-ready", action="store_true")
    parser.add_argument("--allow-stale-kb", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--prometheus-textfile", type=Path)
    args = parser.parse_args()

    report = run_canary(
        args.base_url,
        timeout=max(0.1, args.timeout),
        allow_not_ready=args.allow_not_ready,
        allow_stale_kb=args.allow_stale_kb,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_output:
        _atomic_write(args.json_output, encoded)
    else:
        print(encoded, end="")
    if args.prometheus_textfile:
        _atomic_write(args.prometheus_textfile, prometheus_text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
