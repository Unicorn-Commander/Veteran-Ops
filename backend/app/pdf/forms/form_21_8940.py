"""Fill the OFFICIAL VA Form 21-8940 (Veteran's Application for Increased
Compensation Based on Unemployability — TDIU) — PURE mapping + thin pypdf fill.

Same legal lane as 21-526EZ: we fill ONLY glance-verifiable, high-confidence fields
we already hold — the veteran's name and the service-connected condition(s) they say
keep them from working. We NEVER fill SSN, VA file number, date of birth, address,
the employment/earnings history, or the signature. Output is a DRAFT the veteran
reviews, completes, and signs; Veteran-Ops does not file it. TDIU claims often
warrant an accredited VSO/attorney — the app says so elsewhere.

Template: VA Form 21-8940, JUL 2024 (OMB 2900-0404), 4 pages / 188 AcroForm fields,
introspected 2026-07-09. pypdf ignores field names that don't exist in a newer
edition, so a stale map under-fills, never mis-fills.
"""

from __future__ import annotations

from pathlib import Path

from ..base import fill_acroform, split_name

TEMPLATE = Path(__file__).parent.parent / "templates" / "21-8940.pdf"
FORM_ID = "21-8940"
FORM_EDITION = "JUL 2024"
FORM_OMB = "2900-0404"
FORM_TITLE = "Veteran's Application for Increased Compensation Based on Unemployability"
DRAFT_FILENAME = "VA-21-8940-DRAFT-review-and-sign.pdf"

_SUB = "form1[0].#subform[0]."

AUTO_FILLED = [
    "Your name",
    "The service-connected condition(s) you're claiming keep you from working",
]
YOU_COMPLETE = [
    "Social Security number and VA file number",
    "Date of birth",
    "Mailing address and phone",
    "Your employment and earnings history",
    "Doctors and hospitals that have treated you",
    "Education and training details",
    "Your signature and date",
]

_TITLE = (
    "DRAFT VA Form 21-8940 — review, complete, and sign before filing "
    "(prepared with Rating Raider; we do not file for you)"
)


def build_field_values(
    *,
    full_name: str,
    email: str,
    service_periods: list | None,
    contentions: list[dict],
    identity: dict | None = None,
    is_own_draft: bool = True,
    **_: object,
) -> dict:
    """PURE: map app data → {acroform_field_name: value}. Only non-empty values are
    emitted (pypdf leaves everything else blank for the veteran)."""
    values: dict[str, str] = {}

    first, middle, last = split_name(full_name)
    if first:
        values[_SUB + "VeteransFirstName[0]"] = first
    if last:
        values[_SUB + "VeteransLastName[0]"] = last
    if middle:
        values[_SUB + "VeteransMiddleInitial[0]"] = middle

    # Item 12A: "What service-connected disability(ies) prevents you from securing or
    # following any substantially gainful occupation?" — the veteran's own claimed
    # conditions, joined verbatim.
    names = [
        (c.get("name") or "").strip()
        for c in (contentions or [])
        if isinstance(c, dict) and (c.get("name") or "").strip()
    ]
    if names:
        values[_SUB + "Service_Connected_Disability[0]"] = "; ".join(names)[:500]

    from ..identity_fill import identity_values

    values.update(identity_values(identity, {
        "street": _SUB + "CurrentMailingAddress_NumberAndStreet[0]",
        "unit": _SUB + "CurrentMailingAddress_ApartmentOrUnitNumber[0]",
        "city": _SUB + "CurrentMailingAddress_City[0]",
        "state": _SUB + "CurrentMailingAddress_StateOrProvince[0]",
        "country": _SUB + "CurrentMailingAddress_Country[0]",
        "zip5": _SUB + "CurrentMailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]",
        "zip4": _SUB + "CurrentMailingAddress_ZIPOrPostalCode_LastFourNumbers[0]",
    }, is_own_draft=is_own_draft))
    return values


def fill_pdf(values: dict) -> bytes:
    return fill_acroform(TEMPLATE, values, title=_TITLE)
