/**
 * golos docs — lightweight help-center behaviors (no framework).
 * Search/filter on the landing page; shared hooks for child pages.
 */
(function () {
  "use strict";

  function normalize(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function initSearch() {
    var root = document.querySelector("[data-docs-search]");
    if (!root) return;

    var input = root.querySelector('input[type="search"]');
    var clearBtn = root.querySelector("[data-docs-search-clear]");
    var status = root.querySelector("[data-docs-search-status]");
    var items = Array.prototype.slice.call(
      document.querySelectorAll("[data-docs-item]")
    );
    if (!input || !items.length) return;

    var total = items.length;

    function setClearVisible(on) {
      if (!clearBtn) return;
      clearBtn.classList.toggle("is-visible", on);
      clearBtn.hidden = !on;
    }

    function setStatus(visible, query) {
      if (!status) return;
      if (!query) {
        status.textContent = "";
        status.removeAttribute("data-state");
        status.removeAttribute("aria-live");
        return;
      }
      status.setAttribute("aria-live", "polite");
      if (visible === 0) {
        status.dataset.state = "empty";
        status.textContent =
          'No topics match “' + query + '”. Try another keyword.';
      } else if (visible === total) {
        status.dataset.state = "all";
        status.textContent = "Showing all " + total + " topics.";
      } else {
        status.dataset.state = "filtered";
        status.textContent =
          "Showing " + visible + " of " + total + " topics.";
      }
    }

    function applyFilter() {
      var query = normalize(input.value);
      var visible = 0;

      items.forEach(function (item) {
        var hay = normalize(
          item.getAttribute("data-docs-keywords") ||
            item.textContent ||
            ""
        );
        var match = !query || hay.indexOf(query) !== -1;
        item.hidden = !match;
        item.classList.toggle("is-filtered-out", !match);
        if (match) visible += 1;
      });

      setClearVisible(Boolean(query));
      setStatus(visible, query ? input.value.trim() : "");
    }

    input.addEventListener("input", applyFilter);
    input.addEventListener("search", applyFilter);

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        input.value = "";
        applyFilter();
        input.focus();
      });
    }

    // Escape clears when the search field is focused.
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && input.value) {
        event.preventDefault();
        input.value = "";
        applyFilter();
      }
    });

    applyFilter();
  }

  function initExternalLinks() {
    // Ensure external links opened in a new tab are safe when present.
    document.querySelectorAll('a[target="_blank"]').forEach(function (link) {
      var rel = (link.getAttribute("rel") || "").split(/\s+/).filter(Boolean);
      if (rel.indexOf("noopener") === -1) rel.push("noopener");
      if (rel.indexOf("noreferrer") === -1) rel.push("noreferrer");
      link.setAttribute("rel", rel.join(" "));
    });
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  ready(function () {
    initSearch();
    initExternalLinks();
  });
})();
