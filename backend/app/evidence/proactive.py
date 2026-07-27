"""Detect existing evidence + obvious evidence opportunities from the dossier.

Pure and deterministic (no LLM, no DB) given an assembled VeteranDossier. Two reads:

  * existing_evidence()  — nexus/buddy/DBQ documents already in the file, matched to
    the condition they support (so we surface "you already have this — here it is").
  * evidence_opportunities() — per condition, where a nexus or buddy statement is
    both NEEDED (a gap) and OBTAINABLE (the prerequisites are in the record), with a
    ready draft action and an honest flag when the veteran must do something we can't
    automate.
"""

from __future__ import annotations

from typing import Any

# doc_type → the evidence kind it stands as (nexus letters may be classified either way).
_NEXUS_DOCS = {"nexus_letter", "private_medical_opinion"}
_BUDDY_DOCS = {"lay_statement"}
_DBQ_DOCS = {"dbq"}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _condition_names(dossier) -> dict[str, dict]:
    """name(lower) → condition dict, for matching a document's mentions to a condition."""
    return {_norm(c.get("name")): c for c in (dossier.conditions or []) if c.get("name")}


def _doc_mentions(doc) -> list[str]:
    ex = getattr(doc, "extracted", None) or {}
    names: list[str] = []
    for m in ex.get("conditions_mentioned") or []:
        if isinstance(m, dict) and m.get("name"):
            names.append(_norm(m["name"]))
    for link in ex.get("suggested_links") or []:
        if isinstance(link, dict) and link.get("condition"):
            names.append(_norm(link["condition"]))
    return names


def existing_evidence(dossier) -> list[dict]:
    """Evidence documents already in the file, matched to the condition they support.
    Each: {condition, evidence_type, document_id, document_title, doc_type}. Lets the
    UI/agent say 'you already have a nexus letter for your knee — here it is' and link
    it in the right spot."""
    by_name = _condition_names(dossier)
    out: list[dict] = []
    for doc in dossier.documents or []:
        dt = _norm(getattr(doc, "doc_type", None))
        if dt in _NEXUS_DOCS:
            etype = "nexus"
        elif dt in _BUDDY_DOCS:
            etype = "buddy_statement"
        elif dt in _DBQ_DOCS:
            etype = "dbq"
        else:
            continue
        matched = [by_name[n] for n in _doc_mentions(doc) if n in by_name]
        # A nexus/buddy/DBQ that names no known condition is still worth surfacing once.
        targets = matched or [None]
        for cond in targets:
            out.append(
                {
                    "condition": (cond or {}).get("name"),
                    "diagnostic_code": (cond or {}).get("diagnostic_code"),
                    "evidence_type": etype,
                    "document_id": str(getattr(doc, "id", "") or ""),
                    "document_title": getattr(doc, "title", None) or getattr(doc, "filename", None),
                    "doc_type": dt,
                }
            )
    return out


def _has(missing: list, *needles: str) -> bool:
    blob = " ".join(_norm(m) for m in (missing or []))
    return any(n in blob for n in needles)


def evidence_opportunities(dossier) -> list[dict]:
    """Per condition, the obvious next evidence step where we can help. Each:
      {condition, opportunity: 'nexus'|'buddy_statement', reason, draft_route,
       auto_draftable: bool, needs_veteran: str|None}

    Rules (deterministic, conservative — only 'obvious' cases):
    - NEXUS: the condition still needs a nexus AND has both an in-service event on file
      and a diagnosis signal (a diagnostic code, or a rated/known status). A nexus is
      the #1 reason claims are denied, so surfacing a provider-ready template here is
      the single highest-leverage automation. auto_draftable=True (we build the
      provider template); needs_veteran = the provider must review + sign it.
    - BUDDY STATEMENT: the condition needs continuity-of-symptoms evidence AND has an
      in-service event a witness could attest. Lay fact — we can draft the whole thing
      for the witness to sign.
    """
    opps: list[dict] = []
    for c in dossier.conditions or []:
        name = c.get("name")
        if not name:
            continue
        missing = c.get("missing") or []
        has_event = bool(_norm(c.get("in_service_event")))
        has_diagnosis = bool(c.get("diagnostic_code")) or _norm(c.get("va_status")) in {
            "service_connected", "pending",
        } or _norm(c.get("band")) in {"strong", "complete", "developing"}

        if _has(missing, "nexus") and has_event and has_diagnosis:
            opps.append(
                {
                    "condition": name,
                    "opportunity": "nexus",
                    "reason": (
                        "Your file has the diagnosis and the in-service event for this "
                        "condition, but no medical nexus linking them — the piece VA "
                        "most often denies claims for."
                    ),
                    "draft_route": "/nexus",
                    "auto_draftable": True,
                    "needs_veteran": "Your treating provider reviews, completes the opinion, and signs it.",
                }
            )
        if _has(missing, "continuity", "lay", "buddy") and has_event:
            opps.append(
                {
                    "condition": name,
                    "opportunity": "buddy_statement",
                    "reason": (
                        "There's an in-service event on file but a gap in continuity of "
                        "symptoms — a buddy statement from someone who witnessed it can fill it."
                    ),
                    "draft_route": "/buddy",
                    "auto_draftable": True,
                    "needs_veteran": "The witness reviews and signs the drafted statement.",
                }
            )
    return opps


def draft_for_opportunity(dossier, opp: dict) -> dict | None:
    """PRE-GENERATE the actual, printable draft for an opportunity from the veteran's
    OWN record — so it's ready to sign, not just a 'prepare' link. Reuses the existing
    pure, legal-lane renderers (nexus = provider-signable template; buddy = lay-fact
    statement). Returns {title, markdown} or None. No LLM, no fabrication."""
    cond = next(
        (c for c in (dossier.conditions or []) if _norm(c.get("name")) == _norm(opp.get("condition"))),
        None,
    )
    if cond is None:
        return None
    name = cond.get("name")
    veteran = None
    prof = getattr(dossier, "profile", None) or {}
    ident = prof.get("identity") if isinstance(prof, dict) else None
    if isinstance(ident, dict):
        veteran = ident.get("full_name")

    if opp.get("opportunity") == "nexus":
        from ..routers.nexus import _render_letter
        from ..schemas import NexusDraftIn

        is_secondary = _norm(cond.get("claim_type")) == "secondary" or bool(cond.get("secondary_to"))
        payload = NexusDraftIn(
            veteran_name=veteran,
            condition=name,
            diagnostic_code=cond.get("diagnostic_code"),
            claim_type="secondary" if is_secondary else "direct",
            in_service_event=cond.get("in_service_event"),
            secondary_to=cond.get("secondary_to_name") or None,
        )
        return {"title": f"Nexus opinion template — {name}", "markdown": _render_letter(payload)}

    if opp.get("opportunity") == "buddy_statement":
        from ..routers.buddy import _render_statement
        from ..schemas import BuddyDraftIn

        payload = BuddyDraftIn(
            witness_name="[Witness name]",
            witness_relationship="[Their relationship to you, e.g. squad member, spouse]",
            veteran_name=veteran,
            condition=name,
            observations=(
                cond.get("in_service_event")
                or f"[What the witness saw firsthand about your {name} — the event, the symptoms, when and how often]"
            ),
        )
        return {"title": f"Buddy statement draft — {name}", "markdown": _render_statement(payload)}
    return None


def evidence_review(dossier) -> dict:
    """The full proactive picture for the agent + UI: what we already have (to link)
    and what's obviously worth adding — with the actual draft PRE-GENERATED for each
    opportunity (ready to print/sign, not just a link)."""
    have = existing_evidence(dossier)
    opps = evidence_opportunities(dossier)
    for opp in opps:
        draft = draft_for_opportunity(dossier, opp)
        if draft:
            opp["draft"] = draft
    return {
        "already_in_your_file": have,
        "worth_adding": opps,
        "summary": (
            f"Found {len(have)} piece(s) of evidence already in your records and "
            f"{len(opps)} clear opportunit{'y' if len(opps) == 1 else 'ies'} to strengthen a claim."
        ),
        "disclaimer": (
            "We organize your evidence and prepare drafts to the point of signature — a "
            "nexus opinion is your provider's to write and sign; a buddy statement is the "
            "witness's. We never file for you."
        ),
    }
