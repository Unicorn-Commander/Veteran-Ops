"""WAVE12 — tier-based feature entitlements (app/features.py). Pure unit tests: no DB,
no app. Asserts the tier ordering, the per-feature minimum tier, the feature-set
projection, and seat limits. The mission invariant: individual (ungated) features are
never restricted; only org/enterprise capabilities gate on tier.
"""

from __future__ import annotations

from app.features import (
    FEATURE_MIN_TIER,
    SEAT_LIMIT,
    features_for,
    has_feature,
    tier_rank,
)


def test_tier_rank_orders_free_pro_team_enterprise():
    assert tier_rank("free") < tier_rank("pro") < tier_rank("team") < tier_rank("enterprise")


def test_tier_rank_unknown_or_none_is_free():
    assert tier_rank(None) == 0
    assert tier_rank("free") == 0
    assert tier_rank("wat") == 0
    # Case-insensitive.
    assert tier_rank("ENTERPRISE") == tier_rank("enterprise")


def test_ungated_feature_always_true():
    for tier in ("free", "pro", "team", "enterprise", None, "bogus"):
        assert has_feature(tier, "some_individual_tool") is True


def test_team_features_require_team():
    for feature in ("org_invites", "org_workspaces", "staff_caseload", "org_admin_console"):
        assert has_feature("free", feature) is False
        assert has_feature("pro", feature) is False
        assert has_feature("team", feature) is True
        assert has_feature("enterprise", feature) is True


def test_enterprise_features_require_enterprise():
    for feature in ("white_label", "sso_byoidp"):
        assert has_feature("free", feature) is False
        assert has_feature("pro", feature) is False
        assert has_feature("team", feature) is False
        assert has_feature("enterprise", feature) is True


def test_priority_support_requires_pro():
    assert has_feature("free", "priority_support") is False
    assert has_feature("pro", "priority_support") is True
    assert has_feature("team", "priority_support") is True
    assert has_feature("enterprise", "priority_support") is True


def test_features_for_free_excludes_team_features():
    feats = set(features_for("free"))
    assert "org_invites" not in feats
    assert "org_workspaces" not in feats
    assert "white_label" not in feats


def test_features_for_team_includes_team_not_enterprise():
    feats = set(features_for("team"))
    assert {"org_invites", "org_workspaces", "staff_caseload", "org_admin_console"} <= feats
    assert "white_label" not in feats
    assert "sso_byoidp" not in feats


def test_features_for_enterprise_includes_all():
    assert set(features_for("enterprise")) == set(FEATURE_MIN_TIER)


def test_seat_limits():
    assert SEAT_LIMIT["free"] == 1
    assert SEAT_LIMIT["team"] == 25
    assert SEAT_LIMIT["enterprise"] == -1
