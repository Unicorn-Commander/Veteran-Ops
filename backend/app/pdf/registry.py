"""Registry mapping a VA form_id → its filler (Wave 8).

Each entry ties a public form_id (the number the veteran sees on the PDF) to its
edition/OMB, bundled template, PURE `build_field_values`, and the AUTO_FILLED /
YOU_COMPLETE label lists the UI shows so the download is honestly labeled — filled
vs. what the veteran must still complete and sign. All fillers share one signature:

    build_field_values(*, full_name, email, service_periods, contentions) -> dict

so the endpoint assembles a single dossier and dispatches by form_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .base import fill_acroform
from .forms import (
    form_20_0995,
    form_21_526ez,
    form_21_686c,
    form_21_4138,
    form_21_4142,
    form_21_8940,
)


@dataclass(frozen=True)
class FormSpec:
    form_id: str
    edition: str
    omb: str
    title: str
    template: Path
    build_field_values: Callable[..., dict]
    auto_filled: list[str]
    you_complete: list[str]
    draft_filename: str
    draft_title: str

    def fill(self, values: dict) -> bytes:
        """Fill this form's template with a value map (DRAFT stamped)."""
        return fill_acroform(self.template, values, title=self.draft_title)


def _spec(mod) -> FormSpec:
    return FormSpec(
        form_id=mod.FORM_ID,
        edition=mod.FORM_EDITION,
        omb=mod.FORM_OMB,
        title=mod.FORM_TITLE,
        template=mod.TEMPLATE,
        build_field_values=mod.build_field_values,
        auto_filled=mod.AUTO_FILLED,
        you_complete=mod.YOU_COMPLETE,
        draft_filename=mod.DRAFT_FILENAME,
        draft_title=mod._TITLE,
    )


REGISTRY: dict[str, FormSpec] = {
    m.FORM_ID: _spec(m)
    for m in (
        form_21_526ez,
        form_21_8940,
        form_20_0995,
        form_21_686c,
        form_21_4138,
        form_21_4142,
    )
}


def get_spec(form_id: str) -> FormSpec | None:
    """Case-insensitive lookup (URLs may lower-case the id, e.g. 21-526ez)."""
    if not form_id:
        return None
    return REGISTRY.get(form_id) or REGISTRY.get(form_id.lower())
