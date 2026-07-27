"""Privacy-safe, fingerprinted release and rule-version inventory."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from . import __version__

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = BACKEND_ROOT / "release-manifest.json"
RULE_CHANGELOG_PATH = Path(__file__).parent / "kb" / "data" / "rule_versions.json"
_RELEASE_SHA_RE = re.compile(r"(?:unknown|development|[0-9a-f]{7,64})\Z")
_UTC_RFC3339_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"release metadata must be an object: {path.name}")
    return payload


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rule_content_sha256(files: list[str]) -> str:
    inventory = hashlib.sha256()
    for relative in sorted(files):
        digest = _file_sha256(BACKEND_ROOT / relative)
        inventory.update(f"{relative}:{digest}\n".encode())
    return inventory.hexdigest()


def _release_sha() -> str:
    value = os.getenv("RELEASE_SHA", "")
    return value if _RELEASE_SHA_RE.fullmatch(value) else "development"


def _release_built_at() -> str:
    value = os.getenv("RELEASE_BUILT_AT", "")
    if not _UTC_RFC3339_RE.fullmatch(value):
        return "unknown"
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return "unknown"
    return value


@lru_cache(maxsize=1)
def release_inventory() -> dict[str, Any]:
    manifest = _read_json(MANIFEST_PATH)
    changelog = _read_json(RULE_CHANGELOG_PATH)
    rule_files = manifest.get("rule_files") or []
    if not all(isinstance(item, str) and item for item in rule_files):
        raise ValueError("release manifest rule_files must be non-empty strings")

    actual_rule_hash = _rule_content_sha256(rule_files)
    benefits_path = BACKEND_ROOT / str(manifest["benefits_file"])
    actual_benefits_hash = _file_sha256(benefits_path)
    manifest_hash = _file_sha256(MANIFEST_PATH)
    rule_version = str(manifest["rule_version"])
    changes = changelog.get("changes") or []
    changelog_versions = {
        str(change.get("version")) for change in changes if isinstance(change, dict)
    }

    checks = {
        "app_version_matches": manifest.get("version") == __version__,
        "rule_fingerprint_matches": actual_rule_hash
        == manifest.get("rule_content_sha256"),
        "benefits_fingerprint_matches": actual_benefits_hash
        == manifest.get("benefits_content_sha256"),
        "rule_changelog_matches": changelog.get("current_version") == rule_version
        and rule_version in changelog_versions,
    }
    return {
        **manifest,
        "manifest_sha256": manifest_hash,
        "actual_rule_content_sha256": actual_rule_hash,
        "actual_benefits_content_sha256": actual_benefits_hash,
        "checks": checks,
        "valid": all(checks.values()),
        "rule_changelog": changes,
    }


def release_snapshot(*, kb_verified_as_of: str | None, kb_status: str) -> dict[str, Any]:
    """Return non-sensitive build, rules, KB, and evaluation release identity."""
    inventory = release_inventory()
    return {
        "schema_version": inventory["schema_version"],
        "product": inventory["product"],
        "version": __version__,
        "release_id": inventory["release_id"],
        "source_revision": _release_sha(),
        "built_at": _release_built_at(),
        "schema_revision": inventory["schema_revision"],
        "manifest_sha256": inventory["manifest_sha256"],
        "manifest_valid": inventory["valid"],
        "kb": {
            "version": f"title38-{kb_verified_as_of or 'unknown'}",
            "verified_as_of": kb_verified_as_of,
            "status": kb_status,
        },
        "rules": {
            "version": inventory["rule_version"],
            "content_sha256": inventory["actual_rule_content_sha256"],
            "fingerprint_verified": inventory["checks"]["rule_fingerprint_matches"],
            "changelog": inventory["rule_changelog"],
        },
        "benefits": {
            "version": inventory["benefits_version"],
            "content_sha256": inventory["actual_benefits_content_sha256"],
            "fingerprint_verified": inventory["checks"][
                "benefits_fingerprint_matches"
            ],
        },
        "evaluations": {
            "golden_fixture_version": inventory["golden_fixture_version"],
            "evaluation_card_schema_version": inventory[
                "evaluation_card_schema_version"
            ],
        },
    }
