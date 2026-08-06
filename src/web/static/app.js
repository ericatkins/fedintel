/* Fedintel terminal interactions: command palette (Ctrl+K) + j/k table nav.
   No user data is interpolated into HTML here; navigation uses fixed routes
   and encodeURIComponent-escaped query values only. */
(function () {
  "use strict";

  // ---- command palette ----
  var palette = document.getElementById("palette");
  var input = document.getElementById("palette-input");
  var list = document.getElementById("palette-list");
  if (!palette) return;

  var commands = [
    { label: "Go: Home dashboard", run: function () { go("/app"); } },
    { label: "Go: Opportunities", run: function () { go("/app/opportunities"); } },
    { label: "Go: Watchlist", run: function () { go("/app/watchlist"); } },
    { label: "Go: Alerts", run: function () { go("/app/alerts"); } },
    { label: "Go: Company profile", run: function () { go("/app/profile"); } },
    { label: "Go: Agencies", run: function () { go("/app/agencies"); } },
    { label: "Go: Vendors", run: function () { go("/app/vendors"); } },
    { label: "Go: Reports", run: function () { go("/app/reports"); } },
    { label: "Export: opportunities CSV", run: function () { go("/app/opportunities.csv"); } },
    { label: "Filter: high match (score > 80)", run: function () { go("/app/opportunities?min_score=80"); } },
    { label: "Filter: closing soon", run: function () { go("/app/opportunities?min_score=0&q=&notice_type=solicitation"); } },
    { label: "Filter: sources sought", run: function () { go("/app/opportunities?notice_type=sources%20sought&min_score=0"); } }
  ];

  function go(url) { window.location.href = url; }

  function items(q) {
    q = q.trim().toLowerCase();
    var out = commands.filter(function (c) { return c.label.toLowerCase().indexOf(q) !== -1; });
    if (q) {
      var m = q.match(/score\s*>\s*(\d{1,3})/);
      if (m) out.unshift({ label: "Filter: score > " + m[1],
        run: function () { go("/app/opportunities?min_score=" + encodeURIComponent(m[1])); } });
      var vm = q.match(/^vendor\s+(.+)/);
      if (vm) out.unshift({ label: 'Search vendors: "' + vm[1] + '"',
        run: function () { go("/app/vendors?q=" + encodeURIComponent(vm[1])); } });
      out.push({ label: 'Search opportunities: "' + q + '"',
        run: function () { go("/app/opportunities?q=" + encodeURIComponent(q)); } });
    }
    return out.slice(0, 9);
  }

  var active = 0;
  function paint() {
    var q = input.value;
    var opts = items(q);
    list.textContent = "";
    opts.forEach(function (c, i) {
      var li = document.createElement("li");
      li.textContent = c.label;             // textContent only — never innerHTML
      if (i === active) li.className = "active";
      li.addEventListener("click", c.run);
      list.appendChild(li);
    });
    list._opts = opts;
  }

  function openPalette() { palette.classList.remove("hidden"); input.value = ""; active = 0; paint(); input.focus(); }
  function closePalette() { palette.classList.add("hidden"); }

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (!palette.classList.contains("hidden")) {
      if (e.key === "Escape") { closePalette(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, (list._opts || []).length - 1); paint(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); paint(); }
      else if (e.key === "Enter") { e.preventDefault(); var o = (list._opts || [])[active]; if (o) o.run(); }
      return;
    }
    // ---- j/k row navigation on data tables ----
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
    var rows = Array.prototype.slice.call(document.querySelectorAll("table.kb tbody tr"));
    if (!rows.length) return;
    var idx = rows.findIndex(function (r) { return r.classList.contains("kb-focus"); });
    if (e.key === "j" || e.key === "k") {
      e.preventDefault();
      if (idx >= 0) rows[idx].classList.remove("kb-focus");
      idx = e.key === "j" ? Math.min(idx + 1, rows.length - 1) : Math.max(idx - 1, 0);
      rows[idx].classList.add("kb-focus");
      rows[idx].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && idx >= 0) {
      var link = rows[idx].querySelector("a[data-row-link]");
      if (link) { e.preventDefault(); link.click(); }
    }
  });
  input.addEventListener("input", function () { active = 0; paint(); });
})();
