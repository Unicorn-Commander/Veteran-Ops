"""Fill the OFFICIAL VA Form 21-4142 (Authorization to Disclose Information to the
VA) — PURE mapping + thin pypdf fill.

This form authorizes private providers to release the veteran's records to VA. We
fill ONLY the veteran's name (the identity block, which repeats in the page footer).
We deliberately leave the Patient name BLANK — it is usually the veteran but not
always, and we won't assume it — along with SSN, service number, every provider's
name/address/treatment dates, the conditions treated, and the signature. Output is a
DRAFT the veteran completes and signs; Rating Raider does not file it. (Note: VA pairs
this with the 21-4142a; the veteran completes that separately.)

Template: VA Form 21-4142, AUG 2024 (OMB 2900-0858), 5 pages / 145 AcroForm fields,
introspected 2026-07-09. pypdf ignores unknown field names → stale map under-fills,
never mis-fills.
"""

from __future__ import annotations

from pathlib import Path

from ..base import fill_acroform, split_name

TEMPLATE = Path(__file__).parent.parent / "templates" / "21-4142.pdf"
FORM_ID = "21-4142"
FORM_EDITION = "AUG 2024"
FORM_OMB = "2900-0858"
FORM_TITLE = "Authorization to Disclose Information to the Department of Veterans Affairs"
DRAFT_FILENAME = "VA-21-4142-Authorization-DRAFT-review-and-sign.pdf"

# The veteran identity block appears on Page_1 and repeats in the page footer
# (#subform[14]); stamp both so the name carries through.
_ID_BLOCKS = ("F[0].Page_1[0].", "F[0].#subform[14].")

AUTO_FILLED = [
    "Your (the veteran's) name",
]
YOU_COMPLETE = [
    "Social Security number and service number",
    "The patient's name (if the records aren't your own)",
    "Each provider or facility — name, address, and treatment dates",
    "The condition(s) they treated",
    "Your signature and date",
]

_TITLE = (
    "DRAFT VA Form 21-4142 (Authorization to Disclose Information) — review, "
    "complete, and sign before filing (prepared with Rating Raider; we do not file "
    "for you)"
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
    """PURE: map app data → {acroform_field_name: value}. Only the veteran's name is
    filled (both identity blocks); patient name and all provider fields stay blank."""
    values: dict[str, str] = {}

    first, middle, last = split_name(full_name)
    for prefix in _ID_BLOCKS:
        if first:
            values[prefix + "VeteranFirstName[0]"] = first
        if last:
            values[prefix + "VeteranLastName[0]"] = last
        if middle:
            values[prefix + "VeteranMiddleInitial1[0]"] = middle

    from ..identity_fill import identity_values

    _p = _ID_BLOCKS[0]  # the veteran identity block on Page 1
    values.update(identity_values(identity, {
        "dob_m": _p + "DOBmonth[0]", "dob_d": _p + "DOBday[0]", "dob_y": _p + "DOByear[0]",
        "phone_area": _p + "TelephoneNumber_AreaCode[0]",
        "phone_mid": _p + "TelephoneNumber_SecondThreeNumbers[0]",
        "phone_last": _p + "TelephoneNumber_LastFourNumbers[0]",
        "street": _p + "MailingAddress_NumberAndStreet[0]",
        "unit": _p + "MailingAddress_ApartmentOrUnitNumber[0]",
        "city": _p + "MailingAddress_City[0]",
        "state": _p + "MailingAddress_StateOrProvince[0]",
        "country": _p + "MailingAddress_Country[0]",
        "zip5": _p + "MailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]",
        "zip4": _p + "MailingAddress_ZIPOrPostalCode_LastFourNumbers[0]",
    }, is_own_draft=is_own_draft))
    return values


def fill_pdf(values: dict) -> bytes:
    return fill_acroform(TEMPLATE, values, title=_TITLE)
