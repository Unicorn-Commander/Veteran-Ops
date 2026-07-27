"""Supporting-research links for a nexus theory, via Center Deep.

A nexus opinion is the provider's — but the medical LITERATURE that supports the
causal link is public research, and pulling it is exactly what makes a strong nexus
(and what expensive nexus services charge for). We build a DE-IDENTIFIED research
query (the condition + the causal theory only — never the veteran's name, record, or
any PII) and a deep-link to the Center Deep instance that matches the valor host the
veteran is on, so they/their provider can run the search and cite the studies.

Legal + PII line: this is a literature search the PROVIDER considers when writing
their opinion — we never write the opinion. The query carries no PII, so it is safe
even though Center Deep may use larger/cloud models for research.
"""

from __future__ import annotations

import urllib.parse

from ..config import settings


def center_deep_base(host: str | None) -> str:
    """The Center Deep instance for a given valor host — prod research for the
    unicorncommander.ai deployment, the dev instance otherwise."""
    h = (host or "").split(":")[0].strip().lower()
    if h.endswith("unicorncommander.ai"):
        return settings.center_deep_url_unicorncommander.rstrip("/")
    return settings.center_deep_url_default.rstrip("/")


def _theory_query(condition: str, primary: str | None, exposure: str | None) -> str:
    """A de-identified medical-literature query for the causal theory. Only the
    condition + the link being argued — no veteran identifiers."""
    condition = (condition or "").strip()
    if primary:
        return f"peer-reviewed medical literature: {condition} secondary to / caused or aggravated by {primary.strip()}"
    if exposure:
        return f"peer-reviewed medical literature linking {condition} to {exposure.strip()} exposure"
    return f"peer-reviewed medical literature on the cause and etiology of {condition}"


def nexus_research(
    *,
    condition: str,
    host: str | None = None,
    primary: str | None = None,
    exposure: str | None = None,
) -> dict:
    """A ready supporting-research link for a nexus theory: the de-identified query
    plus a deep-link to the right Center Deep instance. The provider cites what it
    finds; we never assert the medical opinion."""
    query = _theory_query(condition, primary, exposure)
    base = center_deep_base(host)
    url = f"{base}/search?" + urllib.parse.urlencode({"q": query})
    return {
        "condition": condition,
        "research_query": query,
        "center_deep_url": url,
        "how_to_use": (
            "Open this in Center Deep to pull peer-reviewed studies supporting the "
            "link. Bring the studies to your provider — they cite the literature in "
            "the nexus rationale and sign the opinion. We never write the opinion or "
            "send any of your personal information in this search."
        ),
    }
