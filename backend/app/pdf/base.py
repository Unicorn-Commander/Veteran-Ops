"""Generalized VA-form AcroForm filler + shared pure helpers.

`fill_acroform(template_path, values, ...)` is the generalization of the original
`form526_fill.fill_pdf`: it appends the bundled official PDF, sets NeedAppearances so
every viewer renders the entered values, applies `values` to each page (a page with no
matching field is fine), and stamps the DRAFT Title + "Rating Raider" Producer.

Legal-lane contract (identical to 526EZ): pypdf silently ignores field names that
don't exist in the template. So a value map written against a stale edition simply
UNDER-fills — it never mis-fills a renamed field. Callers therefore emit ONLY
non-empty, high-confidence values; everything else stays blank for the veteran.

The name/date helpers here are the shared, deterministic (no-LLM) primitives the
per-form `build_field_values` functions use. `form_21_526ez.py` keeps its own private
copies unchanged (it was moved verbatim); the newer forms import these.
"""

from __future__ import annotations

import io
from datetime import date

PRODUCER = "Rating Raider"


def split_name(full_name: str) -> tuple[str, str, str]:
    """full_name -> (first, middle_initial, last). Best-effort: a single token
    becomes the first name with a blank last name (never guesses a surname)."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    first = parts[0]
    last = parts[-1]
    middle = parts[1][0] if len(parts) > 2 and parts[1] else ""
    return first, middle, last


def year(value) -> str:
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return value[:4]
    return ""


def date_parts(value) -> tuple[str, str, str]:
    """Loose YYYY-MM-DD (or a date) -> (month, day, year) strings; blank on anything
    we can't parse cleanly (we never guess a date onto a federal form)."""
    if isinstance(value, date):
        return f"{value.month:02d}", f"{value.day:02d}", f"{value.year:04d}"
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        y, m, d = value[:4], value[5:7], value[8:10]
        if y.isdigit() and m.isdigit() and d.isdigit():
            return m, d, y
    return "", "", ""


def fill_acroform(template_path, values: dict, *, title: str, producer: str = PRODUCER) -> bytes:
    """Fill the AcroForm at `template_path` with `values` and return PDF bytes.

    NeedAppearances is set so every PDF viewer renders the entered values (Acrobat,
    Preview, Chrome). auto_regenerate=False keeps pypdf from rebuilding appearance
    streams per page (slower and lossy on these XFA-adjacent VA forms)."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import BooleanObject, NameObject

    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    writer.append(reader)

    try:
        writer.set_need_appearances_writer(True)
    except Exception:  # noqa: BLE001 — older pypdf: set the flag directly
        writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    for page in writer.pages:
        try:
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
        except Exception:  # noqa: BLE001 — a page with no matching fields is fine
            continue

    writer.add_metadata({"/Title": title, "/Producer": producer})

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
