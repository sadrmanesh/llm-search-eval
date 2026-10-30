(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("report-data").textContent);
  var SVG = "http://www.w3.org/2000/svg";
  var cfg = DATA.config;
  var primary = cfg.primary_metric;
  var systems = DATA.systems;
  var names = systems.map(function (s) { return s.name; });
  var details = DATA.details || null;

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "text") node.textContent = attrs[key];
        else if (key === "class") node.className = attrs[key];
        else node.setAttribute(key, attrs[key]);
      });
    }
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }
  function fmt(v, d) { return v === null || v === undefined ? "n/a" : Number(v).toFixed(d === undefined ? 4 : d); }
  function signed(v) { return v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + Number(v).toFixed(4); }
  function pct(v) { return v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%"; }
  function money(v) { return v === null || v === undefined ? "unknown" : "$" + Number(v).toFixed(4); }
  function td(text, cls) { return el("td", { text: text, class: cls || "" }); }
  function th(text, cls) { return el("th", { text: text, class: cls || "" }); }
  function table(headers, rows, numeric) {
    var head = el("tr", null, headers.map(function (h, i) { return th(h, i && numeric !== false ? "num" : ""); }));
    var body = el("tbody", null, rows);
    return el("table", null, [el("thead", null, [head]), body]);
  }
  function option(value, label, selected) {
    var o = el("option", { value: value, text: label || value });
    if (selected) o.selected = true;
    return o;
  }

  function barChart(container, items, opts) {
    opts = opts || {};
    container.textContent = "";
    var width = Math.max(320, container.clientWidth || 640);
    var rowH = 22, labelW = opts.labelWidth || 140, valueW = 70;
    var height = items.length * rowH + 10;
    var chart = svg("svg", { width: width, height: height, role: "img", "aria-label": opts.label || "chart" });
    var plotW = width - labelW - valueW;
    var values = items.map(function (it) { return it.value || 0; });
    var maxAbs = Math.max.apply(null, values.map(Math.abs).concat([opts.max || 0, 1e-9]));
    var signedMode = values.some(function (v) { return v < 0; });
    var zero = labelW + (signedMode ? plotW / 2 : 0);
    var scale = (signedMode ? plotW / 2 : plotW) / maxAbs;
    items.forEach(function (it, i) {
      var y = 5 + i * rowH;
      var v = it.value || 0;
      var label = svg("text", { x: labelW - 6, y: y + 14, "text-anchor": "end" });
      label.textContent = it.label.length > 22 ? it.label.slice(0, 21) + "\u2026" : it.label;
      var title = svg("title", {});
      title.textContent = it.label + ": " + (it.value === null ? "n/a" : fmt(it.value));
      var w = Math.abs(v) * scale;
      var bar = svg("rect", {
        x: v >= 0 ? zero : zero - w, y: y + 3, width: Math.max(w, it.value === null ? 0 : 1), height: rowH - 8,
        class: "bar" + (signedMode || opts.colorSign ? (v >= 0 ? " pos" : " neg") : ""), rx: 2
      });
      bar.appendChild(title);
      var text = svg("text", { x: labelW + plotW + 6, y: y + 14 });
      text.textContent = it.value === null ? "n/a" : (signedMode ? signed(v) : fmt(v));
      chart.appendChild(label); chart.appendChild(bar); chart.appendChild(text);
    });
    if (signedMode) chart.appendChild(svg("line", { x1: zero, x2: zero, y1: 0, y2: height, class: "axis" }));
    container.appendChild(chart);
  }

  function renderOverview() {
    var ds = DATA.dataset, labels = DATA.labels, cost = DATA.cost || {};
    var cards = [
      ["Queries", ds.queries], ["Products", ds.products], ["Gold labels", ds.gold_labels],
      ["Judged", labels.judged], ["From cache", labels.cached], ["Unlabeled", labels.unlabeled],
      ["Tokens", cost.total_tokens === undefined ? "n/a" : cost.total_tokens.toLocaleString()],
      ["Cost", cost.requests ? money(cost.cost_usd) : "$0"]
    ];
    var box = $("overview-cards");
    cards.forEach(function (c) {
      box.appendChild(el("div", { class: "card" }, [el("div", { class: "k", text: c[0] }), el("div", { class: "v", text: String(c[1]) })]));
    });
    $("meta").textContent = "Judge: " + (labels.judge || "none") + " \u00b7 depth " + cfg.depth +
      " \u00b7 relevant when grade \u2265 " + cfg.threshold + " \u00b7 baseline " + cfg.baseline +
      " \u00b7 generated " + DATA.generated_at + " by llm-search-eval " + DATA.tool.version;
  }

  function renderSummary() {
    var metrics = cfg.metrics;
    var best = {};
    metrics.forEach(function (m) {
      var vals = systems.map(function (s) { return s.metrics[m].mean; }).filter(function (v) { return v !== null; });
      best[m] = vals.length ? Math.max.apply(null, vals) : null;
    });
    var rows = systems.map(function (s) {
      return el("tr", null, [td(s.name)].concat(metrics.map(function (m) {
        var v = s.metrics[m].mean;
        var isBest = v !== null && systems.length > 1 && Math.abs(v - best[m]) < 1e-12;
        return td(fmt(v), "num" + (isBest ? " best" : ""));
      })));
    });
    $("summary-table").appendChild(table(["System"].concat(metrics), rows));
    var select = $("metric-select");
    metrics.forEach(function (m) { select.appendChild(option(m, m, m === primary)); });
    function draw() {
      var m = select.value;
      barChart($("metric-chart"), systems.map(function (s) { return { label: s.name, value: s.metrics[m].mean }; }), { max: 1, label: m });
    }
    select.addEventListener("change", draw);
    draw();
  }

  function renderComparison() {
    var comp = DATA.comparison;
    var section = $("comparison");
    if (systems.length < 2) { section.hidden = true; return; }
    var rows = comp.significance.map(function (t) {
      var d = comp.deltas.filter(function (x) { return x.system === t.system && x.metric === t.metric; })[0] || {};
      var cls = d.delta > 0 ? "num pos" : d.delta < 0 ? "num neg" : "num";
      return el("tr", null, [td(t.system), td(signed(d.delta), cls), td(pct(d.relative), cls),
        td(t.wins + " / " + t.ties + " / " + t.losses, "num"),
        td(t.p_value === null ? "n/a" : t.p_value.toFixed(4) + (t.p_value < 0.05 ? " *" : ""), "num")]);
    });
    $("comparison-table").appendChild(table(["System", "\u0394 " + comp.primary_metric, "Relative", "Win / tie / loss", "p-value"], rows));
    var select = $("compare-select");
    names.filter(function (n) { return n !== comp.baseline; }).forEach(function (n, i) { select.appendChild(option(n, n, i === 0)); });
    function draw() {
      var a = systems.filter(function (s) { return s.name === select.value; })[0];
      var b = systems.filter(function (s) { return s.name === comp.baseline; })[0];
      var items = [];
      Object.keys(b.per_query).forEach(function (q) {
        var x = a.per_query[q][primary], y = b.per_query[q][primary];
        if (x === null || y === null || Math.abs(x - y) < 1e-12) return;
        var text = details && details.queries[q] ? q + " " + details.queries[q].text : q;
        items.push({ label: text, value: x - y });
      });
      items.sort(function (p, q) { return q.value - p.value; });
      $("delta-note").textContent = items.length ? "Per-query " + primary + " change of " + select.value + " versus " + comp.baseline + ", queries with no change omitted." : "No query changed between " + select.value + " and " + comp.baseline + ".";
      barChart($("delta-chart"), items, { labelWidth: 220, label: "per-query delta" });
    }
    select.addEventListener("change", draw);
    draw();
  }

  function renderLanguages() {
    var by = DATA.by_language;
    var langs = {};
    Object.keys(by).forEach(function (s) { Object.keys(by[s]).forEach(function (l) { langs[l] = true; }); });
    langs = Object.keys(langs).sort();
    if (langs.length < 2) { $("languages").hidden = true; return; }
    var rows = Object.keys(by).map(function (s) {
      return el("tr", null, [td(s)].concat(langs.map(function (l) { return td(fmt(by[s][l].mean) + " (n=" + by[s][l].n + ")", "num"); })));
    });
    $("language-table").appendChild(table(["System"].concat(langs), rows));
  }

  function renderJudging() {
    var j = DATA.judging;
    if (!j) { $("judging").hidden = true; return; }
    var dist = j.label_distribution;
    barChart($("label-chart"), ["3", "2", "1", "0"].map(function (g) { return { label: "grade " + g, value: dist[g] || 0 }; }), { label: "label distribution" });
    var info = $("judging-info");
    info.appendChild(el("p", { text: "Judge: " + j.judge + ". " + j.pairs + " judged pair(s)." }));
    if (j.agreement) {
      var a = j.agreement;
      var k = a.krippendorff_alpha;
      info.appendChild(table(["Statistic", "Value"], [
        el("tr", null, [td("Fleiss' kappa"), td(fmt(a.fleiss_kappa, 3), "num")]),
        el("tr", null, [td("Krippendorff's alpha (ordinal)"), td(fmt(k.ordinal, 3), "num")]),
        el("tr", null, [td("Krippendorff's alpha (nominal)"), td(fmt(k.nominal, 3), "num")]),
        el("tr", null, [td("Unanimous items"), td(a.unanimous === null ? "n/a" : (a.unanimous * 100).toFixed(1) + "%", "num")])
      ]));
      info.appendChild(el("h3", { text: "Pairwise agreement" }));
      info.appendChild(table(["Judges", "n", "Agreement", "Cohen's kappa", "Weighted kappa"], a.pairwise.map(function (p) {
        return el("tr", null, [td(p.a + " / " + p.b), td(String(p.n), "num"), td(p.percent_agreement === null ? "n/a" : (p.percent_agreement * 100).toFixed(1) + "%", "num"), td(fmt(p.cohen_kappa, 3), "num"), td(fmt(p.weighted_kappa, 3), "num")]);
      })));
    }
    var g = j.gold_agreement;
    if (g) {
      var box = $("gold-info");
      box.appendChild(el("h3", { text: "Agreement with gold labels" }));
      var raters = [[j.judge, g.judge]].concat(Object.keys(g.members).map(function (n) { return [n, g.members[n]]; }));
      box.appendChild(table(["Rater", "n", "Exact", "Within one", "Binary", "Weighted kappa", "Bias"], raters.map(function (r) {
        var s = r[1];
        return el("tr", null, [td(r[0]), td(String(s.n), "num"), td((s.exact * 100).toFixed(1) + "%", "num"), td((s.within_one * 100).toFixed(1) + "%", "num"), td((s.binary_agreement * 100).toFixed(1) + "%", "num"), td(fmt(s.weighted_kappa, 3), "num"), td(signed(s.mean_bias), "num")]);
      })));
      var m = g.judge.confusion;
      box.appendChild(el("p", { class: "note", text: "Confusion matrix: rows are gold grades, columns are judge grades." }));
      box.appendChild(table(["gold \\ judge"].concat(m.categories.map(String)), m.matrix.map(function (row, i) {
        return el("tr", null, [td(String(m.categories[i]))].concat(row.map(function (c) { return td(String(c), "num"); })));
      })));
    }
  }

  function renderCost() {
    var c = DATA.cost;
    if (!c || (!c.requests && !c.cache_hits && !c.budget.skipped_pairs)) { $("cost").hidden = true; return; }
    var rows = Object.keys(c.models).map(function (name) {
      var m = c.models[name];
      return el("tr", null, [td(name), td(String(m.requests), "num"), td(m.prompt_tokens.toLocaleString(), "num"), td(m.completion_tokens.toLocaleString(), "num"), td(money(m.cost_usd), "num")]);
    });
    rows.push(el("tr", null, [td("Total"), td(String(c.requests), "num"), td(c.prompt_tokens.toLocaleString(), "num"), td(c.completion_tokens.toLocaleString(), "num"), td(money(c.cost_usd), "num best")]));
    $("cost-table").appendChild(table(["Model", "Requests", "Input tokens", "Output tokens", "Cost"], rows));
    var notes = [c.cache_hits + " judgment(s) served from cache at no cost."];
    if (c.unpriced_models.length) notes.push("No price configured for: " + c.unpriced_models.join(", ") + ".");
    if (c.budget.exhausted) notes.push("Budget reached (" + c.budget.reason + "); " + c.budget.skipped_pairs + " pair(s) were not judged.");
    $("cost-note").textContent = notes.join(" ");
  }

  function renderQueries() {
    if (!details) { $("queries").hidden = true; return; }
    var qids = Object.keys(details.queries);
    var body = el("tbody");
    var rows = {};
    qids.forEach(function (q) {
      var info = details.queries[q];
      var cells = [td(q), el("td", { dir: "auto", text: info.text }), td(info.lang)];
      systems.forEach(function (s) { cells.push(td(fmt(s.per_query[q][primary], 3), "num")); });
      var tr = el("tr", { "data-q": q }, cells);
      tr.addEventListener("click", function () { showQuery(q); });
      rows[q] = tr;
      body.appendChild(tr);
    });
    var head = el("tr", null, [th("Id"), th("Query"), th("Lang")].concat(names.map(function (n) { return th(n + " " + primary, "num"); })));
    $("query-table").appendChild(el("table", { class: "clickable" }, [el("thead", null, [head]), body]));
    $("query-filter").addEventListener("input", function (e) {
      var needle = e.target.value.toLowerCase();
      qids.forEach(function (q) {
        var hay = (q + " " + details.queries[q].text).toLowerCase();
        rows[q].hidden = needle && hay.indexOf(needle) < 0;
      });
    });
    function showQuery(q) {
      Object.keys(rows).forEach(function (k) { rows[k].className = k === q ? "selected" : ""; });
      var box = $("query-detail");
      box.textContent = "";
      var info = details.queries[q];
      box.appendChild(el("h3", { dir: "auto", text: q + ": " + info.text }));
      var labels = details.labels[q] || {};
      var lists = el("div", { class: "lists" });
      systems.forEach(function (s) {
        var ranked = details.rankings[s.name][q] || [];
        var ol = el("ol");
        ranked.forEach(function (pid) {
          var l = labels[pid];
          var p = details.products[pid];
          var grade = l ? l.grade : null;
          var badge = el("span", { class: "badge " + (grade === null ? "gx" : "g" + grade), text: grade === null ? "?" : String(grade) });
          var title = el("span", { dir: "auto", text: p ? p.title : pid + " (not in catalog)" });
          var src = el("span", { class: "src", text: " " + pid + (l ? " \u00b7 " + l.source : " \u00b7 unlabeled") });
          var parts = [badge, title, src];
          if (l && l.reason) parts.push(el("span", { class: "reason", dir: "auto", text: l.reason }));
          if (l && l.votes) parts.push(el("span", { class: "reason", text: "votes: " + Object.keys(l.votes).map(function (k) { return k + "=" + (l.votes[k] === null ? "x" : l.votes[k]); }).join(", ") }));
          ol.appendChild(el("li", null, parts));
        });
        if (!ranked.length) ol.appendChild(el("li", { class: "muted", text: "no results" }));
        var metrics = cfg.metrics.map(function (m) { return m + " " + fmt(s.per_query[q][m], 3); }).join(" \u00b7 ");
        lists.appendChild(el("div", { class: "list" }, [el("h3", { text: s.name }), el("p", { class: "note", text: metrics }), ol]));
      });
      box.appendChild(lists);
      var missing = Object.keys(labels).filter(function (pid) {
        return labels[pid].grade >= cfg.threshold && !systems.some(function (s) { return (details.rankings[s.name][q] || []).indexOf(pid) >= 0; });
      });
      if (missing.length) box.appendChild(el("p", { class: "note", text: "Relevant products no system returned in the top " + cfg.depth + ": " + missing.join(", ") }));
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (qids.length) showQuery(qids[0]);
  }

  renderOverview();
  renderSummary();
  renderComparison();
  renderLanguages();
  renderJudging();
  renderCost();
  renderQueries();
})();
