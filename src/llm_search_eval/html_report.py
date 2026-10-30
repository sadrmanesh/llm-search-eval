"""Self-contained interactive HTML dashboard for an evaluation report.

The output is one file with inline CSS, JavaScript, and data. It needs no
network access, so it can be attached to CI runs, emailed, or opened offline.
"""

from __future__ import annotations

import html
import json
from importlib import resources
from pathlib import Path
from typing import Any

from llm_search_eval.evaluate import EvaluationReport

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="llm-search-eval {version}">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta" id="meta"></div>
</header>
<nav>
  <a href="#overview">Overview</a>
  <a href="#summary">Metrics</a>
  <a href="#comparison">Comparison</a>
  <a href="#languages">Languages</a>
  <a href="#judging">Judges</a>
  <a href="#cost">Cost</a>
  <a href="#queries">Queries</a>
</nav>
<main>
  <section id="overview"><h2>Overview</h2><div class="cards" id="overview-cards"></div></section>
  <section id="summary">
    <h2>Metrics</h2>
    <div id="summary-table"></div>
    <div class="row" style="margin-top:14px"><label for="metric-select">Chart</label>
      <select id="metric-select"></select></div>
    <div id="metric-chart"></div>
  </section>
  <section id="comparison">
    <h2>System comparison</h2>
    <div id="comparison-table"></div>
    <p class="note">p-values come from a two-sided paired randomization test;
      * marks p &lt; 0.05.</p>
    <div class="row">
      <label for="compare-select">System</label><select id="compare-select"></select>
    </div>
    <p class="note" id="delta-note"></p>
    <div id="delta-chart"></div>
  </section>
  <section id="languages">
    <h2>Primary metric by query language</h2><div id="language-table"></div>
  </section>
  <section id="judging">
    <h2>Judges</h2>
    <div class="split">
      <div><h3>Label distribution</h3><div id="label-chart"></div></div>
      <div id="judging-info"></div>
    </div>
    <div id="gold-info"></div>
  </section>
  <section id="cost">
    <h2>Cost and usage</h2><div id="cost-table"></div><p class="note" id="cost-note"></p>
  </section>
  <section id="queries">
    <h2>Queries</h2>
    <div class="row"><input type="search" id="query-filter" placeholder="Filter queries"></div>
    <div id="query-table"></div>
    <div id="query-detail"></div>
  </section>
</main>
<footer>Produced by llm-search-eval {version}.</footer>
<script type="application/json" id="report-data">{data}</script>
<script>{js}</script>
</body>
</html>
"""


def _asset(name: str) -> str:
    return (resources.files("llm_search_eval") / "assets" / name).read_text(encoding="utf-8")


def _embed_json(data: Any) -> str:
    """Serialize for a ``<script>`` block without allowing it to close the tag."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(report: EvaluationReport | dict[str, Any]) -> str:
    """Render the dashboard. Per-query drilldown needs the report's ``details``."""
    data = report.to_dict() if isinstance(report, EvaluationReport) else report
    version = html.escape(str(data.get("tool", {}).get("version", "")))
    return _TEMPLATE.format(
        title=html.escape(str(data.get("title", "Search evaluation report"))),
        version=version,
        css=_asset("dashboard.css"),
        js=_asset("dashboard.js"),
        data=_embed_json(data),
    )


def write_html(report: EvaluationReport | dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path
