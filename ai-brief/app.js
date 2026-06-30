/* The AI Brief — rendering + interactivity. Vanilla JS, no dependencies. */
(function () {
  "use strict";
  var E = window.EDITION || {};
  var LS_ROLE = "aibrief.role";

  // ── helpers ───────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function el(id) { return document.getElementById(id); }
  function getRole() {
    var r = null;
    try { r = localStorage.getItem(LS_ROLE); } catch (e) {}
    if (r && (E.roles || []).indexOf(r) !== -1) return r;
    return E.defaultRole || (E.roles && E.roles[0]) || "Engineering Leader";
  }
  function setRole(r) { try { localStorage.setItem(LS_ROLE, r); } catch (e) {} }
  function qs(name) {
    var m = new RegExp("[?&]" + name + "=([^&]*)").exec(location.search);
    return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : null;
  }
  function story(id) { return (E.stories || {})[id]; }
  function lvlClass(v) { return String(v || "").toLowerCase(); }

  function signalChips(s, opts) {
    if (!s) return "";
    var compact = opts && opts.compact;
    var parts = [
      ["Signal", s.signal, lvlClass(s.signal)],
      ["Novelty", s.novelty, lvlClass(s.novelty)],
      ["Practical", s.practical, lvlClass(s.practical)],
      ["Hype", s.hype, "hype-" + lvlClass(s.hype)],
    ];
    if (compact) parts = [parts[0], parts[3]]; // Signal + Hype only
    return '<span class="chips">' + parts.map(function (p) {
      return '<span class="chip ' + p[2] + '"><span class="k">' + p[0] + '</span> ' + esc(p[1]) + "</span>";
    }).join("") + "</span>";
  }

  function articleHref(id) { return "article.html?id=" + encodeURIComponent(id); }

  // ── masthead / nav / persona bar (shared) ──────────────────────────────
  function renderChrome() {
    var mh = el("masthead");
    if (mh) {
      mh.innerHTML =
        '<div class="wrap">' +
          '<div class="masthead-top">' +
            "<span>" + esc(E.editionLabel || "Today’s Edition") + "</span>" +
            (E.sample ? '<span class="sample-tag">Sample edition · illustrative content</span>' : "") +
            "<span>" + esc(E.date || "") + "</span>" +
          "</div>" +
          '<h1 class="title"><a href="index.html">' + esc(E.masthead || "The AI Brief") + "</a></h1>" +
          '<p class="subtitle">' + esc(E.tagline || "") + "</p>" +
          '<div class="dateline">' +
            "<b>" + esc(E.date || "") + "</b>" +
            (E.nav || []).slice(0, 8).map(function (n) {
              return '<span class="sep">·</span><span>' + esc(n) + "</span>";
            }).join("") +
          "</div>" +
        "</div>";
    }

    var nav = el("nav");
    if (nav) {
      nav.innerHTML =
        '<div class="wrap"><div class="nav-row">' +
          (E.nav || []).map(function (n) {
            return '<a href="index.html#' + esc(n.toLowerCase().replace(/\s+/g, "")) + '">' + esc(n) + "</a>";
          }).join("") +
        "</div></div>";
    }

    var pb = el("personaBar");
    if (pb) {
      var role = getRole();
      pb.innerHTML =
        '<div class="wrap"><div class="persona-bar">' +
          '<span class="lbl">Why this matters to you →</span>' +
          '<select id="roleSelect" aria-label="Choose your role">' +
            (E.roles || []).map(function (r) {
              return '<option value="' + esc(r) + '"' + (r === role ? " selected" : "") + ">" + esc(r) + "</option>";
            }).join("") +
          "</select>" +
          '<span class="hint">Story implications rewrite for your role.</span>' +
        "</div></div>";
      var sel = el("roleSelect");
      sel.addEventListener("change", function () {
        setRole(sel.value);
        if (window.__rerender) window.__rerender();
      });
    }
  }

  // ── HOMEPAGE ───────────────────────────────────────────────────────────
  function storyCard(id, role) {
    var s = story(id);
    if (!s) return "";
    var note = s.personas && s.personas[role];
    return (
      '<div class="card">' +
        '<div class="meta"><span class="kicker">' + esc(s.kicker) + "</span>" +
          '<span class="dot">·</span><span class="readtime">' + s.readTime + " min read</span></div>" +
        '<h3><a href="' + articleHref(id) + '">' + esc(s.headline) + "</a></h3>" +
        '<p class="summary">' + esc(s.summary) + "</p>" +
        '<div class="meta">' + signalChips(s.signal, { compact: true }) + "</div>" +
        (note ? '<div class="persona-note"><b>' + esc(role) + ":</b> " + esc(note) + "</div>" : "") +
      "</div>"
    );
  }

  function rankedList(ids) {
    return '<ol class="ranked">' + ids.map(function (id) {
      var s = story(id);
      if (!s) return "";
      return "<li><div><span class=\"tag\">" + esc(s.kicker) + "</span>" +
        '<h4><a href="' + articleHref(id) + '">' + esc(s.headline) + "</a></h4>" +
        '<p class="note">' + esc(s.summary) + "</p></div></li>";
    }).join("") + "</ol>";
  }

  function renderLead(role) {
    var s = story(E.lead);
    if (!s) return "";
    return (
      '<section id="today" class="article-anchor">' +
      '<div class="grid lead-grid">' +
        '<div class="lead">' +
          '<div class="meta"><span class="kicker">Lead Story · ' + esc(s.kicker) + "</span>" +
            '<span class="dot">·</span><span class="readtime">' + s.readTime + " min brief</span></div>" +
          '<h1><a href="' + articleHref(s.id) + '">' + esc(s.headline) + "</a></h1>" +
          '<p class="takeaway">' + esc(s.takeaway) + "</p>" +
          '<div class="why-strip"><span class="lbl">Why it matters</span><p>' + esc(s.whyItMatters) + "</p></div>" +
          '<div class="meta">' + signalChips(s.signal) + "</div>" +
          '<a class="btn" href="' + articleHref(s.id) + '">Read the ' + s.readTime + "-min brief →</a>" +
        "</div>" +
        '<div class="col-divider">' +
          '<div class="sec-head" style="margin-top:0"><h2>The 5 Things</h2><span class="sub">that matter today</span></div>' +
          fiveThingsCompact() +
        "</div>" +
      "</div></section>"
    );
  }

  function fiveThingsCompact() {
    return '<ol class="ranked">' + (E.fiveThings || []).map(function (t) {
      var s = story(t.id) || {};
      return "<li><div><span class=\"tag\">" + esc(t.label) + "</span>" +
        '<h4><a href="' + articleHref(t.id) + '">' + esc(s.headline || t.id) + "</a></h4>" +
        '<p class="note">' + esc(t.note) + "</p></div></li>";
    }).join("") + "</ol>";
  }

  function renderTopAndMarket(role) {
    var top = (E.sections && E.sections.top) || [];
    var market = (E.sections && E.sections.market) || [];
    return (
      '<div class="grid two-col">' +
        '<div id="models"><div class="sec-head"><h2>Top Stories</h2><span class="sub">Models · Agents · Coding</span></div>' +
          rankedList(top) + "</div>" +
        '<div id="startups" class="col-divider"><div class="sec-head" style="margin-top:0"><h2>Market / Industry</h2><span class="sub">Funding · M&amp;A · Moves</span></div>' +
          market.map(function (id) { return storyCard(id, role); }).join("") + "</div>" +
      "</div>"
    );
  }

  function renderBuildersLeaders(role) {
    var builders = (E.sections && E.sections.builders) || [];
    var leaders = (E.sections && E.sections.leaders) || [];
    return (
      '<div class="grid two-col">' +
        '<div id="coding"><div class="sec-head"><h2>For Builders</h2><span class="sub">Repos · papers · tools</span></div>' +
          builders.map(function (id) { return storyCard(id, role); }).join("") + "</div>" +
        '<div class="col-divider"><div class="sec-head" style="margin-top:0"><h2>For Leaders</h2><span class="sub">Strategy · org · risk</span></div>' +
          leaders.map(function (id) { return storyCard(id, role); }).join("") + "</div>" +
      "</div>"
    );
  }

  function renderFiveBox() {
    return (
      '<div class="five">' +
        '<span class="kick">Daily executive summary</span>' +
        "<h2>The 5 Things That Matter</h2>" +
        "<ol>" + (E.fiveThings || []).map(function (t) {
          var s = story(t.id) || {};
          return "<li><div><span class=\"lbl\">" + esc(t.label) + "</span>" +
            '<h4><a href="' + articleHref(t.id) + '">' + esc(s.headline || t.id) + "</a></h4>" +
            '<p class="note">' + esc(t.note) + "</p></div></li>";
        }).join("") + "</ol>" +
      "</div>"
    );
  }

  function renderAgentWatch(role) {
    var items = E.agentWatch || [];
    return (
      '<section id="agents"><div id="agentwatch" class="sec-head"><h2>Agent Watch</h2>' +
        '<span class="sub">Can I build with this? Is it production-ready? What’s the moat?</span></div>' +
      '<div class="tiles">' + items.map(function (a) {
        return '<div class="tile">' +
          '<span class="track">' + esc(a.track) + "</span>" +
          "<h4>" + (a.storyId ? '<a href="' + articleHref(a.storyId) + '">' + esc(a.name) + "</a>" : esc(a.name)) + "</h4>" +
          '<div class="kv">' +
            '<div><span class="k">Can I build with it?</span><span>' + esc(a.buildable) + "</span></div>" +
            '<div><span class="k">Production-ready?</span><span>' + esc(a.production) + "</span></div>" +
            '<div><span class="k">The moat</span><span>' + esc(a.moat) + "</span></div>" +
            '<div><span class="k">Interview demo</span><span>' + esc(a.demo) + "</span></div>" +
          "</div>" +
        "</div>";
      }).join("") + "</div></section>"
    );
  }

  function renderBuilderRadar() {
    var items = E.builderRadar || [];
    return (
      '<section id="tools"><div id="radar" class="sec-head"><h2>Builder Radar</h2><span class="sub">Trending repos · frameworks · MCP servers · tools</span></div>' +
      '<div class="tiles">' + items.map(function (r) {
        return '<div class="tile">' +
          '<span class="stars">▲ ' + esc(r.stars) + "</span>" +
          "<h4>" + esc(r.repo) + "</h4>" +
          '<div class="kv">' +
            '<div><span class="k">What it does</span><span>' + esc(r.what) + "</span></div>" +
            '<div><span class="k">Why builders care</span><span>' + esc(r.why) + "</span></div>" +
            '<div><span class="k">Comparable to</span><span>' + esc(r.compare) + "</span></div>" +
          "</div>" +
        "</div>";
      }).join("") + "</div></section>"
    );
  }

  function renderBenchmark() {
    var items = E.benchmarkWatch || [];
    return (
      '<section id="benchmarks"><div id="benchmark" class="sec-head"><h2>Benchmark Watch</h2>' +
        '<span class="sub">Score moved — but does it matter in real work?</span></div>' +
      '<div class="tiles">' + items.map(function (b) {
        return '<div class="tile">' +
          "<h4>" + (b.storyId ? '<a href="' + articleHref(b.storyId) + '">' + esc(b.name) + "</a>" : esc(b.name)) + "</h4>" +
          '<div class="kv">' +
            '<div><span class="k">What changed</span><span>' + esc(b.change) + "</span></div>" +
            '<div><span class="k">Independently verified?</span><span>' + esc(b.verified) + "</span></div>" +
            '<div><span class="k">Saturated?</span><span>' + esc(b.saturated) + "</span></div>" +
            '<div><span class="k">So what</span><span>' + esc(b.takeaway) + "</span></div>" +
          "</div>" +
        "</div>";
      }).join("") + "</div></section>"
    );
  }

  function renderMap() {
    var m = E.companyMap || {};
    return (
      '<section id="infra"><div id="map" class="sec-head"><h2>AI Company Map</h2><span class="sub">A living map of the landscape</span></div>' +
      '<div class="map">' + Object.keys(m).map(function (cat) {
        return '<div class="cat"><h4>' + esc(cat) + "</h4><ul>" +
          m[cat].map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>";
      }).join("") + "</div></section>"
    );
  }

  function renderTimeline() {
    var keys = Object.keys(E.timelines || {});
    if (!keys.length) return "";
    var k = keys[0], pts = E.timelines[k];
    return (
      '<div class="grid two-col"><div>' +
        '<div class="sec-head"><h2>Timeline</h2><span class="sub">' + esc(k) + "</span></div>" +
        '<div class="timeline">' + pts.map(function (p) {
          return '<div class="pt"><span class="yr">' + esc(p.year) + "</span><p>" + esc(p.text) + "</p></div>";
        }).join("") + "</div></div>" +
        '<div class="col-divider"><div class="sec-head" style="margin-top:0"><h2>Weekly Deep Dive</h2><span class="sub">The Sunday read</span></div>' +
          deepDiveTeaser() + "</div>" +
      "</div>"
    );
  }

  function deepDiveTeaser() {
    var s = story(E.weeklyDeepDive);
    if (!s) return "";
    return (
      '<div class="card">' +
        '<div class="meta"><span class="kicker">' + esc(s.kicker) + "</span>" +
          '<span class="dot">·</span><span class="readtime">' + s.readTime + " min read</span></div>" +
        '<h3 style="font-size:24px"><a href="' + articleHref(s.id) + '">' + esc(s.headline) + "</a></h3>" +
        '<p class="summary">' + esc(s.takeaway) + "</p>" +
        '<a class="btn ghost" href="' + articleHref(s.id) + '">Read the deep dive →</a>' +
      "</div>"
    );
  }

  function renderCompare() {
    var items = E.compares || [];
    return (
      '<section id="weeklybrief"><div id="compare" class="sec-head"><h2>Compare Mode</h2><span class="sub">Tools &amp; models, side by side</span></div>' +
      items.map(function (c) {
        return '<div class="compare"><h4>' + esc(c.title) + "</h4><table><thead><tr><th></th>" +
          c.columns.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
          "</tr></thead><tbody>" +
          c.rows.map(function (row) {
            return "<tr><th>" + esc(row.dim) + "</th>" +
              row.vals.map(function (v) { return "<td>" + esc(v) + "</td>"; }).join("") + "</tr>";
          }).join("") +
          "</tbody></table></div>";
      }).join("") + "</section>"
    );
  }

  function renderSignup() {
    return (
      '<div class="signup">' +
        "<h2>Get the brief in your inbox</h2>" +
        "<p>AI is moving too fast for feeds. One daily edition for people who build, lead, and invest in AI systems — signal over hype.</p>" +
        '<form id="signupForm"><input id="email" type="email" placeholder="you@company.com" required>' +
          "<button type=\"submit\">Subscribe</button></form>" +
        '<div class="ok" id="signupOk"></div>' +
      "</div>"
    );
  }

  function wireSignup() {
    var form = el("signupForm");
    if (!form) return;
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = (el("email").value || "").trim();
      var ok = el("signupOk");
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { ok.textContent = "Enter a valid email."; return; }
      try {
        var list = JSON.parse(localStorage.getItem("aibrief.subs") || "[]");
        if (list.indexOf(email) === -1) list.push(email);
        localStorage.setItem("aibrief.subs", JSON.stringify(list));
      } catch (e) {}
      ok.textContent = "Subscribed (saved locally — wire to a real list in production). Welcome aboard.";
      el("email").value = "";
    });
  }

  function renderHome() {
    var role = getRole();
    var main = el("main");
    main.innerHTML =
      renderLead(role) +
      renderFiveBox() +
      renderTopAndMarket(role) +
      '<hr style="border:0;border-top:1px solid var(--rule);margin:30px 0">' +
      renderBuildersLeaders(role) +
      renderAgentWatch(role) +
      renderBuilderRadar() +
      renderBenchmark() +
      renderMap() +
      renderTimeline() +
      renderCompare() +
      renderSignup();
    wireSignup();
  }

  // ── ARTICLE PAGE ───────────────────────────────────────────────────────
  function signalGrid(s) {
    if (!s) return "";
    var cells = [
      ["Signal", s.signal, lvlClass(s.signal)],
      ["Novelty", s.novelty, lvlClass(s.novelty)],
      ["Practical value", s.practical, lvlClass(s.practical)],
      ["Hype risk", s.hype, "hype-" + lvlClass(s.hype)],
    ];
    return '<div class="signal-grid">' + cells.map(function (c) {
      return '<div class="s ' + c[2] + '"><div class="k">' + c[0] + '</div><div class="v">' + esc(c[1]) + "</div></div>";
    }).join("") + "</div>";
  }

  function renderArticle() {
    var id = qs("id");
    var s = story(id);
    var main = el("main");
    if (!s) {
      main.innerHTML = '<div class="article"><a class="back" href="index.html">← Back to today’s edition</a>' +
        "<h1>Story not found</h1><p>That brief isn’t in today’s edition. <a href=\"index.html\">Return to the front page →</a></p></div>";
      return;
    }
    document.title = s.headline + " · " + (E.masthead || "The AI Brief");
    var role = getRole();

    function sec(label, body, cls) {
      return '<div class="article-sec ' + (cls || "") + '"><h2>' + esc(label) + "</h2><p>" + esc(body) + "</p></div>";
    }

    main.innerHTML =
      '<article class="article">' +
        '<a class="back" href="index.html">← Today’s Edition</a>' +
        '<div class="topmeta" style="margin-top:14px"><span class="kicker">' + esc(s.kicker) + "</span>" +
          '<span class="dot">·</span><span class="readtime">' + s.readTime + " min read</span></div>" +
        "<h1>" + esc(s.headline) + "</h1>" +
        '<p class="takeaway">' + esc(s.takeaway) + "</p>" +
        signalGrid(s.signal) +
        '<div class="article-sec"><h2>Who should care</h2><div class="whocare">' +
          (s.whoShouldCare || []).map(function (w) { return '<span class="who">' + esc(w) + "</span>"; }).join("") +
        "</div></div>" +
        sec("What happened", s.whatHappened) +
        sec("What changed", s.whatChanged) +
        sec("Why it matters", s.whyItMatters) +
        sec("Skeptical read", s.skepticalRead, "skeptic") +
        personaBox(s, role) +
        sourcesBlock(s) +
        relatedBlock(s) +
        '<p class="notice">Sample edition — this brief is illustrative content demonstrating The AI Brief’s format, not live reporting.</p>' +
      "</article>";

    var sel = el("articleRole");
    if (sel) sel.addEventListener("change", function () {
      setRole(sel.value);
      var box = el("personaText");
      if (box) box.textContent = (s.personas && s.personas[sel.value]) || "—";
    });
  }

  function personaBox(s, role) {
    var text = (s.personas && s.personas[role]) || "—";
    return (
      '<div class="persona-box">' +
        '<div class="head"><h2>Why this matters to you</h2>' +
          '<select id="articleRole" aria-label="Choose your role">' +
            (E.roles || []).map(function (r) {
              return '<option value="' + esc(r) + '"' + (r === role ? " selected" : "") + ">" + esc(r) + "</option>";
            }).join("") +
          "</select></div>" +
        '<p id="personaText">' + esc(text) + "</p>" +
      "</div>"
    );
  }

  function sourcesBlock(s) {
    if (!s.sources || !s.sources.length) return "";
    return '<div class="article-sec"><h2>Sources</h2><ul class="src-list">' +
      s.sources.map(function (x) { return '<li><a href="' + esc(x.url) + '">' + esc(x.title) + "</a></li>"; }).join("") +
      "</ul></div>";
  }

  function relatedBlock(s) {
    if (!s.related || !s.related.length) return "";
    return '<div class="article-sec"><h2>Related</h2><ul class="rel-list">' +
      s.related.map(function (x) {
        var href = x.id ? articleHref(x.id) : (x.href || "#");
        return '<li><a href="' + esc(href) + '">' + esc(x.label) + "</a></li>";
      }).join("") +
      "</ul></div>";
  }

  // ── boot ────────────────────────────────────────────────────────────────
  function boot() {
    renderChrome();
    var page = document.body.getAttribute("data-page");
    if (page === "article") {
      window.__rerender = renderArticle;
      renderArticle();
    } else {
      window.__rerender = renderHome;
      renderHome();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
