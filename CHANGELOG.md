# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-10-31

Every result now records which judge prompt produced it.

### Added

- A prompt version and a prompt hash for each LLM judge prompt. `PROMPT_VERSION` and `PAIRWISE_PROMPT_VERSION` stay hand-bumped identifiers; the new `PROMPT_HASH` and `PAIRWISE_PROMPT_HASH` are the first 12 hex characters of a SHA-256 over the rendered system prompt and the user prompt template, so any edit to the text changes them.
- `Judge.info` and `PairwiseJudge.info`, with the judge label, provider (endpoint host), model, prompt version, and prompt hash. A panel lists its members under `members`.
- The provider, model, prompt version, and prompt hash in `report.json` (`judging`, `judging.panel.judges`, `pairwise`, and each pairwise comparison), in the Judges and Pairwise preference sections of `report.md`, and in the HTML dashboard.
- New judgment cache and pairwise cache entries store the judge provenance under `judge`.

### Changed

- The OpenAI-compatible relevance and pairwise judges include the prompt hash in their fingerprint, and so in the cache key. Judgments made with a different prompt are never served from the cache. Cache entries written by earlier versions are judged again once. Mock judges are unchanged.
- The user prompt templates are module constants (`USER_PROMPT_TEMPLATE`, `PAIRWISE_USER_PROMPT_TEMPLATE`). The text sent to the model is byte for byte the same as in 0.3.2.

## [0.3.2] - 2026-10-30

A Docker image for the CLI, and the project on Hugging Face.

### Added

- A Docker image for the CLI on Docker Hub (`sadrmanesh/llm-search-eval`) and the GitHub Container Registry (`ghcr.io/sadrmanesh/llm-search-eval`), for `linux/amd64` and `linux/arm64`, tagged `X.Y.Z`, `X.Y`, and `latest`. It runs as a non-root user in `/work`; `EXTRAS` adds the optional clients at build time. The release workflow builds it on GHCR and copies it to Docker Hub when the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets are set, and CI builds and smoke tests it on every pull request. See the [Docker guide](https://sadrmanesh.github.io/llm-search-eval/docker/).
- A browser demo on Hugging Face, <https://huggingface.co/spaces/sadrmanesh/llm-search-eval-demo>, which runs the package with Pyodide on the example data or on your own files, and the example data as the dataset <https://huggingface.co/datasets/sadrmanesh/llm-search-eval-electronics>.
- `.github/workflows/mirror.yml`, which mirrors `main` and tags to `gitlab.com/sadrmanesh/llm-search-eval` when the `GITLAB_TOKEN` secret is set, and skips cleanly otherwise.

## [0.3.1] - 2026-10-30

### Changed

- Shortened the GitHub Action description so the action can be listed on GitHub Marketplace.

## [0.3.0] - 2026-10-30

Statistical depth and a tighter pull request loop: pairwise judging, confidence intervals, query sampling, cost estimates before a run, sticky pull request comments, and three more connectors.

### Added

- Pairwise (A versus B) LLM judging with `--pairwise-judge`: the judge compares the top `--pairwise-k` results of two systems for each query, in both orders by default to cancel position bias (`--no-swap` to judge once). Reports show wins, ties, losses, the win rate with a Wilson interval, an exact sign test, and inconsistent verdicts. Pairs default to each system against the baseline or are chosen with `--pairwise A:B`; verdicts are cached with `--pairwise-cache` and share the cost tracker and budgets. Includes an OpenAI-compatible judge, an offline mock judge, and a registry for custom judges.
- Bootstrap confidence intervals for every metric mean and paired bootstrap intervals for every delta against the baseline (`--bootstrap`, `--confidence`), in all report formats and as `ci_low` and `ci_high` in `report.json`.
- Reproducible query sampling with `--sample` (count, fraction, or percentage), stratified by language or any query field with `--stratify` and `--min-per-stratum`, a `sample` command that writes a sampled queries file, and a per-stratum table of the primary metric.
- `llm-search-eval estimate`: predicts judge calls, tokens, and cost for a run from the real prompts, after gold labels and cache hits, without calling any model, and exits with `1` when the budget is too small. `--json` for automation.
- `llm-search-eval comment`: posts the gate result and report as a pull request comment and updates the same comment on later runs, with a hidden marker, pagination, a length limit, and a warning instead of a failure when the token lacks permission.
- GitHub Action inputs `comment`, `comment-id`, `github-token`, `max-tokens`, `pairwise-judge`, `pairwise`, `bootstrap`, `confidence`, `sample`, and `stratify`, and a `comment-url` output.
- Connectors for Meilisearch, Typesense, and any HTTP/JSON search API (`--backend http` with URL or body templates, `${ENV}` headers, and dotted result and id paths).
- Dashboard: interval columns and chart whiskers, delta intervals in the comparison, sample size, a per-stratum table, and a pairwise view with stacked win bars and per-query verdicts linked to the drilldown.
- Documentation pages for pairwise judging, confidence intervals, sampling, and pull request comments, including the required permissions and the fork caveats.

### Changed

- `fetch --index` is now optional and checked per backend, and `--url` and `--params` apply to every backend that uses them.
- The sample report in `examples/electronics` now includes confidence intervals and a pairwise comparison.

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

[Unreleased]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sadrmanesh/llm-search-eval/releases/tag/v0.1.0
