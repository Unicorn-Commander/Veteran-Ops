# Rating Raider — VA Connect (Chrome MV3 extension)

A small, **read-only** browser helper for veterans using **Rating Raider**, a
free educational self-help app for VA disability claims.

While you are signed into **VA.gov** looking at your **own** disability data,
VA Connect lets you click a button to read the ratings/claims already on the
page and hand them to Rating Raider's import screen — **without any VA developer
API**. It reads the page you are already viewing, in your own logged-in session.

---

## What it does

1. You open your **VA disability ratings** page on VA.gov (signed in):
   `https://www.va.gov/disability/view-disability-rating/rating`
   (optionally your claim/appeal status page too).
2. You click the extension icon, then **"Read my VA data."**
3. The extension parses the page and shows you a **preview** of exactly what it
   found: your combined rating, and each condition with its percentage,
   effective date, and disposition (service-connected / denied / pending).
4. You click **"Send to Rating Raider."** A new tab opens to Rating Raider's
   import page with the data attached, where you sign in (if needed), review,
   and apply the reconcile.

That's the entire scope. It is a bridge from *your screen* to *your account* in
Rating Raider.

---

## Privacy & safety stance

- **Read-only.** It never submits forms, clicks action buttons, changes any
  setting, or downloads/exfiltrates anything beyond the ratings/claims data you
  explicitly choose to send.
- **User-initiated only.** Nothing runs automatically. The page reader is
  injected **only** when you click "Read my VA data." There is no background
  script, no polling, no automatic scraping.
- **Never touches credentials.** It does not read cookies, `localStorage`,
  session tokens, or auth headers, and it stores nothing sensitive. It only
  reads text that is already rendered on screen for you.
- **Transparent.** The popup shows you exactly what was read *before* you send
  anything.
- **Hash handoff.** The data is passed to Rating Raider in the URL **fragment**
  (`...#data=...`). Fragments are not sent to servers, so your health data stays
  out of server access logs. Rating Raider reads it client-side.

---

## How to load it (unpacked)

This is delivered as source for you to review and test — it is **not** published
to any store.

1. Open Chrome and go to `chrome://extensions`.
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked**.
4. Select this `browser-extension/` folder.
5. Pin the extension, sign into VA.gov, open your disability ratings page, and
   click the icon.

To point at a local Rating Raider during development, edit `IMPORT_BASE_URL` at
the top of `popup.js` (e.g. `http://localhost:5173/va-import`).

---

## Permissions — and why each is needed

Declared in `manifest.json`. Deliberately minimal:

| Permission | Why |
|---|---|
| `host_permissions: https://*.va.gov/*` | To read the ratings/claims text on VA.gov pages you open. Scoped to VA.gov only — **not** `<all_urls>`. |
| `activeTab` | Grants access to the current tab **only** in response to your click, so the reader can run on the page you're viewing. |
| `scripting` | To inject the read-only `reader.js` into the active VA.gov tab when you click "Read my VA data." |
| `tabs` | To open a new tab to Rating Raider's import page when you click "Send." |

There is intentionally **no** `cookies` permission, **no** `storage` of
sensitive data, **no** host access beyond `va.gov`, and **no** remote code.

---

## File tree

```
browser-extension/
├── manifest.json     # MV3 manifest, minimal permissions
├── reader.js         # read-only DOM parser, injected only on click
├── popup.html        # popup UI
├── popup.css         # popup styles
├── popup.js          # popup controller (detect page, read, preview, send)
├── icons/
│   ├── icon-16.png   # placeholder solid-color icons
│   ├── icon-48.png
│   └── icon-128.png
└── README.md
```

The `icons/*.png` files are simple solid-color placeholders — replace them with
real brand art before any release.

---

## How the parsing works

VA.gov changes its CSS class names often, so the reader parses by **text and
headings**, not brittle selectors:

- **Combined rating:** regex over the page text for
  `combined disability rating is <n>%`.
- **Service-connected conditions:** a `TreeWalker` over text nodes finds each
  `<n>% rating for <name>` line, then looks in the nearest card-like container
  for a matching `Effective date: <Month DD, YYYY>`.
- **Denied conditions:** finds the heading whose text contains
  `aren't service-connected`, then collects the list items that follow until the
  next heading.
- **Claims/appeals (optional):** best-effort — cards containing a status word
  (`in progress` / `closed` / `received`) with a title, recorded as `pending`.

Every collector is wrapped so unexpected DOM shapes degrade to an empty result
and the popup tells you it "couldn't read this page" instead of crashing.

The handed-off payload:

```json
{
  "combined_rating": 60,
  "conditions": [
    {
      "name": "chronic fatigue syndrome",
      "percent": 60,
      "effective_date": "November 02, 2018",
      "disposition": "service_connected"
    }
  ]
}
```

`disposition` is one of `service_connected`, `denied`, or `pending`.

---

## ⚠️ Before publishing

**Review VA.gov's Terms of Service regarding automated access.** This extension
reads only the user's own data, in their own authenticated session, on an
explicit action — but **get a legal skim before any public store release.**
Automated-access and scraping clauses can apply even to read-only, user-initiated
tools. This is educational self-help software; treat the ToS review as a gate on
distribution, not an afterthought.

---

## Notes / not tested

Built as vanilla JS with no build step so it loads unpacked directly. The
popup/reader logic was reasoned through but **not executed in a real browser**
(no VA.gov test account available here). Two things to verify on first live run:

1. **Effective-date pairing** on the ratings page — confirm each condition's
   date maps to the right card (the reader scopes to the nearest
   `li/article/section/va-card/div`; if VA nests differently, dates may need the
   container selector tightened).
2. **Denied section boundary** — confirm the "aren't service-connected" list is
   captured and stops at the correct next heading.

Both degrade safely (missing date → `null`, missing section → empty) rather than
breaking the read.
