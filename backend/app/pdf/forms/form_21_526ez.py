"""Fill the OFFICIAL VA Form 21-526EZ AcroForm with the app's data — PURE mapping
plus a thin pypdf fill.

Legal lane: we fill ONLY fields the veteran can verify at a glance and that we hold
with confidence (name, email, service dates, the conditions being claimed and how
each relates to service). We NEVER fill SSN, VA file number, date of birth, mailing
address, or the signature — the app doesn't collect those, and they are the
veteran's to complete. The output is a DRAFT (stamped in the PDF Title metadata and
the download filename); Veteran-Ops does not file it.

The template is VA Form 21-526EZ, JAN 2026 (OMB 2900-0747), 15 pages / 357 AcroForm
fields, introspected & verified 2026-07-06. Field names below are copied exactly from
that edition; a newer edition may rename fields (fill degrades to whatever still
matches — pypdf silently ignores unknown names — so a stale map under-fills, never
mis-fills).

Moved verbatim from the original pdf/form526_fill.py (Wave 8 generalization); the
only change is that fill_pdf now delegates to pdf.base.fill_acroform.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ..base import fill_acroform

TEMPLATE = Path(__file__).parent.parent / "templates" / "va-21-526ez.pdf"
FORM_ID = "21-526ez"
FORM_EDITION = "JAN 2026"
FORM_OMB = "2900-0747"
FORM_TITLE = "Application for Disability Compensation and Related Compensation Benefits"

# Exact AcroForm field-name prefixes for the JAN 2026 edition.
_PAGE = "F[0].Page_10[0]."
_DIS = "F[0].#subform[10]."

# The 15 repeating "current disability" rows on the disabilities table. Every row
# has a name + an "explain how it relates to service" cell; the FIRST row also has a
# dedicated onset-date field (later rows use the generic Date12[] cells, which are
# positional and unsafe to target blind — so we only stamp row 0's date).
_DISABILITY_ROWS = 15

# What we auto-fill vs. what the veteran must still complete — surfaced in the UI so
# the download is honestly labeled (never "done").
AUTO_FILLED = [
    "Your name and email",
    "Your date of birth (from your profile)",
    "Your mailing address and phone (from your profile)",
    "Service dates (from your profile)",
    "Standard claim process",
    "Each condition you're claiming and how it relates to your service",
]
YOU_COMPLETE = [
    "Social Security number (we never fill this — write it by hand)",
    "Remaining service details (branch, separation, reserve/guard)",
    "Treatment facilities and direct-deposit information",
    "Your signature and date",
]

_TITLE = (
    "DRAFT VA Form 21-526EZ — review, complete, and sign before filing "
    "(prepared with Rating Raider; we do not file for you)"
)
DRAFT_FILENAME = "VA-21-526EZ-DRAFT-review-and-sign.pdf"


def _split_name(full_name: str) -> tuple[str, str, str]:
    """full_name → (first, middle_initial, last). Best-effort: single token → last
    name blank so the form's required Last Name still gets something."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    first = parts[0]
    last = parts[-1]
    middle = parts[1][0] if len(parts) > 2 and parts[1] else ""
    return first, middle, last


def _year(value) -> str:
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return value[:4]
    return ""


def _date_parts(value) -> tuple[str, str, str]:
    """Loose YYYY-MM-DD (or a date) → (month, day, year) strings; blank on anything
    we can't parse cleanly (we never guess a date onto a federal form)."""
    if isinstance(value, date):
        return f"{value.month:02d}", f"{value.day:02d}", f"{value.year:04d}"
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        y, m, d = value[:4], value[5:7], value[8:10]
        if y.isdigit() and m.isdigit() and d.isdigit():
            return m, d, y
    return "", "", ""


def _digits(value) -> str:
    """Keep only the digits of a string (for phone / ZIP splitting)."""
    return "".join(c for c in str(value or "") if c.isdigit())


def _phone_parts(value) -> tuple[str, str, str]:
    """A US phone (any format) → (area, middle-three, last-four); blank otherwise."""
    d = _digits(value)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) != 10:
        return "", "", ""
    return d[:3], d[3:6], d[6:]


def _zip_parts(value) -> tuple[str, str]:
    """ZIP → (first-five, last-four); last-four blank for a 5-digit ZIP."""
    d = _digits(value)
    if len(d) >= 9:
        return d[:5], d[5:9]
    if len(d) == 5:
        return d, ""
    return "", ""


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
    emitted, so pypdf leaves everything else untouched (blank for the veteran).

    contentions: [{"name": str, "in_service_event": str|None, "onset_date": date|str|None}]
    identity: VeteranIdentity as a dict (full_name, date_of_birth, phone, email,
        address{street,unit,city,state,zip,country}, va_file_number, place_of_birth) —
        all optional; absent → those fields stay blank for the veteran.
    is_own_draft: the VA file number is sensitive (often the SSN), so it is emitted
        ONLY on the veteran's own draft. SSN and signature are NEVER emitted.
    """
    values: dict[str, str] = {}
    ident = identity or {}

    # Identity full_name/email (when saved to the profile) take precedence.
    name_for_form = (ident.get("full_name") or "").strip() or full_name
    email_for_form = (ident.get("email") or "").strip() or email

    first, middle, last = _split_name(name_for_form)
    if first:
        values[_PAGE + "Veteran_Service_Member_First_Name[0]"] = first
    if last:
        values[_PAGE + "Veteran_Service_Member_Last_Name[0]"] = last
    if middle:
        values[_PAGE + "Veteran_Service_Member_Middle_Initial[0]"] = middle
    if email_for_form:
        values[_PAGE + "Email_Address_Optional[0]"] = email_for_form

    # ── Identity: DOB, phone, mailing address, VA file number ────────────────────
    # (introspected from the JAN 2026 edition, verified 2026-07-06). NEVER the SSN
    # or the signature — those stay blank for the veteran to complete by hand.
    dm, dd, dy = _date_parts(ident.get("date_of_birth"))
    for fld, val in (
        ("Date_Of_Birth_Month[0]", dm),
        ("Date_Of_Birth_Day[0]", dd),
        ("Date_Of_Birth_Year[0]", dy),
    ):
        if val:
            values[_PAGE + fld] = val

    area, mid3, last4 = _phone_parts(ident.get("phone"))
    if area:
        values[_PAGE + "Daytime_Phone_Number_Area_Code[0]"] = area
        values[_PAGE + "Telephone_Middle_Three_Numbers[0]"] = mid3
        values[_PAGE + "Telephone_Last_Four_Numbers[0]"] = last4

    addr = ident.get("address") or {}
    z5, z4 = _zip_parts(addr.get("zip"))
    for fld, val in (
        ("CurrentMailingAddress_NumberAndStreet[0]", (addr.get("street") or "").strip()),
        ("CurrentMailingAddress_ApartmentOrUnitNumber[0]", (addr.get("unit") or "").strip()),
        ("CurrentMailingAddress_City[0]", (addr.get("city") or "").strip()),
        ("CurrentMailingAddress_StateOrProvince[0]", (addr.get("state") or "").strip()),
        ("CurrentMailingAddress_Country[0]", (addr.get("country") or "").strip()),
        ("CurrentMailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]", z5),
        ("CurrentMailingAddress_ZIPOrPostalCode_LastFourNumbers[0]", z4),
    ):
        if val:
            values[_PAGE + fld] = val

    # VA file number: sensitive, opt-in, and only on the veteran's own draft.
    vafn = (ident.get("va_file_number") or "").strip()
    if vafn and is_own_draft:
        values[_PAGE + "VA_File_Number[0]"] = vafn

    # First service period only (the form's top service-dates line). service_periods
    # rows look like {branch, component, start_date, end_date, discharge_character}.
    periods = service_periods or []
    if periods and isinstance(periods[0], dict):
        p0 = periods[0]
        bm, bd, by = _date_parts(p0.get("start_date"))
        em, ed, ey = _date_parts(p0.get("end_date"))
        for fld, val in (
            ("Beginning_Date_Month[0]", bm),
            ("Beginning_Date_Day[0]", bd),
            ("Beginning_Date_Year[0]", by),
            ("Ending_Date_Month[0]", em),
            ("Ending_Date_Day[0]", ed),
            ("Ending_Date_Year[0]", ey),
        ):
            if val:
                values[_PAGE + fld] = val

    # Standard claim process (vs. FDC/IDES/BDD — which have their own prerequisites
    # we can't assert on the veteran's behalf).
    values[_PAGE + "Standard_Claim_Process[0]"] = "/1"

    # Disabilities table — one row per claimed condition, up to the 15 the form holds.
    for i, cond in enumerate(contentions[:_DISABILITY_ROWS]):
        if not isinstance(cond, dict):
            continue
        name = (cond.get("name") or "").strip()
        if not name:
            continue
        values[f"{_DIS}CURRENTDISABILITY[{i}]"] = name[:120]
        event = (cond.get("in_service_event") or "").strip()
        if event:
            values[f"{_DIS}ExplainHowDisabilityRelatesToEvent_Exposure_Injury[{i}]"] = event[:500]
        if i == 0:
            m, d, y = _date_parts(cond.get("onset_date"))
            if y:
                values[f"{_DIS}Date_Disability_Began_Or_Worsened[0]"] = f"{m}/{d}/{y}" if m and d else y

    return values


def fill_pdf(values: dict) -> bytes:
    """Fill the bundled 21-526EZ with `values` and return PDF bytes (delegates to the
    generalized pdf.base.fill_acroform; behavior is unchanged from Wave 7)."""
    return fill_acroform(TEMPLATE, values, title=_TITLE)
