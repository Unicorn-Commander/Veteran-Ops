"""Fill the OFFICIAL VA Form 20-0995 (Decision Review Request: Supplemental Claim)
— PURE mapping + thin pypdf fill.

NOTE ON NUMBERING: the Supplemental Claim is VA Form **20-0995** (not 21-0995 — no
such form exists). The build spec listed the module as "form_21_0995"; the correct
official number is used everywhere here (form_id, template, edition) so the on-screen
labels match what the veteran sees on the PDF.

Same legal lane as 21-526EZ: we fill ONLY high-confidence, glance-verifiable fields
we hold — the veteran's name/email and the specific issues (their claimed
conditions) they're asking VA to review again with new & relevant evidence. We NEVER
fill SSN, VA file number, date of birth, address, the DATE of the decision being
contested, or the signature. Output is a DRAFT the veteran reviews, completes, and
signs; Rating Raider does not file it.

Template: VA Form 20-0995, MAY 2024 (OMB 2900-0886), 7 pages / 164 AcroForm fields,
introspected 2026-07-09. pypdf ignores unknown field names → stale map under-fills,
never mis-fills.
"""

from __future__ import annotations

from pathlib import Path

from ..base import fill_acroform, split_name

TEMPLATE = Path(__file__).parent.parent / "templates" / "20-0995.pdf"
FORM_ID = "20-0995"
FORM_EDITION = "MAY 2024"
FORM_OMB = "2900-0886"
FORM_TITLE = "Decision Review Request: Supplemental Claim"
DRAFT_FILENAME = "VA-20-0995-Supplemental-Claim-DRAFT-review-and-sign.pdf"

_ID = "form1[0].#subform[16]."
_ISSUES = "form1[0].#subform[17].Table2[0]."
# Row 1 uses SPECIFICISSUE1; rows 2–7 use SPECIFICISSUE2. Seven rows on the form.
_ISSUE_ROWS = 7

AUTO_FILLED = [
    "Your name and email",
    "The issues (your claimed conditions) you're asking VA to review again",
]
YOU_COMPLETE = [
    "Social Security number and VA file number",
    "Date of birth",
    "Mailing address and phone",
    "The DATE of the VA decision you're contesting (for each issue)",
    "The new & relevant evidence supporting each issue",
    "Your signature and date (and any witness)",
]

_TITLE = (
    "DRAFT VA Form 20-0995 (Supplemental Claim) — review, complete, and sign before "
    "filing (prepared with Rating Raider; we do not file for you)"
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
    from ..identity_fill import identity_values

    _IDMAP = {
        "dob_m": _ID + "VeteranDOBMonth[0]", "dob_d": _ID + "VeteranDOBDay[0]",
        "dob_y": _ID + "VeteranDOBYear[0]",
        "phone_area": _ID + "VeteransPhoneAreaCode[0]",
        "phone_mid": _ID + "VeteransPhoneFirstThreeNumbers[0]",
        "phone_last": _ID + "VeteransPhoneLastFourNumbers[0]",
        "street": _ID + "CurrentMailingAddress_NumberAndStreet[0]",
        "unit": _ID + "CurrentMailingAddress_ApartmentOrUnitNumber[0]",
        "city": _ID + "CurrentMailingAddress_City[0]",
        "state": _ID + "CurrentMailingAddress_StateOrProvince[0]",
        "country": _ID + "CurrentMailingAddress_Country[0]",
        "zip5": _ID + "CurrentMailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]",
        "zip4": _ID + "CurrentMailingAddress_ZIPOrPostalCode_LastFourNumbers[0]",
    }
    """PURE: map app data → {acroform_field_name: value}. Only non-empty values are
    emitted (pypdf leaves everything else blank for the veteran)."""
    values: dict[str, str] = {}

    first, middle, last = split_name(full_name)
    if first:
        values[_ID + "VeteransFirstName[0]"] = first
    if last:
        values[_ID + "VeteransLastName[0]"] = last
    if middle:
        values[_ID + "VeteransMiddleInitial1[0]"] = middle
    if email:
        values[_ID + "Email[0]"] = email

    # Contested issues table — one row per claimed condition, up to the 7 rows.
    names = [
        (c.get("name") or "").strip()
        for c in (contentions or [])
        if isinstance(c, dict) and (c.get("name") or "").strip()
    ]
    for i, name in enumerate(names[:_ISSUE_ROWS]):
        cell = "SPECIFICISSUE1[0]" if i == 0 else "SPECIFICISSUE2[0]"
        values[f"{_ISSUES}Row{i + 1}[0].{cell}"] = name[:180]

    values.update(identity_values(identity, _IDMAP, is_own_draft=is_own_draft))
    return values


def fill_pdf(values: dict) -> bytes:
    return fill_acroform(TEMPLATE, values, title=_TITLE)
