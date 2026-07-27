"""Game Plan — the strategy layer (Wave 8).

One deterministic engine that reads everything the app already knows (conditions,
evidence gaps/readiness, decoded denials, suggested secondaries/presumptives, current
combined rating, ITF status) and assembles it into an organized snapshot, a few
ranked pathways to consider, and a prioritized action list.

Educational only. It proposes options; the veteran decides. Estimated combined
ratings are §4.25 math on the veteran's OWN target ratings — never a prediction of
what VA will decide, and never a promise. Every estimate carries its basis label.
"""
