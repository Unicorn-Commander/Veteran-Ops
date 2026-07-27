"""Bulk review-queue reconcile — veteran-confirmed policies only."""

from app.schemas import BulkReconcileIn


def test_bulk_reconcile_modes_are_constrained():
    assert BulkReconcileIn(mode="accept_agreed").mode == "accept_agreed"
    assert BulkReconcileIn(mode="accept_record").dismiss_all_missing is False
    for mode in ("accept_record", "accept_extracted", "accept_agreed", "clear_all"):
        BulkReconcileIn(mode=mode)


def test_apply_resolution_agreed_semantics():
    """Document pure selection logic used by bulk reconcile."""
    fields = [
        {"field_id": "0:rating_percent", "candidate_value": 50, "extracted_value": 50},
        {"field_id": "0:diagnostic_code", "candidate_value": "6260", "extracted_value": "6100"},
        {"field_id": "1:name", "candidate_value": "Tinnitus", "extracted_value": "Tinnitus"},
    ]

    def select(mode: str, f: dict):
        c, e = f.get("candidate_value"), f.get("extracted_value")
        if mode == "accept_record":
            return c, True
        if mode == "accept_extracted":
            return e, True
        if c is not None and c == e:
            return c, True
        return None, False

    agreed = [fid for f in fields if (fid := f["field_id"]) and select("accept_agreed", f)[1]]
    assert agreed == ["0:rating_percent", "1:name"]
    assert all(select("accept_record", f)[1] for f in fields)
