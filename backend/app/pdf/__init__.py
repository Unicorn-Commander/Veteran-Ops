"""PDF generation — the real fillable government forms.

We fill the OFFICIAL VA AcroForm PDFs (bundled under templates/) with the
high-confidence data the app already holds and leave everything we don't collect
(SSN, VA file number, date of birth, address, signature) for the veteran. Each form
stays pristine — no injected pages — and travels as a DRAFT the veteran reviews,
completes, and signs. Rating Raider never files anything.

Wave 8 generalized the original 21-526EZ filler across the form set:
  - base.fill_acroform      — the generalized pypdf fill (DRAFT stamp, NeedAppearances)
  - forms/form_*            — one PURE build_field_values per form (no LLM)
  - registry.REGISTRY       — form_id → FormSpec (edition, OMB, template, filler, labels)

Covered forms: 21-526EZ (disability compensation), 21-8940 (TDIU), 20-0995
(Supplemental Claim), 21-686c (dependents), 21-4138 (statement in support), 21-4142
(authorization to disclose records). pypdf ignores field names that don't exist in a
given edition, so a stale map UNDER-fills — it never mis-fills.
"""
