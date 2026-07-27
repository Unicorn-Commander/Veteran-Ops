"""Fill the OFFICIAL VA Form 21-686c (Application Request to Add and/or Remove
Dependents) — PURE mapping + thin pypdf fill.

Legal lane (stricter here): dependency decisions move real money and turn on
sensitive, structured facts (each dependent's identity, SSN, dates, marriage/divorce
history). We fill ONLY the veteran's own name and email — the fields any veteran can
verify at a glance — and leave EVERY dependent detail, the add/remove selection, SSN,
VA file number, date of birth, address, and signature for the veteran. Output is a
DRAFT the veteran reviews, completes, and signs (or hands to a free VSO); Rating
Raider does not file it.

Template: VA Form 21-686c, AUG 2025 (OMB 2900-0043), 15 pages / 647 AcroForm fields,
introspected 2026-07-09. pypdf ignores unknown field names → stale map under-fills,
never mis-fills.
"""

from __future__ import annotations

from pathlib import Path

from ..base import fill_acroform, split_name

TEMPLATE = Path(__file__).parent.parent / "templates" / "21-686c.pdf"
FORM_ID = "21-686c"
FORM_EDITION = "AUG 2025"
FORM_OMB = "2900-0043"
FORM_TITLE = "Application Request to Add and/or Remove Dependents"
DRAFT_FILENAME = "VA-21-686c-Dependents-DRAFT-review-and-sign.pdf"

# Section I (veteran identification) lives on Page_7 of this edition.
_VET = "F[0].Page_7[0].#subform[0]."

AUTO_FILLED = [
    "Your (the veteran's) name and email",
]
YOU_COMPLETE = [
    "Social Security number and VA file number",
    "Date of birth",
    "Mailing address and phone",
    "Whether you're adding or removing each dependent",
    "Each dependent's details (spouse, child, or parent) — names, SSNs, and dates",
    "Marriage, divorce, and prior-marriage information",
    "Your signature and date",
]

_TITLE = (
    "DRAFT VA Form 21-686c — review, complete, and sign before filing "
    "(prepared with Rating Raider; we do not file for you)"
)


def build_field_values(
    *,
    full_name: str,
    email: str,
    service_periods: list | None,
    contentions: list[dict],
    identity: dict | None = None,
    dependents: list | None = None,
    is_own_draft: bool = True,
    **_: object,
) -> dict:
    """PURE: map app data → {acroform_field_name: value}. Only the veteran's own
    identity is filled; every dependent field stays blank for the veteran."""
    values: dict[str, str] = {}

    first, middle, last = split_name(full_name)
    if first:
        values[_VET + "VeteranFirstName[0]"] = first
    if last:
        values[_VET + "VeteranLastName[0]"] = last
    if middle:
        values[_VET + "VeteranMiddleInitial1[0]"] = middle
    if email:
        values[_VET + "Email_Address[0]"] = email

    from ..identity_fill import identity_values, spouse_values

    values.update(identity_values(identity, {
        "dob_m": _VET + "DOBmonth[0]", "dob_d": _VET + "DOBday[0]", "dob_y": _VET + "DOByear[0]",
        "street": _VET + "CompleteMailingAddress_NumberAndStreet[0]",
        "city": _VET + "City[0]", "state": _VET + "StateOrProvince[0]",
        "zip5": _VET + "ZIPOrPostalCode_FirstFiveNumbers[0]",
        "zip4": _VET + "ZIPOrPostalCode_LastFourNumbers[0]",
    }, is_own_draft=is_own_draft))
    # First spouse in the household → the 21-686c spouse block (no SSN — hand-written).
    values.update(spouse_values(dependents, {
        "sp_first": _VET + "SPOUSE_CURRENT_LEGAL_NAME_FirstName[0]",
        "sp_middle": _VET + "SPOUSE_MiddleInitial1[0]",
        "sp_last": _VET + "SPOUSE_LastName[0]",
        "sp_dob_m": _VET + "DOBmonth[1]", "sp_dob_d": _VET + "DOBday[1]", "sp_dob_y": _VET + "DOByear[1]",
        "marriage_m": _VET + "DOMARRIAGEmonth[0]",
        "marriage_d": _VET + "DOMARRIAGEday[0]",
        "marriage_y": _VET + "DOMARRIAGEyear[0]",
        "marriage_place": _VET + "PlaceOfMarriage_City_Or_County[0]",
    }))
    return values


def fill_pdf(values: dict) -> bytes:
    return fill_acroform(TEMPLATE, values, title=_TITLE)
