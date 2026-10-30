# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/sadrmanesh/llm-search-eval/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sadrmanesh/llm-search-eval/releases/tag/v0.1.0
