/*
 * popup.js — Rating Raider VA Connect popup controller.
 *
 * Flow:
 *   1. On open, inspect the active tab. Enable "Read my VA data" only on a
 *      supported va.gov page; otherwise explain why it is disabled.
 *   2. On click, inject reader.js into the active tab (chrome.scripting) and
 *      render a transparent preview of exactly what was read.
 *   3. On "Send to Rating Raider", open a new tab to the import page with the
 *      payload in the URL *fragment* (keeps health data out of server logs).
 *
 * No credentials, cookies, or tokens are ever touched. Injection only happens
 * on the explicit "Read my VA data" click.
 */
(function () {
  "use strict";

  // Base URL of Rating Raider's import page. Change to a localhost origin for
  // local development, e.g. "http://localhost:5173/va-import".
  var IMPORT_BASE_URL = "https://valor.magicunicorn.dev/va-import";

  // Supported VA.gov pages (used for the enable/disable hint in the popup).
  var SUPPORTED = [
    {
      test: /^https:\/\/www\.va\.gov\/disability\/view-disability-rating\/rating/i,
      label: "disability ratings"
    },
    {
      test: /^https:\/\/www\.va\.gov\/claim-or-appeal-status\//i,
      label: "claim & appeal status"
    },
    {
      test: /^https:\/\/www\.va\.gov\/track-claims\//i,
      label: "claim status"
    }
  ];

  var els = {};
  var lastPayload = null; // the { combined_rating, conditions } we will send

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.status = document.getElementById("rr-status");
    els.read = document.getElementById("rr-read");
    els.preview = document.getElementById("rr-preview");
    els.combined = document.getElementById("rr-combined-value");
    els.countSc = document.getElementById("rr-count-sc");
    els.countDenied = document.getElementById("rr-count-denied");
    els.countPending = document.getElementById("rr-count-pending");
    els.list = document.getElementById("rr-list");
    els.send = document.getElementById("rr-send");

    els.read.addEventListener("click", onRead);
    els.send.addEventListener("click", onSend);

    detectActiveTab();
  }

  // ---- tab detection -------------------------------------------------------

  function getActiveTab(cb) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      cb(tabs && tabs.length ? tabs[0] : null);
    });
  }

  function matchSupported(url) {
    if (!url) return null;
    for (var i = 0; i < SUPPORTED.length; i++) {
      if (SUPPORTED[i].test.test(url)) return SUPPORTED[i];
    }
    return null;
  }

  function detectActiveTab() {
    getActiveTab(function (tab) {
      if (!tab || !tab.url) {
        setStatus("Couldn't read the active tab.", "warn");
        els.read.disabled = true;
        return;
      }
      var match = matchSupported(tab.url);
      var isVaGov = /^https:\/\/([a-z0-9-]+\.)*va\.gov\//i.test(tab.url);

      if (match) {
        setStatus(
          "Ready on your VA " + match.label + " page. Click below to read it.",
          "ok"
        );
        els.read.disabled = false;
      } else if (isVaGov) {
        setStatus(
          "You're on VA.gov, but not a supported page. Open your disability " +
            "ratings page (Profile → Disability rating) and try again.",
          "warn"
        );
        els.read.disabled = true;
      } else {
        setStatus(
          "Open VA.gov and sign in, then go to your disability ratings page " +
            "to use VA Connect.",
          "warn"
        );
        els.read.disabled = true;
      }
    });
  }

  // ---- read (inject reader.js on explicit click) ---------------------------

  function onRead() {
    els.read.disabled = true;
    setStatus("Reading this page…", null);

    getActiveTab(function (tab) {
      if (!tab || !tab.id) {
        setStatus("Couldn't access the active tab.", "error");
        els.read.disabled = false;
        return;
      }
      if (!matchSupported(tab.url)) {
        setStatus("This isn't a supported VA.gov page.", "warn");
        els.read.disabled = false;
        return;
      }

      try {
        chrome.scripting.executeScript(
          { target: { tabId: tab.id }, files: ["reader.js"] },
          function (results) {
            els.read.disabled = false;

            if (chrome.runtime.lastError) {
              setStatus(
                "Couldn't read this page (" +
                  chrome.runtime.lastError.message +
                  "). Make sure you're signed in and try again.",
                "error"
              );
              return;
            }
            var data =
              results && results.length ? results[0].result : null;
            handleReadResult(data);
          }
        );
      } catch (e) {
        els.read.disabled = false;
        setStatus("Couldn't run the reader: " + e.message, "error");
      }
    });
  }

  function handleReadResult(data) {
    if (!data || !data.ok) {
      setStatus(
        "Couldn't read any ratings or claims from this page. VA.gov may have " +
          "changed its layout, or the page hasn't finished loading. Try " +
          "refreshing and reading again.",
        "warn"
      );
      els.preview.hidden = true;
      lastPayload = null;
      return;
    }

    // Build the payload we will hand to Rating Raider.
    lastPayload = {
      combined_rating:
        typeof data.combined_rating === "number"
          ? data.combined_rating
          : null,
      conditions: Array.isArray(data.conditions) ? data.conditions : []
    };

    renderPreview(lastPayload, data.source);
  }

  // ---- preview rendering (transparency) ------------------------------------

  function renderPreview(payload, source) {
    var conds = payload.conditions;
    var counts = { service_connected: 0, denied: 0, pending: 0 };
    conds.forEach(function (c) {
      if (counts[c.disposition] !== undefined) counts[c.disposition]++;
    });

    els.combined.textContent =
      payload.combined_rating === null ? "—" : payload.combined_rating + "%";
    els.countSc.textContent = counts.service_connected + " service-connected";
    els.countDenied.textContent = counts.denied + " denied";
    els.countPending.textContent = counts.pending + " pending";

    // Rebuild the list safely (textContent only — never innerHTML from page).
    els.list.textContent = "";
    conds.forEach(function (c) {
      els.list.appendChild(renderItem(c));
    });

    els.preview.hidden = false;

    var summary =
      "Read " +
      conds.length +
      " condition" +
      (conds.length === 1 ? "" : "s") +
      (payload.combined_rating !== null
        ? " and a " + payload.combined_rating + "% combined rating"
        : "") +
      ". Review below, then send.";
    setStatus(summary, "ok");
  }

  function renderItem(c) {
    var li = document.createElement("li");
    li.className = "rr-list-item";

    var main = document.createElement("div");
    main.className = "rr-item-main";

    var name = document.createElement("div");
    name.className = "rr-item-name";
    name.textContent = c.name || "(unnamed condition)";

    var badge = document.createElement("span");
    badge.className = "rr-badge " + badgeClass(c.disposition);
    badge.textContent = badgeLabel(c.disposition);
    name.appendChild(badge);
    main.appendChild(name);

    if (c.effective_date) {
      var meta = document.createElement("div");
      meta.className = "rr-item-meta";
      meta.textContent = "Effective " + c.effective_date;
      main.appendChild(meta);
    }
    li.appendChild(main);

    if (typeof c.percent === "number") {
      var pct = document.createElement("div");
      pct.className = "rr-item-pct";
      pct.textContent = c.percent + "%";
      li.appendChild(pct);
    }
    return li;
  }

  function badgeClass(d) {
    if (d === "denied") return "rr-badge-denied";
    if (d === "pending") return "rr-badge-pending";
    return "rr-badge-sc";
  }

  function badgeLabel(d) {
    if (d === "denied") return "denied";
    if (d === "pending") return "pending";
    return "service-connected";
  }

  // ---- send (open Rating Raider import tab) --------------------------------

  function onSend() {
    if (!lastPayload) {
      setStatus("Nothing to send yet — read your VA data first.", "warn");
      return;
    }
    try {
      var encoded = encodeURIComponent(JSON.stringify(lastPayload));
      var url = IMPORT_BASE_URL + "#data=" + encoded;
      chrome.tabs.create({ url: url });
      setStatus("Opened Rating Raider. Review and apply the import there.", "ok");
    } catch (e) {
      setStatus("Couldn't build the handoff link: " + e.message, "error");
    }
  }

  // ---- status helper -------------------------------------------------------

  function setStatus(msg, kind) {
    els.status.textContent = msg;
    els.status.className = "rr-status" + (kind ? " rr-" + kind : "");
  }
})();
