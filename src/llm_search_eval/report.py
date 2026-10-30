"""Render evaluation reports as Markdown and JSON."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from llm_search_eval.evaluate import EvaluationReport
from llm_search_eval.html_report import render_html


def _fmt(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _signed(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1%}"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]], align: str = "") -> list[str]:
    align = align or "l" + "r" * (len(headers) - 1)
    sep = ["---:" if a == "r" else ":---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _ci(entry: dict[str, Any], digits: int = 4, signed: bool = False) -> str:
    low, high = entry.get("ci_low"), entry.get("ci_high")
    if low is None or high is None:
        return "n/a"
    fmt = _signed if signed else _fmt
    return f"[{fmt(low, digits)}, {fmt(high, digits)}]"


def _confidence_label(cfg: dict[str, Any]) -> str:
    return f"{round(float(cfg.get('confidence', 0.95)) * 100):g}% CI"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def summary_table(data: dict[str, Any]) -> list[str]:
    metrics = data["config"]["metrics"]
    systems = data["systems"]
    best = {}
    for m in metrics:
        values = [s["metrics"][m]["mean"] for s in systems if s["metrics"][m]["mean"] is not None]
        best[m] = max(values) if values else None
    rows = []
    for s in systems:
        cells = [f"`{_escape(s['name'])}`"]
        for m in metrics:
            v = s["metrics"][m]["mean"]
            text = _fmt(v)
            if v is not None and len(systems) > 1 and abs(v - best[m]) < 1e-12:
                text = f"**{text}**"
            cells.append(text)
        rows.append(cells)
    return _table(["System", *metrics], rows)


def render_markdown(report: EvaluationReport | dict[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, EvaluationReport) else report
    cfg = data["config"]
    ds = data["dataset"]
    labels = data["labels"]
    comp = data["comparison"]
    primary = cfg["primary_metric"]

    out: list[str] = [f"# {data['title']}", ""]
    langs = ", ".join(f"{k}: {v}" for k, v in ds["languages"].items())
    out += [
        f"- **Queries:** {ds['queries']} ({langs})",
        f"- **Products:** {ds['products']}",
        f"- **Gold labels:** {ds['gold_labels']}",
        f"- **Judge:** {labels['judge'] or 'none (unlabeled results count as not relevant)'}",
        f"- **Depth:** top {cfg['depth']}, relevant when grade >= {cfg['threshold']}, "
        f"{cfg['gain']} gain",
        f"- **Primary metric:** `{primary}`, baseline `{cfg['baseline']}`",
        "",
        "## Summary",
        "",
        *summary_table(data),
        "",
    ]
    if len(comp["ranking"]) > 1:
        leader = comp["ranking"][0]
        out += [f"Best system by `{primary}`: **`{_escape(leader)}`**.", ""]
    with_ci = cfg.get("bootstrap") and any(
        "ci_low" in s["metrics"][primary] for s in data["systems"]
    )
    if with_ci:
        label = _confidence_label(cfg)
        out += [f"## Confidence intervals for `{primary}`", ""]
        out += _table(
            ["System", "Mean", label, "Queries"],
            (
                [
                    f"`{_escape(s['name'])}`",
                    _fmt(s["metrics"][primary]["mean"]),
                    _ci(s["metrics"][primary]),
                    str(s["metrics"][primary]["n"]),
                ]
                for s in data["systems"]
            ),
        )
        out += [
            "",
            f"Percentile bootstrap over queries ({cfg['bootstrap']} resamples, seed "
            f"{cfg['seed']}). Narrow intervals need more queries, not more judgments.",
            "",
        ]

    if comp["significance"]:
        out += [f"## Comparison against `{_escape(cfg['baseline'])}`", ""]
        rows = []
        for t in comp["significance"]:
            d = next(
                x for x in comp["deltas"] if x["system"] == t["system"] and x["metric"] == primary
            )
            p = t["p_value"]
            flag = "" if p is None else (" (significant)" if p < 0.05 else "")
            row = [f"`{_escape(t['system'])}`", _signed(d["delta"])]
            if with_ci:
                row.append(_ci(d, signed=True))
            row += [
                _pct(d["relative"]),
                f"{t['wins']} / {t['ties']} / {t['losses']}",
                ("n/a" if p is None else f"{p:.4f}") + flag,
            ]
            rows.append(row)
        headers = ["System", f"Δ {primary}"]
        if with_ci:
            headers.append(f"Δ {_confidence_label(cfg)}")
        headers += ["Relative", "Win / tie / loss", "p-value"]
        out += _table(headers, rows)
        out += [
            "",
            "p-values come from a two-sided paired randomization test over per-query "
            f"`{primary}` ({cfg['permutations']} permutations, seed {cfg['seed']}).",
            *(
                [
                    "An interval for Δ that excludes zero agrees with a significant p-value "
                    "in almost every case; when they disagree, the effect is borderline."
                ]
                if with_ci
                else []
            ),
            "",
            "### All metric deltas",
            "",
        ]
        out += _table(
            ["System", "Metric", "Baseline", "System value", "Δ"]
            + ([_confidence_label(cfg)] if with_ci else [])
            + ["Relative"],
            (
                [
                    f"`{_escape(d['system'])}`",
                    d["metric"],
                    _fmt(d["baseline"]),
                    _fmt(d["value"]),
                    _signed(d["delta"]),
                    *([_ci(d, signed=True)] if with_ci else []),
                    _pct(d["relative"]),
                ]
                for d in comp["deltas"]
            ),
            align="llrrr" + ("r" if with_ci else "") + "r",
        )
        out.append("")

    by_lang = data["by_language"]
    lang_keys = sorted({lang for v in by_lang.values() for lang in v})
    if len(lang_keys) > 1:
        out += [f"## `{primary}` by query language", ""]
        out += _table(
            ["System", *lang_keys],
            (
                [f"`{_escape(name)}`"]
                + [f"{_fmt(v[lang]['mean'])} (n={v[lang]['n']})" for lang in lang_keys]
                for name, v in by_lang.items()
            ),
        )
        out.append("")

    out += ["## Label coverage", ""]
    out += _table(
        ["System", "Queries answered", f"Labeled in top {cfg['depth']}", "Unknown products"],
        (
            [
                f"`{_escape(s['name'])}`",
                f"{s['coverage']['queries_answered']}/{s['coverage']['queries_total']}",
                "n/a"
                if s["coverage"]["labeled_at_depth"] is None
                else f"{s['coverage']['labeled_at_depth']:.1%}",
                str(s["coverage"]["unknown_products"]),
            ]
            for s in data["systems"]
        ),
    )
    out += [
        "",
        f"Gold labels used: {labels['gold_used']}, new judgments: {labels['judged']}, "
        f"from cache: {labels['cached']}, failed: {labels['failed']}, "
        f"still unlabeled: {labels['unlabeled']}.",
        "",
    ]
    if labels["failed"] or labels["unlabeled"]:
        out += [
            "> Unlabeled results are treated as not relevant, which can understate a system "
            "that surfaces products the gold set never saw. Enable a judge to fill the gaps.",
            "",
        ]
    out += _judging_section(data.get("judging"))
    out += _cost_section(data.get("cost"))
    out += [
        "---",
        f"Produced by llm-search-eval {data['tool']['version']} at {data['generated_at']}.",
        "",
    ]
    return "\n".join(out)


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _judging_section(judging: dict[str, Any] | None) -> list[str]:
    if not judging:
        return []
    out = ["## Judges", ""]
    dist = judging["label_distribution"]
    out.append(
        f"Judge `{_escape(judging['judge'])}` labeled {judging['pairs']} pair(s). "
        "Grade distribution: " + ", ".join(f"{g}: {dist[g]}" for g in ("3", "2", "1", "0")) + "."
    )
    out.append("")
    agreement = judging.get("agreement")
    if agreement:
        alpha = agreement["krippendorff_alpha"]
        out += ["### Inter-judge agreement", ""]
        out += _table(
            ["Statistic", "Value"],
            [
                ["Items with every vote", str(agreement["complete_items"])],
                ["Unanimous", _ratio(agreement["unanimous"])],
                ["Fleiss' kappa", _fmt(agreement["fleiss_kappa"], 3)],
                ["Krippendorff's alpha (ordinal)", _fmt(alpha["ordinal"], 3)],
                ["Krippendorff's alpha (nominal)", _fmt(alpha["nominal"], 3)],
            ],
        )
        out.append("")
        out += _table(
            ["Judges", "n", "Agreement", "Cohen's kappa", "Weighted kappa"],
            (
                [
                    f"`{_escape(p['a'])}` / `{_escape(p['b'])}`",
                    str(p["n"]),
                    _ratio(p["percent_agreement"]),
                    _fmt(p["cohen_kappa"], 3),
                    _fmt(p["weighted_kappa"], 3),
                ]
                for p in agreement["pairwise"]
            ),
        )
        out.append("")
    gold = judging.get("gold_agreement")
    if gold:
        out += ["### Agreement with gold labels", ""]
        raters = [(judging["judge"], gold["judge"]), *gold["members"].items()]
        out += _table(
            ["Rater", "n", "Exact", "Within one", "Binary", "Weighted kappa", "Mean bias"],
            (
                [
                    f"`{_escape(name)}`",
                    str(stats["n"]),
                    _ratio(stats["exact"]),
                    _ratio(stats["within_one"]),
                    _ratio(stats["binary_agreement"]),
                    _fmt(stats["weighted_kappa"], 3),
                    _signed(stats["mean_bias"], 3),
                ]
                for name, stats in raters
            ),
        )
        out += [
            "",
            f"Binary agreement treats grades >= {gold['threshold']} as relevant. Weighted kappa "
            "uses quadratic weights. A positive bias means the judge grades more leniently "
            "than the gold labels.",
            "",
        ]
    return out


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:,.4f}"


def _cost_section(cost: dict[str, Any] | None) -> list[str]:
    if not cost or not (cost["requests"] or cost["cache_hits"] or cost["budget"]["skipped_pairs"]):
        return []
    out = ["## Cost and usage", ""]
    rows = [
        [
            f"`{_escape(name)}`",
            str(m["requests"]),
            f"{m['prompt_tokens']:,}",
            f"{m['completion_tokens']:,}",
            _money(m["cost_usd"]),
        ]
        for name, m in cost["models"].items()
    ]
    rows.append(
        [
            "**Total**",
            str(cost["requests"]),
            f"{cost['prompt_tokens']:,}",
            f"{cost['completion_tokens']:,}",
            f"**{_money(cost['cost_usd'])}**",
        ]
    )
    out += _table(["Model", "Requests", "Input tokens", "Output tokens", "Cost"], rows)
    out += ["", f"Judgments served from cache at no cost: {cost['cache_hits']}."]
    if cost["unpriced_models"]:
        names = ", ".join(f"`{_escape(n)}`" for n in cost["unpriced_models"])
        out.append(f"No price configured for {names}; set one with `--price` or `--price-file`.")
    budget = cost["budget"]
    limits = [
        f"{label} {value}"
        for label, value in (
            ("max cost USD", budget["max_cost_usd"]),
            ("max tokens", budget["max_tokens"]),
            ("max judgments", budget["max_judgments"]),
        )
        if value is not None
    ]
    if limits:
        state = (
            f"reached ({budget['reason']}); {budget['skipped_pairs']} pair(s) were not judged"
            if budget["exhausted"]
            else "not reached"
        )
        out.append(f"Budget: {', '.join(limits)}. Status: {state}.")
    out.append("")
    return out


def write_reports(
    report: EvaluationReport, output_dir: str | Path, formats: Sequence[str] = ("md", "json")
) -> list[Path]:
    """Write the requested reports into ``output_dir``.

    ``formats`` may contain ``md``, ``json``, and ``html``. ``judgments.jsonl`` is
    written whenever a judge produced labels, and ``cost.json`` whenever a judge
    was used.
    """

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if "md" in formats:
        path = out / "report.md"
        path.write_text(render_markdown(report), encoding="utf-8")
        written.append(path)
    if "json" in formats:
        path = out / "report.json"
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(path)
    if "html" in formats:
        path = out / "report.html"
        path.write_text(render_html(report), encoding="utf-8")
        written.append(path)
    data = report.to_dict()
    if data.get("judging") and data.get("cost"):
        path = out / "cost.json"
        path.write_text(
            json.dumps(data["cost"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(path)
    if report.judgments:
        path = out / "judgments.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for j in report.judgments:
                record: dict[str, Any] = {
                    "query_id": j.query_id,
                    "product_id": j.product_id,
                    "relevance": j.relevance,
                    "reason": j.reason,
                    "source": j.source,
                }
                if j.votes:
                    record["votes"] = {v.judge: v.relevance for v in j.votes}
                if j.gold is not None:
                    record["gold"] = j.gold
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        written.append(path)
    return written
