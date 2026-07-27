"""Fail-closed routing for outputs that depend on current VA rules."""

from __future__ import annotations


def guards_path(method: str, path: str) -> bool:
    """Whether a request can create or calculate consequential KB-backed output.

    Historical run reads and operational status remain available while degraded so
    veterans never lose access to their records or previously generated work.
    """
    method = method.upper()
    if path == "/api/raider/chat":
        return method == "POST"
    if path.startswith("/api/kb/"):
        return path != "/api/kb/freshness"
    if path.startswith("/api/strategy"):
        return path not in {"/api/strategy/briefing", "/api/strategy/deepdive"}
    if path.startswith(("/api/packet/", "/api/filing", "/api/nexus", "/api/appeals")):
        return True
    if not path.startswith("/api/analysis"):
        return False
    historical = (
        "/api/analysis/comprehensive/latest",
        "/api/analysis/comprehensive/runs",
        "/api/analysis/intake-benchmark",
        "/api/analysis/automation-status",
    )
    return not any(path == prefix or path.startswith(f"{prefix}/") for prefix in historical)
