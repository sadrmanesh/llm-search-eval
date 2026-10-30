"""Command line interface for ``llm-search-eval``.

Commands: ``run`` (evaluate), ``validate`` (check inputs), ``report`` (re-render
a saved report), ``gate`` (fail CI on regressions), ``fetch`` (collect a run
from a live search backend) and ``sample`` (draw a query sample).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from llm_search_eval import __version__
from llm_search_eval.errors import ConfigError, LLMSearchEvalError
from llm_search_eval.evaluate import EvaluationConfig, evaluate
from llm_search_eval.gate import check_report, load_report
from llm_search_eval.html_report import write_html
from llm_search_eval.io import load_dataset, load_queries, load_run, write_json, write_run
from llm_search_eval.judges import JudgmentCache, available_judges, create_judge
from llm_search_eval.judges.base import Judge
from llm_search_eval.judges.panel import AGGREGATIONS, JudgePanel
from llm_search_eval.metrics import DEFAULT_METRICS
from llm_search_eval.models import Run
from llm_search_eval.report import render_markdown, summary_table, write_reports
from llm_search_eval.usage import Budget, CostTracker, PriceTable

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_JUDGE_FAILURES = 3

REPORT_FORMATS = ("md", "json", "html")


def _option_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    for kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            pass
    return value.strip()


def _system_arg(value: str) -> tuple[str, str]:
    name, sep, path = value.partition("=")
    if not sep:
        return Path(value).stem, value
    if not name or not path:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, path


def _sample_size(value: str) -> int | float:
    text = value.strip()
    try:
        if text.endswith("%"):
            number: int | float = float(text[:-1]) / 100
        elif "." in text:
            number = float(text)
        else:
            number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "expected a number of queries (200), a fraction (0.25) or a percentage (25%)"
        ) from None
    if number <= 0 or (isinstance(number, float) and number > 1):
        raise argparse.ArgumentTypeError("sample must be a positive count or a fraction up to 1")
    return number


def _add_sampling_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("sampling")
    g.add_argument(
        "--sample",
        type=_sample_size,
        metavar="SIZE",
        help="evaluate a random sample of queries: a count (200), fraction (0.25) or 25%%",
    )
    g.add_argument(
        "--stratify",
        metavar="FIELD",
        help="sample in proportion to a query field (lang or an extra column) "
        "and break the primary metric down by it",
    )
    g.add_argument(
        "--min-per-stratum",
        type=int,
        default=1,
        metavar="N",
        help="queries drawn from each group at least (default: 1)",
    )


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


def _metric_floor(value: str) -> tuple[str, float]:
    metric, sep, number = value.partition("=")
    try:
        if not sep or not metric:
            raise ValueError
        return metric.strip(), float(number)
    except ValueError:
        raise argparse.ArgumentTypeError("expected METRIC=VALUE, for example ndcg@10=0.6") from None


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
    j = run.add_argument_group("judges")
    j.add_argument(
        "--judge",
        dest="judges",
        action="append",
        default=[],
        metavar="SPEC",
        help=f"relevance judge for unlabeled results: {', '.join(available_judges())}, "
        "openai=MODEL[,base_url=URL,api_key_env=VAR,timeout=S], mock[=noise=P,seed=N], "
        "or module:Class[=KEY=VALUE,...]. "
        "Repeat to form a panel of judges (default: no judge)",
    )
    j.add_argument(
        "--aggregate",
        choices=AGGREGATIONS,
        default="majority",
        help="how a panel combines grades (default: %(default)s)",
    )
    j.add_argument("--min-votes", type=int, help="votes a panel needs per pair (default: majority)")
    j.add_argument("--model", help="default model for LLM judges")
    j.add_argument("--base-url", help="OpenAI-compatible API base URL (default: $OPENAI_BASE_URL)")
    j.add_argument("--api-key-env", help="environment variable holding the API key")
    j.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    j.add_argument("--no-json-mode", action="store_true", help="do not request JSON responses")
    j.add_argument("--cache", help="JSONL cache of judgments, reused across runs")
    j.add_argument("--concurrency", type=int, default=4, help="parallel judge requests")
    j.add_argument(
        "--calibrate",
        action="store_true",
        help="also judge pairs that have gold labels and report judge vs gold agreement",
    )
    j.add_argument("--calibration-sample", type=int, metavar="N", help="judge at most N gold pairs")

    pw = run.add_argument_group("pairwise comparison")
    pw.add_argument(
        "--pairwise-judge",
        metavar="SPEC",
        help="compare systems head to head with a pairwise judge: mock or "
        "openai=MODEL[,base_url=URL,...] (uses --model, --base-url and friends)",
    )
    pw.add_argument(
        "--pairwise",
        dest="pairwise_pairs",
        action="append",
        default=[],
        metavar="A:B",
        help="systems to compare; repeatable (default: each system vs the baseline)",
    )
    pw.add_argument(
        "--pairwise-k", type=int, default=5, help="results per system shown (default: 5)"
    )
    pw.add_argument(
        "--no-swap",
        action="store_true",
        help="judge each query once instead of in both orders (half the cost, more bias)",
    )
    pw.add_argument("--pairwise-cache", help="JSONL cache of pairwise verdicts")

    c = run.add_argument_group("cost and budget")
    c.add_argument(
        "--price",
        action="append",
        default=[],
        metavar="MODEL=IN,OUT",
        help="USD per million input and output tokens for a model; repeatable",
    )
    c.add_argument("--price-file", help="JSON file mapping model names to prices")
    c.add_argument("--max-cost", type=float, metavar="USD", help="stop judging at this cost")
    c.add_argument("--max-tokens", type=int, help="stop judging after this many tokens")
    c.add_argument("--max-judgments", type=int, help="stop after this many fresh judgments")

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
    m.add_argument(
        "--bootstrap",
        type=int,
        default=1000,
        metavar="N",
        help="bootstrap resamples for confidence intervals; 0 turns them off (default: 1000)",
    )
    m.add_argument(
        "--confidence",
        type=float,
        default=0.95,
        help="confidence level of the intervals (default: %(default)s)",
    )

    _add_sampling_args(run)

    o = run.add_argument_group("output")
    o.add_argument("--output-dir", "-o", default="reports", help="report directory")
    o.add_argument(
        "--format",
        default="md,json,html",
        help="comma separated report formats: md, json, html (default: %(default)s)",
    )
    o.add_argument("--title", default="Search evaluation report")
    o.add_argument("--quiet", action="store_true", help="do not print the summary table")

    validate = sub.add_parser("validate", help="check dataset and run files for problems")
    _add_dataset_args(validate)

    report = sub.add_parser("report", help="render a saved report.json as Markdown or HTML")
    report.add_argument("report", help="path to report.json")
    report.add_argument("--output-dir", "-o", help="directory (default: next to report.json)")
    report.add_argument("--format", default="html", help="md, html, or both (default: html)")

    sample = sub.add_parser(
        "sample",
        help="write a random, optionally stratified, sample of a queries file",
        description="Draw a reproducible sample of queries, for example to label a "
        "manageable subset or to keep CI fast. The output is JSONL.",
    )
    sample.add_argument("--queries", "-q", required=True, help="queries file")
    sample.add_argument("--output", "-o", required=True, help="JSONL file to write")
    sample.add_argument("--seed", type=int, default=13)
    _add_sampling_args(sample)

    gate = sub.add_parser(
        "gate",
        help="check a report against quality thresholds; exit code 1 on failure",
        description="Fail when metrics fall below a floor or regress against the baseline "
        "system or a reference report. Prints a Markdown summary.",
    )
    gate.add_argument("report", help="path to report.json")
    gate.add_argument("--reference", help="earlier report.json to compare the same systems with")
    gate.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        default=[],
        help="metric for regression checks; repeatable (default: the primary metric)",
    )
    gate.add_argument("--max-drop", type=float, help="largest allowed absolute drop")
    gate.add_argument(
        "--max-relative-drop", type=float, help="largest allowed relative drop, e.g. 0.05 for 5%%"
    )
    gate.add_argument(
        "--min",
        dest="floors",
        action="append",
        default=[],
        type=_metric_floor,
        metavar="METRIC=VALUE",
        help="minimum mean value for a metric; repeatable",
    )
    gate.add_argument(
        "--system",
        dest="systems",
        action="append",
        default=[],
        help="only check these systems; repeatable (default: all)",
    )
    gate.add_argument(
        "--significant-only",
        action="store_true",
        help="fail on a drop only when the paired randomization test finds it significant",
    )
    gate.add_argument("--alpha", type=float, default=0.05, help="significance level")
    gate.add_argument("--permutations", type=int, default=10_000)
    gate.add_argument("--seed", type=int, default=13)
    gate.add_argument("--summary", help="append the Markdown summary to this file")
    gate.add_argument("--json", dest="json_out", help="write the check results as JSON")

    fetch = sub.add_parser("fetch", help="query a live search backend and save the results")
    fetch.add_argument("--queries", "-q", required=True, help="queries file")
    fetch.add_argument(
        "--backend", required=True, choices=["elasticsearch", "opensearch", "algolia"]
    )
    fetch.add_argument("--index", required=True, help="index name")
    fetch.add_argument("--output", "-o", required=True, help="run file to write (.jsonl or .trec)")
    fetch.add_argument("--name", help="system name stored in TREC output (default: backend)")
    fetch.add_argument("-k", type=int, default=10, help="results per query (default: 10)")
    fetch.add_argument("--concurrency", type=int, default=4)
    fetch.add_argument("--timeout", type=float, default=30.0)
    fetch.add_argument("--id-field", help="document field holding the product id")
    es = fetch.add_argument_group("Elasticsearch and OpenSearch")
    es.add_argument("--url", help="cluster URL, e.g. http://localhost:9200")
    es.add_argument(
        "--fields",
        help="comma separated fields for the default multi_match query "
        "(default: title^3,brand^2,category,description)",
    )
    es.add_argument(
        "--template",
        help="JSON file with the request body; {{query}}, {{k}} and {{lang}} are filled in",
    )
    es.add_argument("--username", help="basic auth user; password from *_PASSWORD")
    al = fetch.add_argument_group("Algolia")
    al.add_argument("--app-id", help="application id (default: $ALGOLIA_APP_ID)")
    al.add_argument("--params", help="JSON object of extra search parameters")
    return parser


def _load_runs(systems: Sequence[tuple[str, str]]) -> list[Run]:
    return [load_run(path, name) for name, path in systems]


def _progress(done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        print(f"\rjudging {done}/{total}", end="\n" if done == total else "", file=sys.stderr)


def _parse_formats(value: str, allowed: Sequence[str] = REPORT_FORMATS) -> list[str]:
    formats = [f.strip().lower() for f in value.split(",") if f.strip()]
    unknown = set(formats) - set(allowed)
    if unknown or not formats:
        raise ConfigError(
            f"unknown report format(s): {', '.join(sorted(unknown)) or value!r}; "
            f"choose from {', '.join(allowed)}"
        )
    return formats


def _judge_options(spec: str, args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    name, sep, rest = spec.partition("=")
    name = name.strip()
    options: dict[str, Any] = {}
    if name == "openai" or ":" in name:
        options = {
            "model": args.model,
            "base_url": args.base_url,
            "api_key_env": args.api_key_env,
            "timeout": args.timeout,
            "json_mode": False if args.no_json_mode else None,
        }
    if sep:
        for i, part in enumerate(p.strip() for p in rest.split(",")):
            key, eq, value = part.partition("=")
            key = key.strip()
            if not eq and i == 0:
                options["model"] = part
            elif not eq or not key.isidentifier():
                raise ConfigError(f"invalid judge option {part!r} in {spec!r}; use KEY=VALUE")
            elif key == "model":
                options[key] = value.strip()
            else:
                options[key] = _option_value(value)
    return name, options


def _judge_from_spec(spec: str, args: argparse.Namespace) -> Judge:
    name, options = _judge_options(spec, args)
    return create_judge(name, **options)


def _pair_arg(value: str) -> tuple[str, str]:
    a, sep, b = value.partition(":")
    if not sep or not a.strip() or not b.strip():
        raise ConfigError(f"invalid --pairwise {value!r}; expected SYSTEM_A:SYSTEM_B")
    return a.strip(), b.strip()


def _build_pairwise_judge(args: argparse.Namespace) -> Any:
    spec = (args.pairwise_judge or "").strip()
    if not spec or spec == "none":
        if args.pairwise_pairs:
            raise ConfigError("--pairwise needs --pairwise-judge")
        return None
    from llm_search_eval.judges.pairwise import create_pairwise_judge

    name, options = _judge_options(spec, args)
    return create_pairwise_judge(name, **options)


def _build_judge(args: argparse.Namespace) -> Judge | None:
    specs = [s for s in args.judges if s.strip() and s.strip() != "none"]
    if not specs:
        return None
    judges = [_judge_from_spec(spec, args) for spec in specs]
    if len(judges) == 1:
        return judges[0]
    return JudgePanel(judges, aggregation=args.aggregate, min_votes=args.min_votes)


def _build_tracker(args: argparse.Namespace) -> CostTracker:
    prices = PriceTable.from_file(args.price_file) if args.price_file else PriceTable()
    prices = PriceTable.parse_specs(args.price, base=prices)
    budget = Budget(args.max_cost, args.max_tokens, args.max_judgments)
    return CostTracker(prices=prices, budget=budget)


def _pairwise_cache(path: str | None) -> Any:
    from llm_search_eval.pairwise import PairwiseCache

    return PairwiseCache(path)


def cmd_run(args: argparse.Namespace) -> int:
    if not args.systems:
        raise LLMSearchEvalError("at least one --system NAME=PATH is required")
    formats = _parse_formats(args.format)
    dataset = load_dataset(args.queries, args.products, args.qrels)
    runs = _load_runs(args.systems)
    tracker = _build_tracker(args)
    judge = _build_judge(args)
    if judge is None and not dataset.qrels:
        print(
            "warning: no --qrels and no --judge: every result will count as not relevant",
            file=sys.stderr,
        )
    if judge is None and args.calibrate:
        raise ConfigError("--calibrate needs at least one --judge")

    config = EvaluationConfig(
        metrics=args.metrics,
        depth=args.depth,
        threshold=args.threshold,
        gain=args.gain,
        baseline=args.baseline,
        primary_metric=args.primary,
        permutations=args.permutations,
        seed=args.seed,
        bootstrap=args.bootstrap,
        confidence=args.confidence,
        concurrency=args.concurrency,
        title=args.title,
        calibrate=args.calibrate,
        calibration_sample=args.calibration_sample,
        sample_size=args.sample,
        stratify_by=args.stratify,
        min_per_stratum=args.min_per_stratum,
        pairwise_k=args.pairwise_k,
        pairwise_swap=not args.no_swap,
        pairwise_pairs=[_pair_arg(p) for p in args.pairwise_pairs] or None,
    )
    pairwise_judge = _build_pairwise_judge(args)
    if args.stratify and args.sample is None and not args.quiet:
        print(
            f"note: no --sample; reporting every query, grouped by {args.stratify}", file=sys.stderr
        )
    try:
        report = evaluate(
            dataset,
            runs,
            config,
            judge=judge,
            cache=JudgmentCache(args.cache),
            progress=None if args.quiet else _progress,
            tracker=tracker,
            pairwise_judge=pairwise_judge,
            pairwise_cache=_pairwise_cache(args.pairwise_cache),
        )
    finally:
        if judge is not None:
            judge.close()
        if pairwise_judge is not None:
            pairwise_judge.close()
    written = write_reports(report, args.output_dir, formats)
    data = report.to_dict()
    if not args.quiet:
        print("\n".join(summary_table(data)))
        cost = data["cost"]
        if judge is not None:
            spent = "unknown" if cost["cost_usd"] is None else f"${cost['cost_usd']:.4f}"
            print(
                f"judge requests: {cost['requests']}, tokens: {cost['total_tokens']}, "
                f"cost: {spent}, cache hits: {cost['cache_hits']}",
                file=sys.stderr,
            )
        for path in written:
            print(f"wrote {path}", file=sys.stderr)
    if data["cost"]["budget"]["exhausted"]:
        print(
            f"warning: budget {data['cost']['budget']['reason']}; "
            f"{data['cost']['budget']['skipped_pairs']} pair(s) were not judged",
            file=sys.stderr,
        )
    failed = data["labels"]["failed"] + sum(
        c["failed"] for c in (data.get("pairwise") or {}).get("comparisons", [])
    )
    if failed:
        print(f"error: {failed} judgment(s) failed; see report.json for details", file=sys.stderr)
        return EXIT_JUDGE_FAILURES
    return EXIT_OK


def cmd_sample(args: argparse.Namespace) -> int:
    from llm_search_eval.io import write_queries
    from llm_search_eval.sampling import sample_queries

    if args.sample is None:
        raise ConfigError("--sample is required, for example --sample 200 or --sample 0.1")
    queries = load_queries(args.queries)
    result = sample_queries(
        queries,
        args.sample,
        stratify_by=args.stratify,
        seed=args.seed,
        min_per_stratum=args.min_per_stratum,
    )
    path = write_queries(args.output, result.queries)
    print(f"wrote {path}: {len(result.queries)} of {result.population} queries", file=sys.stderr)
    for name, counts in result.strata.items():
        print(f"  {name}: {counts['sampled']} of {counts['population']}", file=sys.stderr)
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    formats = _parse_formats(args.format, ("md", "html"))
    data = load_report(args.report)
    out = Path(args.output_dir) if args.output_dir else Path(args.report).parent
    out.mkdir(parents=True, exist_ok=True)
    if "md" in formats:
        path = out / "report.md"
        path.write_text(render_markdown(data), encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    if "html" in formats:
        if "details" not in data:
            print(
                "warning: the report has no per-query details; the drilldown will be empty",
                file=sys.stderr,
            )
        print(f"wrote {write_html(data, out / 'report.html')}", file=sys.stderr)
    return EXIT_OK


def cmd_gate(args: argparse.Namespace) -> int:
    data = load_report(args.report)
    reference = load_report(args.reference) if args.reference else None
    if not (args.floors or args.max_drop is not None or args.max_relative_drop is not None):
        raise ConfigError("set at least one of --min, --max-drop or --max-relative-drop")
    result = check_report(
        data,
        reference=reference,
        metrics=args.metrics or None,
        floors=dict(args.floors),
        max_drop=args.max_drop,
        max_relative_drop=args.max_relative_drop,
        systems=args.systems or None,
        significant_only=args.significant_only,
        alpha=args.alpha,
        permutations=args.permutations,
        seed=args.seed,
    )
    summary = result.to_markdown()
    print(summary)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    if args.json_out:
        write_json(args.json_out, result.to_dict())
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


def _json_arg(value: str | None, what: str, from_file: bool) -> Any:
    if value is None:
        return None
    try:
        text = Path(value).read_text(encoding="utf-8") if from_file else value
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"invalid {what}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{what} must be a JSON object")
    return data


def cmd_fetch(args: argparse.Namespace) -> int:
    from llm_search_eval.connectors import (
        AlgoliaConnector,
        ElasticsearchConnector,
        OpenSearchConnector,
        fetch_run,
    )
    from llm_search_eval.connectors.base import SearchConnector

    queries = load_queries(args.queries)
    connector: SearchConnector
    if args.backend == "algolia":
        connector = AlgoliaConnector(
            args.app_id,
            args.index,
            params=_json_arg(args.params, "--params", from_file=False),
            id_field=args.id_field or "objectID",
            timeout=args.timeout,
        )
    else:
        cls = ElasticsearchConnector if args.backend == "elasticsearch" else OpenSearchConnector
        options: dict[str, Any] = {}
        if args.fields:
            options["fields"] = [f.strip() for f in args.fields.split(",") if f.strip()]
        connector = cls(
            args.url,
            args.index,
            query_template=_json_arg(args.template, "--template", from_file=True),
            id_field=args.id_field,
            username=args.username,
            timeout=args.timeout,
            **options,
        )
    try:
        result = fetch_run(
            connector, queries, k=args.k, name=args.name, concurrency=args.concurrency
        )
    finally:
        connector.close()
    path = write_run(args.output, result.run)
    print(
        f"wrote {path}: {len(result.run.rankings)} of {len(queries)} queries from {args.backend}",
        file=sys.stderr,
    )
    if result.failures:
        for qid, message in sorted(result.failures.items()):
            print(f"error: query {qid}: {message}", file=sys.stderr)
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
    langs: dict[str | None, int] = {}
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
        commands = {
            "run": cmd_run,
            "validate": cmd_validate,
            "report": cmd_report,
            "gate": cmd_gate,
            "fetch": cmd_fetch,
            "sample": cmd_sample,
        }
        return commands[args.command](args)
    except LLMSearchEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


__all__ = ["build_parser", "main", "render_markdown"]
