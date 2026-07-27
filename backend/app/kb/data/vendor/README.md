# Vendored VA open-data files

Snapshot copies of U.S. Department of Veterans Affairs open-source datasets,
vendored so loaders work offline and deterministically. All three files are
**CC0 1.0 Universal (public domain)** per their upstream repositories.

**Fetched: 2026-07-05** (branch `main` of each repo at fetch time).

| File | Upstream repo | Upstream path |
|---|---|---|
| `max_ratings.csv` | [department-of-veterans-affairs/disability-max-ratings-api](https://github.com/department-of-veterans-affairs/disability-max-ratings-api) | `src/python_src/util/data/Diagnostic Code Lookup Table.csv` |
| `contention_dc_lookup.csv` | [department-of-veterans-affairs/contention-classification-api](https://github.com/department-of-veterans-affairs/contention-classification-api) | `src/python_src/util/data/dc_lookup_table/[Release notes] Diagnostic Code to Classification mapping release notes - DC Lookup v0.6.csv` |
| `contention_text_lookup.csv` | [department-of-veterans-affairs/contention-classification-api](https://github.com/department-of-veterans-affairs/contention-classification-api) | `src/python_src/util/data/master_taxonomy/CC Taxonomy master - v0.3.csv` |

`dc_exclusions.csv` is a separate, small application rule table (not part of
those CC0 datasets). Each row carries its own 38 CFR citation and a conservative
same-joint/same-manifestation explanation. The deep-dive conflict resolver uses
it only to annotate and rank mutually exclusive planning lanes; it never deletes
a finding or decides what VA will award.

Notes:
- The contention-classification repo keeps multiple versioned CSVs; the versions
  vendored here are the ones its own `src/python_src/util/app_config.yaml`
  declares current (`diagnostic_code_table` v0.6, `condition_dropdown_table` /
  taxonomy v0.3). Yes, the current DC table upstream really is the file whose
  name starts with `[Release notes]` — that is the data file, not release notes.
- `max_ratings.csv` columns: Diagnostic Code, Rated Issue Name, Max Rating,
  Body System, Category, Subcategory, CFR Reference.
- These are educational reference data. Every user-facing surface that uses them
  must keep the legal-lane framing (see docs/BUILD-SPEC.md) and point veterans
  at eCFR / VA.gov for the authoritative, current text.

To refresh: re-download from the raw.githubusercontent.com paths above, update
the fetch date here, and bump `KB_VERIFIED_AS_OF` in `app/kb/freshness.py` after
re-verifying the KB cards.
