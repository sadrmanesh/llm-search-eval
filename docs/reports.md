# Reports and dashboard

`llm-search-eval run --output-dir DIR` writes:

| File | Contents |
| :--- | :--- |
| `report.md` | Summary, confidence intervals, comparison with p-values and delta intervals, per-language and per-stratum results, pairwise preference, label coverage, judges and agreement, cost. |
| `report.json` | Everything in the Markdown report plus per-query values, rankings, labels, and product summaries. |
| `report.html` | Interactive dashboard in a single file. |
| `cost.json` | Token usage, cost, and budget state (when a judge is used). |
| `judgments.jsonl` | Every judge label with reason, source, panel votes, and the gold label for calibration pairs. |

Choose formats with `--format md,json,html` (all three by default).

## The HTML dashboard

The dashboard is one HTML file with the styles, script, and data inlined. It
makes no network requests, so it works offline, as a CI artifact, or as an
email attachment. It follows the system light or dark theme.

It contains:

- overview cards: queries, products, sample size, label sources, tokens, and cost;
- the metric table with confidence intervals, and a bar chart for any metric
  with interval whiskers;
- system comparison against the baseline with delta intervals and a per-query
  delta chart;
- primary metric by query language and by the stratification field;
- pairwise preference: win, tie and loss counts with win rate intervals, a
  stacked bar per pair, and every query's verdict and reason, linked to the
  query drilldown;
- judge label distribution, inter-judge agreement, and judge vs gold agreement;
- cost per model;
- a searchable query list with a drilldown that shows every system's ranking
  side by side, with grades, label sources, reasons, and panel votes.

The [sample dashboard](https://sadrmanesh.github.io/llm-search-eval/demo/report.html) is
generated from the example dataset. Its source file is
[`examples/electronics/sample-report/report.html`](https://github.com/sadrmanesh/llm-search-eval/blob/main/examples/electronics/sample-report/report.html).

## Posting to a pull request

`llm-search-eval comment` posts `gate.md` and `report.md` as one pull request
comment and updates it on later runs. The GitHub Action does this by default;
see [Pull request comments](pr-comments.md).

## Re-rendering a saved report

```bash
llm-search-eval report reports/report.json --format md,html -o rendered/
```

This is handy when you keep only `report.json` as a CI artifact, or after
upgrading the tool to get a newer dashboard. Reports produced with
`EvaluationConfig(include_details=False)` still render, without the query
drilldown.

From Python:

```python
from llm_search_eval import render_html

html = render_html(report)  # an EvaluationReport or a loaded report.json dict
```
