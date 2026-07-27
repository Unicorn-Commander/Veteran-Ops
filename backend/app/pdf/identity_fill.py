"""Shared veteran-identity fill for VA AcroForms.

Every form names the same identity fields differently (``VeteransFirstName`` vs
``VeteranFirstName``; ``CurrentMailingAddress_*`` vs ``MailingAddress_*``), so each
filler passes a per-form field-name MAP keyed by logical field. The SSN and the
signature are never in any map, so this helper can never emit them — that is the
legal-lane guarantee, enforced structurally rather than by a per-form check.

Only non-empty values are emitted (pypdf leaves unset fields blank for the veteran).
"""

from __future__ import annotations

from datetime import date


def _digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def _phone_parts(value) -> tuple[str, str, str]:
    d = _digits(value)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    return (d[:3], d[3:6], d[6:]) if len(d) == 10 else ("", "", "")


def _zip_parts(value) -> tuple[str, str]:
    d = _digits(value)
    if len(d) >= 9:
        return d[:5], d[5:9]
    return (d, "") if len(d) == 5 else ("", "")


def _date_parts(value) -> tuple[str, str, str]:
    if isinstance(value, date):
        return f"{value.month:02d}", f"{value.day:02d}", f"{value.year:04d}"
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        y, m, d = value[:4], value[5:7], value[8:10]
        if y.isdigit() and m.isdigit() and d.isdigit():
            return m, d, y
    return "", "", ""


def _name_parts(full_name: str) -> tuple[str, str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    middle = parts[1][0] if len(parts) > 2 and parts[1] else ""
    return parts[0], middle, parts[-1]


# Logical keys a form MAP may provide (omit a key the form lacks). NOTE: there is no
# "ssn" or "signature" key — those are never fillable through this helper by design.
_ADDRESS_KEYS = ("street", "unit", "city", "state", "country", "zip5", "zip4")


def identity_values(
    identity: dict | None,
    fieldmap: dict[str, str],
    *,
    is_own_draft: bool = True,
    full_name_fallback: str = "",
    email_fallback: str = "",
) -> dict[str, str]:
    """Map a VeteranIdentity dict → {acroform_field_name: value} using this form's
    logical→field map. SSN/signature are impossible to emit (not valid keys)."""
    ident = identity or {}
    out: dict[str, str] = {}

    def put(key: str, val: str) -> None:
        field = fieldmap.get(key)
        if field and val:
            out[field] = val

    first, middle, last = _name_parts(
        (ident.get("full_name") or "").strip() or full_name_fallback
    )
    put("first", first)
    put("middle", middle)
    put("last", last)
    put("email", (ident.get("email") or "").strip() or email_fallback)

    dm, dd, dy = _date_parts(ident.get("date_of_birth"))
    put("dob_m", dm)
    put("dob_d", dd)
    put("dob_y", dy)

    area, mid3, last4 = _phone_parts(ident.get("phone"))
    put("phone_area", area)
    put("phone_mid", mid3)
    put("phone_last", last4)

    addr = ident.get("address") or {}
    z5, z4 = _zip_parts(addr.get("zip"))
    addr_vals = {
        "street": (addr.get("street") or "").strip(),
        "unit": (addr.get("unit") or "").strip(),
        "city": (addr.get("city") or "").strip(),
        "state": (addr.get("state") or "").strip(),
        "country": (addr.get("country") or "").strip(),
        "zip5": z5,
        "zip4": z4,
    }
    for key in _ADDRESS_KEYS:
        put(key, addr_vals[key])

    # VA file number is sensitive (often the SSN); only on the veteran's own draft.
    vafn = (ident.get("va_file_number") or "").strip()
    if vafn and is_own_draft:
        put("va_file_number", vafn)

    return out


def spouse_values(
    dependents: list | None, fieldmap: dict[str, str]
) -> dict[str, str]:
    """Map the FIRST spouse in dependents → 21-686c spouse fields (name, DOB,
    marriage date/place). NO SSN (the veteran writes each dependent's SSN by hand)."""
    out: dict[str, str] = {}
    spouse = next(
        (d for d in (dependents or []) if isinstance(d, dict) and d.get("relationship") == "spouse"),
        None,
    )
    if not spouse:
        return out

    def put(key: str, val: str) -> None:
        field = fieldmap.get(key)
        if field and val:
            out[field] = val

    first, middle, last = _name_parts((spouse.get("full_name") or "").strip())
    put("sp_first", first)
    put("sp_middle", middle)
    put("sp_last", last)
    dm, dd, dy = _date_parts(spouse.get("date_of_birth"))
    put("sp_dob_m", dm)
    put("sp_dob_d", dd)
    put("sp_dob_y", dy)
    mm, md, my = _date_parts(spouse.get("marriage_date"))
    put("marriage_m", mm)
    put("marriage_d", md)
    put("marriage_y", my)
    put("marriage_place", (spouse.get("marriage_location") or "").strip())
    return out
