# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-30

First release intended for production use: judge panels, cost control, an interactive dashboard, CI quality gates, and live search connectors.

### Added

- Judge panels: repeat `--judge` to combine several judges by majority, mean, median, min, or max (`--aggregate`), with a configurable quorum (`--min-votes`) and tolerance for individual judge failures.
- Inter-judge agreement in every panel report: unanimous share, Fleiss' kappa, Krippendorff's alpha (nominal, ordinal, interval), and pairwise Cohen's kappa (plain and linear or quadratic weighted).
- Judge versus gold calibration with `--calibrate` and `--calibration-sample`: exact, within-one, and binary agreement, kappa, and bias for the panel and each member. Gold labels still decide the scores.
- Token and cost tracking per model with user-supplied prices (`--price`, `--price-file`), budgets on cost, tokens, or judgments (`--max-cost`, `--max-tokens`, `--max-judgments`), and a `cost.json` report.
- Interactive `report.html` dashboard in a single self-contained file: metric charts, system comparison with per-query deltas, judge agreement, cost, and a searchable per-query drilldown.
- `llm-search-eval gate` command: metric floors and absolute or relative drop limits against the baseline or a reference report, optionally only for statistically significant drops, with Markdown and JSON output.
- `llm-search-eval report` command to re-render Markdown or HTML from a saved `report.json`.
- `llm-search-eval fetch` command and connectors for Elasticsearch, OpenSearch, and Algolia, with request templates, authentication from environment variables, retries, and optional official client extras (`elasticsearch`, `opensearch`, `algolia`).
- Reusable composite GitHub Action (`action.yml`) that runs an evaluation, applies the gate, writes the job summary, and exposes report paths as outputs.
- Tag-driven PyPI release workflow with trusted publishing or an API token.
- Panel votes and gold labels in `judgments.jsonl`.
- Documentation under `docs/` for judges, cost, reports, CI, connectors, and releasing.
- Type checking with mypy in CI, and Python 3.13 in the test matrix.

### Changed

- `--format` now defaults to `md,json,html`.
- `--judge` accepts specs such as `openai=gpt-4o-mini,temperature=0` and can be repeated.
- The mock judge accepts `noise`, `seed`, and `label` options for reproducible disagreement in offline panel runs.
- The sample report in `examples/electronics` now includes the dashboard, judge calibration, and cost files.

## [0.1.0] - 2026-10-30

Initial release.

### Added

- `llm-search-eval run` command to score one or more search systems and compare them against a baseline.
- `llm-search-eval validate` command to detect unknown ids, missing results, and binary-looking labels before an evaluation.
- Dataset loaders for queries, products, and graded gold labels in JSONL, JSON, CSV, and TSV, plus TREC qrels and run files.
- Ranking metrics: nDCG@k with exponential or linear gain, precision@k, recall@k, MRR, and MAP, with configurable relevance threshold and evaluation depth.
- LLM-as-judge relevance grading on a 0 to 3 scale through any OpenAI-compatible chat completions API, with retries, backoff, and tolerant response parsing.
- Deterministic mock judge for tests, CI, and offline runs.
- Pluggable judge registry with `register_judge` and `module:Class` loading.
- Content-addressed JSONL judgment cache.
- Paired randomization significance test, win/tie/loss counts, and per-metric deltas against the baseline.
- Persian and English text normalization, language detection, and per-language metric breakdowns.
- Markdown and JSON reports plus a `judgments.jsonl` audit log.
- Bilingual electronics example dataset with three systems and a sample report.
- Continuous integration with ruff and pytest on Python 3.10, 3.11, and 3.12.

[Unreleased]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sadrmanesh/llm-search-eval/releases/tag/v0.1.0
