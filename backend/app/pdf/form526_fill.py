"""Backward-compat shim (Wave 8).

The canonical 21-526EZ logic moved to pdf/forms/form_21_526ez.py when the filler was
generalized across the VA form set. This module re-exports the same public names so
the existing routers/form526.py `from ..pdf.form526_fill import build_field_values,
fill_pdf` keeps working unchanged. New code should import from pdf.registry or
pdf.forms.form_21_526ez directly.
"""

from __future__ import annotations

from .forms.form_21_526ez import (  # noqa: F401
    AUTO_FILLED,
    FORM_EDITION,
    FORM_OMB,
    TEMPLATE,
    YOU_COMPLETE,
    _DIS,
    _PAGE,
    build_field_values,
    fill_pdf,
)
