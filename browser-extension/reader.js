/*
 * reader.js — Rating Raider VA Connect DOM reader.
 *
 * This file is injected into the ACTIVE va.gov tab ONLY when the user clicks
 * "Read my VA data" in the popup (via chrome.scripting.executeScript).
 *
 * It is strictly READ-ONLY:
 *   - It never submits forms, clicks buttons, or mutates the page.
 *   - It never reads cookies, localStorage, tokens, or auth headers.
 *   - It only parses text that is already rendered on screen for the
 *     signed-in veteran's OWN data.
 *
 * Parsing is intentionally text/heading based (find headings by their words,
 * then walk nearby nodes) rather than relying on VA.gov CSS class names, which
 * change frequently. Every collector is wrapped so an unexpected DOM shape
 * degrades to an empty result instead of throwing.
 *
 * The file is an IIFE whose return value becomes the executeScript result.
 */
(function readVaData() {
  "use strict";

  // ---- small, defensive helpers -------------------------------------------

  function clean(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  // Normalize an "Effective date" phrase like "November 02, 2018".
  function findEffectiveDate(scopeText) {
    if (!scopeText) return null;
    var m = scopeText.match(
      /Effective date:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})/i
    );
    return m ? clean(m[1]) : null;
  }

  // ---- combined rating -----------------------------------------------------
  // Heading like: "Your combined disability rating is 60%"
  function readCombinedRating() {
    try {
      var bodyText = document.body ? document.body.innerText || "" : "";
      var m = bodyText.match(/combined disability rating is\s*(\d{1,3})\s*%/i);
      if (m) {
        var n = parseInt(m[1], 10);
        return isNaN(n) ? null : n;
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  // ---- service-connected conditions ---------------------------------------
  // Cards read like: "60% rating for chronic fatigue syndrome"
  //                  "Effective date: November 02, 2018"
  function readServiceConnected() {
    var out = [];
    try {
      var seen = {};
      var walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        null
      );
      var node;
      while ((node = walker.nextNode())) {
        var t = clean(node.nodeValue);
        // Anchor on the "<n>% rating for <name>" pattern.
        var m = t.match(/^(\d{1,3})%\s+rating for\s+(.+)$/i);
        if (!m) continue;

        var percent = parseInt(m[1], 10);
        if (isNaN(percent)) percent = null;
        var name = clean(m[2]).replace(/[.,;:]+$/, "");
        if (!name) continue;

        // Scope to the nearest card-like container to find the effective date.
        var scope = node.parentElement
          ? node.parentElement.closest(
              "li, article, section, va-card, .vads-c-card, div"
            )
          : null;
        var scopeText = scope ? scope.innerText || "" : "";
        var effective = findEffectiveDate(scopeText);

        var key = name.toLowerCase() + "|" + percent;
        if (seen[key]) continue;
        seen[key] = true;

        out.push({
          name: name,
          percent: percent,
          effective_date: effective,
          disposition: "service_connected"
        });
      }
    } catch (e) {
      /* degrade gracefully */
    }
    return out;
  }

  // ---- denied / not service-connected conditions --------------------------
  // Heading: "Conditions VA determined aren't service-connected"
  // followed by a list of condition names (no percentage).
  function readDenied() {
    var out = [];
    try {
      var headings = Array.prototype.slice.call(
        document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')
      );
      var heading = null;
      for (var i = 0; i < headings.length; i++) {
        if (/aren.?t\s+service-?connected/i.test(headings[i].textContent || "")) {
          heading = headings[i];
          break;
        }
      }
      if (!heading) return out;

      // Walk forward in document order, collecting list items until the next
      // real heading closes the section.
      var all = Array.prototype.slice.call(document.querySelectorAll("*"));
      var start = all.indexOf(heading);
      if (start === -1) return out;

      var seen = {};
      for (var j = start + 1; j < all.length; j++) {
        var el = all[j];
        var isHeading =
          /^H[1-6]$/.test(el.tagName) ||
          el.getAttribute("role") === "heading";
        if (isHeading && clean(el.textContent)) break; // next section

        if (el.tagName === "LI") {
          var name = clean(el.textContent);
          if (
            name &&
            name.length < 140 &&
            !/effective date/i.test(name) &&
            !/rating for/i.test(name) &&
            !seen[name.toLowerCase()]
          ) {
            seen[name.toLowerCase()] = true;
            out.push({
              name: name,
              percent: null,
              effective_date: null,
              disposition: "denied"
            });
          }
        }
      }
    } catch (e) {
      /* degrade gracefully */
    }
    return out;
  }

  // ---- claims / appeals status (optional, best-effort) --------------------
  // Cards with a status (IN PROGRESS / CLOSED) and a title.
  function readClaims() {
    var out = [];
    try {
      var cards = document.querySelectorAll(
        'li, article, va-card, [class*="claim"], [class*="Claim"]'
      );
      var seen = {};
      Array.prototype.forEach.call(cards, function (card) {
        var text = card.innerText || "";
        if (!/in progress|closed|received/i.test(text)) return;

        var title = null;
        var h = card.querySelector("h1,h2,h3,h4,h5,h6,a");
        if (h) title = clean(h.textContent);
        if (!title) {
          var tm = text.match(/(Claim for[^\n]+)/i);
          if (tm) title = clean(tm[1]);
        }
        if (!title || title.length < 4) return;
        title = title.slice(0, 160);

        var key = title.toLowerCase();
        if (seen[key]) return;
        seen[key] = true;

        out.push({
          name: title,
          percent: null,
          effective_date: null,
          disposition: "pending"
        });
      });
    } catch (e) {
      /* degrade gracefully */
    }
    return out;
  }

  // ---- dispatch by page ----------------------------------------------------
  var href = "";
  try {
    href = location.href || "";
  } catch (e) {
    href = "";
  }

  var isRatingsPage = /\/disability\/view-disability-rating\/rating/i.test(href);
  var isClaimsPage =
    /\/claim-or-appeal-status\//i.test(href) || /\/track-claims\//i.test(href);

  var result = {
    ok: false,
    source: "unknown",
    url: href,
    combined_rating: null,
    conditions: []
  };

  if (isRatingsPage) {
    result.source = "ratings";
    result.combined_rating = readCombinedRating();
    result.conditions = readServiceConnected().concat(readDenied());
    result.ok =
      result.combined_rating !== null || result.conditions.length > 0;
  } else if (isClaimsPage) {
    result.source = "claims";
    result.conditions = readClaims();
    result.ok = result.conditions.length > 0;
  } else {
    // Unsupported page — still try ratings parsing in case the URL shape
    // changed, but do not claim success unless something was found.
    result.combined_rating = readCombinedRating();
    var maybe = readServiceConnected().concat(readDenied());
    if (result.combined_rating !== null || maybe.length > 0) {
      result.source = "ratings";
      result.conditions = maybe;
      result.ok = true;
    }
  }

  return result;
})();
