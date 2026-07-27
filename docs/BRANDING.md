# Branding — Veteran-Ops vs Rating Raider

**Decision (2026-07-26).**

| Layer | Name | Notes |
|-------|------|--------|
| **Product / app / platform** | **Veteran-Ops** | What the product *is*. Repo/infra may still say `valor-ops` until the lockstep rename in `docs/rename-veteran-ops.md`. |
| **Main agent (first agent)** | **Rating Raider** | Conversational CWO / claims agent surface (`/raider`). Other specialists may appear later; this is the flagship agent. |
| **Dogfood host (today)** | `valor.magicunicorn.dev` | Keep until production cutover. |
| **Production web (planned)** | `veteranops.magicunicorn.dev` | Also register `veteran-ops.magicunicorn.dev` as optional alias if desired. |
| **Production email (planned)** | `veteran-ops@magicunicorn.dev` | From-name **Veteran-Ops**; agent copy still “Rating Raider” in-product. |

## User-facing copy rules

- **Chrome / app name / titles / emails / PWA short name:** “Veteran-Ops”.
- **Chat agent, “ask …”, thinking states, agent tools:** “Rating Raider”.
- **Legal disclaimers:** Lead with **Veteran-Ops** as the software; mention Rating Raider only when referring to the agent persona.

Example:

> Veteran-Ops is self-help educational software. Rating Raider is your claims agent inside the app. Neither is a VA-accredited representative…

## Domains (production cutover — do not flip alone)

Additive first, then primary, then redirect (same order as platform rename):

1. DNS + Traefik: `veteranops.magicunicorn.dev` (+ optional `veteran-ops.magicunicorn.dev`) → same frontend.
2. Keycloak redirect URIs for both old and new hosts.
3. `SSO_REDIRECT_BASE`, `SSO_ALLOWED_HOSTS`, OG URLs.
4. Email From: `veteran-ops@magicunicorn.dev` (or suite alias).
5. After soak: redirect `valor.magicunicorn.dev` → `veteranops.magicunicorn.dev`.

## Related

- Platform/infra rename contracts: `docs/rename-veteran-ops.md`
- Fleet GPU routing: `docs/FLEET-LLM-ROUTING.md`
