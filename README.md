# llm-search-eval

[![CI](https://github.com/sadrmanesh/llm-search-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/sadrmanesh/llm-search-eval/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![Dependencies](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Measure product search and recommendation quality with classic IR metrics and LLM relevance judges, then compare systems with statistical rigor.**

Built for e-commerce teams who ship ranking changes (BM25 to vectors, hybrid retrieval, rerankers, query rewriting) and need a trustworthy answer to one question: *is the new system actually better for shoppers?* First-class support for **Persian and English** queries.

---

## Contents

- [Why](#why)
- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Data formats](#data-formats)
- [Relevance judges](#relevance-judges)
- [Metrics](#metrics)
- [Reports](#reports)
- [Python API](#python-api)
- [Persian support](#persian-support)
- [Roadmap](#roadmap)
- [خلاصه فارسی](#خلاصه-فارسی)

## Why

Offline search evaluation usually breaks down in the same places:

- **Labels run out.** A gold set labelled last quarter does not cover the products a new retriever surfaces today, so unlabeled results silently count as misses and the new system looks worse than it is.
- **Averages hide noise.** A +2% nDCG gain on 50 queries can easily be chance.
- **Multilingual catalogs are messy.** Persian text mixes Arabic and Persian code points, digit systems, and zero width joiners, which breaks naive matching.

`llm-search-eval` merges your gold labels with LLM judgments for the gaps, scores every system on the same label pool, reports per-language breakdowns, and attaches a paired significance test to every comparison.

## Features

- **Classic IR metrics:** nDCG@k (exponential or linear gain), precision@k, recall@k, MRR, MAP, with configurable relevance threshold and evaluation depth.
- **LLM-as-judge:** graded 0 to 3 relevance labels from any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama, LM Studio, internal gateways), with retries, backoff, and robust JSON parsing.
- **Pluggable judges:** register your own grader with a decorator or load it by `module:Class` path.
- **Deterministic mock judge** for CI, tests, and offline dry runs.
- **Judgment cache:** content-addressed JSONL cache; re-runs never pay for the same judgment twice, and edited products are re-judged automatically.
- **System comparison:** deltas for every metric, win/tie/loss counts, and a paired randomization test against a baseline.
- **Flexible inputs:** JSONL, JSON, CSV, TSV, and TREC run/qrels files, with common field aliases.
- **Reports:** Markdown for pull requests and wikis, JSON for dashboards, and a `judgments.jsonl` audit trail.
- **Zero runtime dependencies**, Python 3.10+, fully typed.

## Installation

```bash
pip install "git+https://github.com/sadrmanesh/llm-search-eval@v0.1.0"
```

From source, for development:

```bash
git clone https://github.com/sadrmanesh/llm-search-eval
cd llm-search-eval
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

The repository ships a small bilingual electronics catalog with three systems to compare. Run it offline with the mock judge:

```bash
llm-search-eval run \
  --queries  examples/electronics/queries.jsonl \
  --products examples/electronics/products.jsonl \
  --qrels    examples/electronics/qrels.csv \
  --system   bm25=examples/electronics/runs/bm25.jsonl \
  --system   semantic=examples/electronics/runs/semantic.csv \
  --system   hybrid=examples/electronics/runs/hybrid.trec \
  --judge mock \
  --output-dir reports/
```

```text
| System | ndcg@5 | ndcg@10 | precision@5 | recall@10 | mrr | map |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `bm25` | 0.5305 | 0.5305 | 0.2200 | 0.4833 | 0.8000 | 0.4306 |
| `semantic` | **0.9865** | **0.9865** | **0.4200** | **0.9667** | **1.0000** | **0.9667** |
| `hybrid` | 0.9767 | 0.9767 | **0.4200** | **0.9667** | **1.0000** | 0.9583 |
```

The full report, including significance tests and the per-language breakdown, is in [`examples/electronics/sample-report/report.md`](examples/electronics/sample-report/report.md).

Switch to a real LLM judge by changing one flag:

```bash
export OPENAI_API_KEY=...
llm-search-eval run ... --judge openai --model gpt-4o-mini --cache .judge-cache.jsonl
```

Check inputs before spending tokens:

```bash
llm-search-eval validate --queries ... --products ... --qrels ... --system ...
```

Run `llm-search-eval run --help` for every option.

## Data formats

Every file can be `.jsonl`, `.json`, `.csv`, or `.tsv`. Field names are case-insensitive.

**Queries**: `query_id` (alias `qid`), `text` (alias `query`), optional `lang`. Language is detected when omitted.

```json
{"query_id": "q06", "text": "هدفون بی سیم نویز کنسلینگ", "lang": "fa"}
```

**Products**: `product_id` (alias `id`, `doc_id`), `title` (alias `name`), optional `description`, `category`, `brand`, `price`, `attributes`. Any other column becomes an attribute that judges can see.

```json
{"product_id": "p06", "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", "brand": "Sony", "category": "Headphones"}
```

**Gold labels** (optional): `query_id`, `product_id`, `relevance` (alias `label`) on the graded scale below. TREC qrels files (`.qrels`, `.txt`) are also accepted.

| Grade | Meaning |
| :---: | :--- |
| 3 | Exact match: fully satisfies the query |
| 2 | Relevant: satisfies the main intent with minor gaps |
| 1 | Partially relevant: related, but misses key requirements |
| 0 | Irrelevant |

**System runs**: one file per system, passed as `--system NAME=PATH`. Any of these layouts work:

- one row per result with `query_id`, `product_id`, and `rank` (ascending) or `score` (descending); file order is used otherwise;
- one object per query: `{"query_id": "q1", "results": ["p3", "p1", "p7"]}`;
- TREC run files (`.trec`, `.run`): `qid Q0 docid rank score tag`.

## Relevance judges

For every (query, product) pair in each system's top `depth` results, labels are resolved in this order:

1. **Gold label** from `--qrels`, if present. Gold labels are never re-judged.
2. **Cached judgment**, if the same judge configuration has already seen this exact query and product content.
3. **Judge**, if `--judge` is set. Otherwise the result is counted as unlabeled (not relevant), and the report shows the coverage gap.

All systems are scored against the same merged label pool, so the ideal ranking used by nDCG and the recall denominator are identical for every system.

| Judge | Use it for |
| :--- | :--- |
| `mock` | Tests, CI, and offline dry runs. Deterministic term coverage over title, brand, category, and attributes. Not a quality signal. |
| `openai` | Any OpenAI-compatible chat completions API. Configure with `--model`, `--base-url` (or `OPENAI_BASE_URL`), and `--api-key-env` (default `OPENAI_API_KEY`). Local servers on `localhost` need no key. |
| `module:Class` | Your own judge. |

Running against a local model with Ollama:

```bash
llm-search-eval run ... --judge openai --base-url http://localhost:11434/v1 --model qwen2.5:14b
```

Writing a custom judge:

```python
from llm_search_eval import Judge, Judgment, register_judge


@register_judge("click-model")
class ClickModelJudge(Judge):
    name = "click-model"

    def __init__(self, table_path: str = "ctr.parquet") -> None:
        self.table = load_ctr_table(table_path)

    @property
    def fingerprint(self) -> str:  # part of the cache key
        return f"click-model:{self.table.version}"

    def judge(self, query, product):
        ctr = self.table.lookup(query.text, product.product_id)
        return Judgment(relevance=min(3, int(ctr * 30)), reason=f"ctr={ctr:.3f}")
```

```bash
llm-search-eval run ... --judge my_package.judges:ClickModelJudge
```

## Metrics

| Metric | Spec | Definition |
| :--- | :--- | :--- |
| nDCG | `ndcg@k` | DCG of the top k divided by the ideal DCG from all known labels for the query. Gain is `2^rel - 1` (default) or `rel` with `--gain linear`. |
| Precision | `precision@k`, `p@k` | Relevant results in the top k, divided by k. |
| Recall | `recall@k`, `r@k` | Relevant results in the top k, divided by all known relevant products. |
| MRR | `mrr`, `mrr@k` | Reciprocal rank of the first relevant result. |
| MAP | `map`, `map@k` | Average precision over relevant ranks, divided by all known relevant products. |

- Binary metrics treat grades `>= --threshold` (default `2`) as relevant.
- Rankings are cut at `--depth`, which defaults to the largest k among the selected metrics.
- A query with no relevant product in the label pool has undefined metrics. It is excluded from the mean instead of being scored as zero, and the JSON report records `n` for every aggregate.
- The **primary metric** (default: the largest-k nDCG, or `--primary`) is used to rank systems and for significance testing.

### Significance testing

Each system is compared to the baseline (first system, or `--baseline`) with a two-sided paired randomization (sign flip) test on per-query values of the primary metric. It makes no normality assumption and is the standard choice in IR evaluation. Use `--permutations` and `--seed` to trade precision for speed and to keep results reproducible.

## Reports

`--output-dir` receives:

| File | Contents |
| :--- | :--- |
| `report.md` | Summary table with best values in bold, comparison with p-values and win/tie/loss, all metric deltas, primary metric by query language, and label coverage. |
| `report.json` | Everything above plus per-query metric values and the full configuration, for dashboards and regression gates. |
| `judgments.jsonl` | Every judge label with its reason and source (`judge` or `cache`), for auditing and for promoting to gold labels. |

The command exits with code `0` on success, `2` for invalid input or configuration, and `3` when some judgments failed.

## Python API

```python
from llm_search_eval import EvaluationConfig, create_judge, evaluate
from llm_search_eval.io import load_dataset, load_run
from llm_search_eval.judges import JudgmentCache
from llm_search_eval.report import render_markdown

dataset = load_dataset("queries.jsonl", "products.jsonl", "qrels.csv")
runs = [load_run("runs/bm25.jsonl", "bm25"), load_run("runs/hybrid.trec", "hybrid")]

report = evaluate(
    dataset,
    runs,
    EvaluationConfig(metrics=["ndcg@10", "recall@50", "mrr"], baseline="bm25"),
    judge=create_judge("openai", model="gpt-4o-mini"),
    cache=JudgmentCache(".judge-cache.jsonl"),
)

print(report.mean("hybrid", "ndcg@10"))
print(render_markdown(report))
```

## Persian support

- Arabic `ي` and `ك` are unified with Persian `ی` and `ک`; Persian and Arabic-Indic digits become ASCII digits.
- Diacritics, tatweel, and directional marks are removed, and the zero width non-joiner is treated as a word boundary.
- Query language is detected from the script when `lang` is missing, and reports break down the primary metric by language.
- The LLM judge prompt states the query language and counts translations and transliterations between Persian and English as matches.

## Roadmap

Planned for upcoming releases:

- Multiple judges per pair with agreement statistics (Cohen's kappa) and judge-versus-gold calibration.
- Token and cost accounting with budget limits.
- Interactive HTML dashboard.
- GitHub Action for ranking regression gates in pull requests.
- Connectors to run queries directly against Elasticsearch, OpenSearch, and Algolia.
- PyPI release.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and conventions, and [CHANGELOG.md](CHANGELOG.md) for release notes.

## خلاصه فارسی

<div dir="rtl">

**llm-search-eval** ابزاری متن باز برای سنجش کیفیت جستجو و پیشنهاد محصول در فروشگاه های اینترنتی است. این ابزار معیارهای کلاسیک بازیابی اطلاعات مانند nDCG و MRR و MAP را با داوری مدل های زبانی ترکیب می کند تا نتایجی که برچسب ندارند هم ارزیابی شوند. چند سیستم جستجو را کنار هم مقایسه می کند و برای هر مقایسه آزمون معناداری آماری ارائه می دهد. پرسش های فارسی و انگلیسی هر دو پشتیبانی می شوند و نویسه های عربی، ارقام فارسی و فاصله های مجازی به شکل یکسان نرمال سازی می شوند.

</div>

## License

[MIT](LICENSE) © 2026 Naser Sadrmanesh
