"""Decision-letter disposition overlay for reclaim/secondaries on unknown va_status."""

from app.firm.context import apply_decision_overlay, plan_decision_status_updates


class _Doc:
    def __init__(self, extracted: dict):
        self.extracted = extracted


def test_overlay_grants_and_denials_without_clobbering_explicit():
    docs = [_Doc({
        "is_va_decision": True,
        "doc_type": "rating_decision",
        "decode": {"decisions": [
            {"name": "unspecified anxiety disorder", "decision": "denied"},
            {"name": "chronic fatigue syndrome", "decision": "granted", "percent": 60},
            {"name": "fibromyalgia", "decision": "denied"},
            {"name": "left knee bursitis", "decision": "denied"},
        ]},
    })]
    conds = [
        {"name": "Chronic Fatigue Syndrome (ME/CFS)", "va_status": "unknown", "current_rating": None},
        {"name": "Unspecified anxiety disorder", "va_status": "unknown"},
        {"name": "Fibromyalgia", "va_status": "unknown"},
        {"name": "Left Knee Disorder", "va_status": "unknown"},
        {"name": "GERD", "va_status": "unknown"},
        {"name": "PTSD", "va_status": "service_connected", "current_rating": 30},
    ]
    apply_decision_overlay(conds, docs)
    assert conds[0]["va_status"] == "service_connected" and conds[0]["current_rating"] == 60
    assert conds[1]["va_status"] == "denied"
    assert conds[2]["va_status"] == "denied"
    assert conds[3]["va_status"] == "denied"
    assert conds[4]["va_status"] == "unknown"
    assert conds[5]["va_status"] == "service_connected" and conds[5]["current_rating"] == 30


def test_overlay_reads_rating_summary_and_conditions_mentioned():
    """Aaron dogfood shape: no decode key; denials live on conditions_mentioned,
    CFS grant on rating_summary with rating_percent."""
    docs = [
        _Doc({
            "is_va_decision": True,
            "doc_type": "decision_letter",
            "rating_summary": [],
            "conditions_mentioned": [
                {"name": "right knee tendonitis, resolved", "decision": "denied"},
                {
                    "name": "unspecified anxiety disorder, claimed as posttraumatic stress disorder and depression",
                    "decision": "denied",
                },
                {"name": "history of fibromyalgia", "decision": "denied"},
                {"name": "left knee bursitis", "decision": "denied"},
                {"name": "chronic fatigue syndrome", "decision": "denied"},  # older denial
            ],
        }),
        _Doc({
            "is_va_decision": True,
            "doc_type": "rating_decision",
            "rating_summary": [
                {"name": "chronic fatigue syndrome", "decision": "granted", "rating_percent": 60},
            ],
            "conditions_mentioned": [
                {"name": "chronic fatigue syndrome", "decision": "granted", "rating_percent": 60},
            ],
        }),
    ]
    conds = [
        {"name": "Chronic Fatigue Syndrome (ME/CFS)", "va_status": "unknown", "current_rating": None},
        {"name": "Unspecified anxiety disorder", "va_status": "unknown"},
        {"name": "Fibromyalgia", "va_status": "unknown"},
        {"name": "Left Knee Disorder", "va_status": "unknown"},
        {"name": "Right Knee Disorder", "va_status": "unknown"},
    ]
    apply_decision_overlay(conds, docs)
    # Later grant wins over earlier CFS denial
    assert conds[0]["va_status"] == "service_connected"
    assert conds[0]["current_rating"] == 60
    assert conds[1]["va_status"] == "denied"
    assert conds[2]["va_status"] == "denied"
    assert conds[3]["va_status"] == "denied"
    assert conds[4]["va_status"] == "denied"


def test_overlay_does_not_map_depression_from_anxiety_claimed_as_tail():
    """'claimed as … depression' on an anxiety denial must not mark Depression denied."""
    docs = [_Doc({
        "is_va_decision": True,
        "doc_type": "decision_letter",
        "conditions_mentioned": [
            {
                "name": "unspecified anxiety disorder, claimed as posttraumatic stress disorder and depression",
                "decision": "denied",
            },
        ],
    })]
    conds = [
        {"name": "Unspecified anxiety disorder", "va_status": "unknown"},
        {"name": "Depression", "va_status": "unknown"},
        {"name": "Major Depressive Disorder", "va_status": "unknown"},
        {"name": "PTSD", "va_status": "unknown"},
    ]
    apply_decision_overlay(conds, docs)
    assert conds[0]["va_status"] == "denied"
    assert conds[1]["va_status"] == "unknown"
    assert conds[2]["va_status"] == "unknown"
    # PTSD may match posttraumatic via signal tokens — acceptable if matched
    assert conds[3]["va_status"] in ("denied", "unknown")


def test_plan_decision_status_updates_is_pure_and_id_keyed():
    docs = [_Doc({
        "is_va_decision": True,
        "doc_type": "rating_decision",
        "rating_summary": [
            {"name": "chronic fatigue syndrome", "decision": "granted", "rating_percent": 60},
        ],
        "conditions_mentioned": [
            {"name": "unspecified anxiety disorder", "decision": "denied"},
        ],
    })]
    conds = [
        {"id": "a1", "name": "Chronic Fatigue Syndrome (ME/CFS)", "va_status": "unknown", "current_rating": None},
        {"id": "a2", "name": "Unspecified anxiety disorder", "va_status": "unknown"},
        {"id": "a3", "name": "PTSD", "va_status": "service_connected", "current_rating": 30},
    ]
    before = [dict(c) for c in conds]
    updates = plan_decision_status_updates(conds, docs)
    # pure: inputs unchanged
    assert conds == before
    by_id = {u["condition_id"]: u for u in updates}
    assert by_id["a1"]["to_status"] == "service_connected"
    assert by_id["a1"]["set_current_rating"] == 60
    assert by_id["a2"]["to_status"] == "denied"
    assert "a3" not in by_id


def test_overlay_ignores_cp_exam_false_grants():
    """C&P exam extract with decision=granted must not override a decision-letter denial."""

    class _NamedDoc:
        def __init__(self, filename, extracted):
            self.filename = filename
            self.doc_type = extracted.get("doc_type")
            self.extracted = extracted

    docs = [
        _NamedDoc(
            "C and P EXAM-STRANSKY.5254.pdf",
            {
                "doc_type": "other",
                "conditions_mentioned": [
                    {"name": "Unspecified Anxiety Disorder", "decision": "granted"},
                ],
            },
        ),
        _NamedDoc(
            "ClaimLetter-2016-5-11.pdf",
            {
                "is_va_decision": True,
                "doc_type": "decision_letter",
                "conditions_mentioned": [
                    {
                        "name": "unspecified anxiety disorder, claimed as posttraumatic stress disorder and depression",
                        "decision": "denied",
                    },
                ],
            },
        ),
        _NamedDoc(
            "decision_letter.pdf",
            {
                "is_va_decision": True,
                "doc_type": "rating_decision",
                "rating_summary": [
                    {"name": "chronic fatigue syndrome", "decision": "granted", "rating_percent": 60},
                ],
            },
        ),
    ]
    conds = [
        {"name": "Unspecified anxiety disorder", "va_status": "unknown"},
        {"name": "Chronic Fatigue Syndrome (ME/CFS)", "va_status": "unknown", "current_rating": None},
        {"name": "Generalized Anxiety Disorder", "va_status": "unknown"},
    ]
    apply_decision_overlay(conds, docs)
    assert conds[0]["va_status"] == "denied"
    assert conds[1]["va_status"] == "service_connected" and conds[1]["current_rating"] == 60
    # GAD should not pick up C&P false grant
    assert conds[2]["va_status"] in ("denied", "unknown")
