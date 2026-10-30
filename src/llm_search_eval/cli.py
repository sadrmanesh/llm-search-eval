"""Command line interface: ``llm-search-eval run`` and ``llm-search-eval validate``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from llm_search_eval import __version__
from llm_search_eval.errors import LLMSearchEvalError
from llm_search_eval.evaluate import EvaluationConfig, evaluate
from llm_search_eval.io import load_dataset, load_run
from llm_search_eval.judges import JudgmentCache, available_judges, create_judge
from llm_search_eval.metrics import DEFAULT_METRICS
from llm_search_eval.models import Run
from llm_search_eval.report import render_markdown, summary_table, write_reports

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_JUDGE_FAILURES = 3


def _system_arg(value: str) -> tuple[str, str]:
    name, sep, path = value.partition("=")
    if not sep:
        return Path(value).stem, value
    if not name or not path:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, path


def _add_dataset_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("dataset")
    g.add_argument(
        "--queries", "-q", required=True, help="queries file (.jsonl, .json, .csv, .tsv)"
    )
    g.add_argument("--products", "-p", required=True, help="product catalog file")
    g.add_argument("--qrels", help="optional gold relevance labels (graded 0-3)")
    g.add_argument(
        "--system",
        "-s",
        dest="systems",
        action="append",
        type=_system_arg,
        default=[],
        metavar="NAME=PATH",
        help="ranked results of one system; repeat to compare systems",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-search-eval",
        description="Evaluate and compare product search systems with IR metrics and LLM judges.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="score and compare one or more search systems")
    _add_dataset_args(run)
    j = run.add_argument_group("judge")
    j.add_argument(
        "--judge",
        default="none",
        help=f"relevance judge for unlabeled results: none, {', '.join(available_judges())}, "
        "or module:Class (default: none)",
    )
    j.add_argument("--model", help="model name for LLM judges")
    j.add_argument("--base-url", help="OpenAI-compatible API base URL (default: $OPENAI_BASE_URL)")
    j.add_argument("--api-key-env", help="environment variable holding the API key")
    j.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    j.add_argument("--no-json-mode", action="store_true", help="do not request JSON responses")
    j.add_argument("--cache", help="JSONL cache of judgments, reused across runs")
    j.add_argument("--concurrency", type=int, default=4, help="parallel judge requests")

    m = run.add_argument_group("metrics")
    m.add_argument(
        "--metrics",
        default=",".join(DEFAULT_METRICS),
        help="comma separated metrics (default: %(default)s)",
    )
    m.add_argument("--primary", help="metric used for ranking and significance tests")
    m.add_argument("--depth", type=int, help="rank cutoff applied to runs (default: max k)")
    m.add_argument("--threshold", type=int, default=2, help="minimum relevant grade (default: 2)")
    m.add_argument("--gain", choices=["exponential", "linear"], default="exponential")
    m.add_argument("--baseline", help="system to compare against (default: first system)")
    m.add_argument("--permutations", type=int, default=10_000, help="randomization test rounds")
    m.add_argument("--seed", type=int, default=13)

    o = run.add_argument_group("output")
    o.add_argument("--output-dir", "-o", default="reports", help="report directory")
    o.add_argument("--format", default="md,json", help="report formats: md, json (default: both)")
    o.add_argument("--title", default="Search evaluation report")
    o.add_argument("--quiet", action="store_true", help="do not print the summary table")

    validate = sub.add_parser("validate", help="check dataset and run files for problems")
    _add_dataset_args(validate)
    return parser


def _load_runs(systems: Sequence[tuple[str, str]]) -> list[Run]:
    return [load_run(path, name) for name, path in systems]


def _progress(done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        print(f"\rjudging {done}/{total}", end="\n" if done == total else "", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    if not args.systems:
        raise LLMSearchEvalError("at least one --system NAME=PATH is required")
    dataset = load_dataset(args.queries, args.products, args.qrels)
    runs = _load_runs(args.systems)
    judge = None
    if args.judge != "none":
        options = {}
        if args.judge == "openai" or ":" in args.judge:
            options = {
                "model": args.model,
                "base_url": args.base_url,
                "api_key_env": args.api_key_env,
                "timeout": args.timeout,
                "json_mode": False if args.no_json_mode else None,
            }
        judge = create_judge(args.judge, **options)
    elif not dataset.qrels:
        print(
            "warning: no --qrels and no --judge: every result will count as not relevant",
            file=sys.stderr,
        )

    config = EvaluationConfig(
        metrics=args.metrics,
        depth=args.depth,
        threshold=args.threshold,
        gain=args.gain,
        baseline=args.baseline,
        primary_metric=args.primary,
        permutations=args.permutations,
        seed=args.seed,
        concurrency=args.concurrency,
        title=args.title,
    )
    try:
        report = evaluate(
            dataset,
            runs,
            config,
            judge=judge,
            cache=JudgmentCache(args.cache),
            progress=None if args.quiet else _progress,
        )
    finally:
        if judge is not None:
            judge.close()
    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    unknown = set(formats) - {"md", "json"}
    if unknown:
        raise LLMSearchEvalError(f"unknown report format(s): {', '.join(sorted(unknown))}")
    written = write_reports(report, args.output_dir, formats)
    if not args.quiet:
        print("\n".join(summary_table(report.to_dict())))
        for path in written:
            print(f"wrote {path}", file=sys.stderr)
    failed = report.to_dict()["labels"]["failed"]
    if failed:
        print(f"error: {failed} judgment(s) failed; see report.json for details", file=sys.stderr)
        return EXIT_JUDGE_FAILURES
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.queries, args.products, args.qrels)
    problems: list[str] = []
    for qid, rels in dataset.qrels.items():
        if qid not in dataset.queries:
            problems.append(f"qrels: unknown query id {qid!r}")
        problems += [
            f"qrels: unknown product {pid!r} (query {qid})"
            for pid in rels
            if pid not in dataset.products
        ]
    if dataset.qrels and max(r for rels in dataset.qrels.values() for r in rels.values()) <= 1:
        problems.append("qrels: labels look binary (0/1); use --threshold 1 or grade them 0-3")
    for run in _load_runs(args.systems):
        for qid, ranking in run.rankings.items():
            if qid not in dataset.queries:
                problems.append(f"{run.name}: unknown query id {qid!r}")
            missing = [pid for pid in ranking if pid not in dataset.products]
            if missing:
                problems.append(f"{run.name}: {len(missing)} unknown product(s) for query {qid}")
        silent = [q for q in dataset.queries if not run.rankings.get(q)]
        if silent:
            problems.append(f"{run.name}: no results for {len(silent)} query(ies)")
    langs = {}
    for q in dataset.queries.values():
        langs[q.lang] = langs.get(q.lang, 0) + 1
    print(
        f"{len(dataset.queries)} queries {langs}, {len(dataset.products)} products, "
        f"{sum(len(v) for v in dataset.qrels.values())} gold labels, {len(args.systems)} system(s)"
    )
    for problem in problems:
        print(f"warning: {problem}")
    print("ok" if not problems else f"{len(problems)} warning(s)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        if args.command == "run":
            return cmd_run(args)
        return cmd_validate(args)
    except LLMSearchEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


__all__ = ["build_parser", "main", "render_markdown"]
