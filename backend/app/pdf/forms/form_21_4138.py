"""Fill the OFFICIAL VA Form 21-4138 (Statement in Support of Claim) — PURE mapping
+ thin pypdf fill.

A 21-4138 is the veteran's OWN sworn statement. We fill ONLY the veteran's name and
email at the top — the identifying header — and deliberately leave the REMARKS
statement body BLANK: the app never authors, rewords, or embellishes the veteran's
words, and on this download path we don't hold a composed statement. We NEVER fill
SSN, VA file number, date of birth, phone, address, or the signature. Output is a
DRAFT the veteran completes (writes their statement) and signs; Rating Raider does
not file it.

Template: VA Form 21-4138, JUL 2024 (OMB 2900-0075), 2 pages / 36 AcroForm fields,
introspected 2026-07-09. pypdf ignores unknown field names → stale map under-fills,
never mis-fills.
"""

from __future__ import annotations

from pathlib import Path

from ..base import fill_acroform, split_name

TEMPLATE = Path(__file__).parent.parent / "templates" / "21-4138.pdf"
FORM_ID = "21-4138"
FORM_EDITION = "JUL 2024"
FORM_OMB = "2900-0075"
FORM_TITLE = "Statement in Support of Claim"
DRAFT_FILENAME = "VA-21-4138-Statement-DRAFT-review-and-sign.pdf"

_SUB = "form1[0].#subform[0]."

AUTO_FILLED = [
    "Your name and email",
]
YOU_COMPLETE = [
    "Social Security number and VA file number",
    "Date of birth",
    "Phone and mailing address",
    "Your statement — in your own words (the Remarks section)",
    "Your signature and date",
]

_TITLE = (
    "DRAFT VA Form 21-4138 (Statement in Support of Claim) — write your statement, "
    "review, and sign before filing (prepared with Rating Raider; we do not file for "
    "you)"
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
    """PURE: map app data → {acroform_field_name: value}. Only the identifying header
    is filled; the statement body (REMARKS) is the veteran's to write."""
    values: dict[str, str] = {}

    first, middle, last = split_name(full_name)
    if first:
        values[_SUB + "Veterans_Beneficiary_First_Name[0]"] = first
    if last:
        values[_SUB + "Last_Name[0]"] = last
    if middle:
        values[_SUB + "Middle_Initial1[0]"] = middle
    if email:
        values[_SUB + "EMAIL_ADDRESS[0]"] = email

    from ..identity_fill import identity_values

    values.update(identity_values(identity, {
        "street": _SUB + "CurrentMailingAddress_NumberAndStreet[0]",
        "unit": _SUB + "CurrentMailingAddress_ApartmentOrUnitNumber[0]",
        "city": _SUB + "CurrentMailingAddress_City[0]",
        "state": _SUB + "CurrentMailingAddress_StateOrProvince[0]",
        "country": _SUB + "CurrentMailingAddress_Country[0]",
        "zip5": _SUB + "CurrentMailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]",
        "zip4": _SUB + "CurrentMailingAddress_ZIPOrPostalCode_LastFourNumbers[0]",
        "va_file_number": _SUB + "VA_File_Number_If_Applicable[0]",
    }, is_own_draft=is_own_draft))
    return values


def fill_pdf(values: dict) -> bytes:
    return fill_acroform(TEMPLATE, values, title=_TITLE)
