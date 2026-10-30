"""Render evaluation reports as Markdown and JSON."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from llm_search_eval.evaluate import EvaluationReport


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

    if comp["significance"]:
        out += [f"## Comparison against `{_escape(cfg['baseline'])}`", ""]
        rows = []
        for t in comp["significance"]:
            d = next(
                x for x in comp["deltas"] if x["system"] == t["system"] and x["metric"] == primary
            )
            p = t["p_value"]
            flag = "" if p is None else (" (significant)" if p < 0.05 else "")
            rows.append(
                [
                    f"`{_escape(t['system'])}`",
                    _signed(d["delta"]),
                    _pct(d["relative"]),
                    f"{t['wins']} / {t['ties']} / {t['losses']}",
                    ("n/a" if p is None else f"{p:.4f}") + flag,
                ]
            )
        out += _table(["System", f"Δ {primary}", "Relative", "Win / tie / loss", "p-value"], rows)
        out += [
            "",
            "p-values come from a two-sided paired randomization test over per-query "
            f"`{primary}` ({cfg['permutations']} permutations, seed {cfg['seed']}).",
            "",
            "### All metric deltas",
            "",
        ]
        out += _table(
            ["System", "Metric", "Baseline", "System value", "Δ", "Relative"],
            (
                [
                    f"`{_escape(d['system'])}`",
                    d["metric"],
                    _fmt(d["baseline"]),
                    _fmt(d["value"]),
                    _signed(d["delta"]),
                    _pct(d["relative"]),
                ]
                for d in comp["deltas"]
            ),
            align="llrrrr",
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
    out += [
        "---",
        f"Produced by llm-search-eval {data['tool']['version']} at {data['generated_at']}.",
        "",
    ]
    return "\n".join(out)


def write_reports(
    report: EvaluationReport, output_dir: str | Path, formats: Sequence[str] = ("md", "json")
) -> list[Path]:
    """Write ``report.md``, ``report.json`` and ``judgments.jsonl`` into ``output_dir``."""
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
    if report.judgments:
        path = out / "judgments.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for j in report.judgments:
                record = {
                    "query_id": j.query_id,
                    "product_id": j.product_id,
                    "relevance": j.relevance,
                    "reason": j.reason,
                    "source": j.source,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        written.append(path)
    return written
