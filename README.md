# llm-search-eval

[![CI](https://github.com/sadrmanesh/llm-search-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/sadrmanesh/llm-search-eval/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20to%203.13-blue)
![Dependencies](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-sadrmanesh.github.io-3f51b5)](https://sadrmanesh.github.io/llm-search-eval/)

**Measure product search quality with classic IR metrics and panels of LLM relevance judges, compare systems with statistical rigor, and block ranking regressions in CI.**

Built for e-commerce teams who ship ranking changes (BM25 to vectors, hybrid retrieval, rerankers, query rewriting) and need a trustworthy answer to one question: *is the new system actually better for shoppers?* First-class support for **Persian and English** queries.

**Documentation:** <https://sadrmanesh.github.io/llm-search-eval/> · **Live sample dashboard:** <https://sadrmanesh.github.io/llm-search-eval/demo/report.html> · **Try it in the browser:** [Hugging Face Space](https://huggingface.co/spaces/sadrmanesh/llm-search-eval-demo) · **Example data:** [Hugging Face dataset](https://huggingface.co/datasets/sadrmanesh/llm-search-eval-electronics)

---

## Contents

- [Why](#why)
- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Data formats](#data-formats)
- [Relevance judges](#relevance-judges)
- [Judge panels and agreement](#judge-panels-and-agreement)
- [Cost tracking and budgets](#cost-tracking-and-budgets)
- [Metrics](#metrics)
- [Confidence intervals](#confidence-intervals)
- [Pairwise comparison](#pairwise-comparison)
- [Sampling and strata](#sampling-and-strata)
- [Reports and dashboard](#reports-and-dashboard)
- [Quality gates and the GitHub Action](#quality-gates-and-the-github-action)
- [Live search connectors](#live-search-connectors)
- [Python API](#python-api)
- [Persian support](#persian-support)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [خلاصه فارسی](#خلاصه-فارسی)

## Why

Offline search evaluation usually breaks down in the same places:

- **Labels run out.** A gold set labelled last quarter does not cover the products a new retriever surfaces today, so unlabeled results silently count as misses and the new system looks worse than it is.
- **Averages hide noise.** A +2% nDCG gain on 50 queries can easily be chance.
- **One model is one opinion.** A single LLM judge has its own biases, and nobody checks how well it agrees with the humans who wrote the gold labels.
- **Costs creep.** Judging thousands of pairs with a frontier model adds up, and nobody notices until the invoice.
- **Multilingual catalogs are messy.** Persian text mixes Arabic and Persian code points, digit systems, and zero width joiners, which breaks naive matching.

`llm-search-eval` merges your gold labels with LLM judgments for the gaps, can ask several judges and measure how much they agree with each other and with your gold labels, tracks every token against a budget, scores every system on the same label pool, attaches a paired significance test to every comparison, and turns the result into a dashboard and a pass or fail check for pull requests.

## Features

- **Classic IR metrics:** nDCG@k (exponential or linear gain), precision@k, recall@k, MRR, MAP, with configurable relevance threshold and evaluation depth.
- **LLM-as-judge:** graded 0 to 3 relevance labels from any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama, LM Studio, internal gateways), with retries, backoff, and robust JSON parsing.
- **Judge panels:** combine several judges by majority, mean, median, min, or max, and tolerate individual failures.
- **Agreement statistics:** Cohen's kappa (plain and weighted), Fleiss' kappa, and Krippendorff's alpha between judges, plus calibration of every judge against your gold labels.
- **Cost tracking:** token usage per model, user-supplied prices, budgets on cost, tokens, or judgments, a `cost.json` report, and an `estimate` command that predicts calls, tokens, and cost before a run.
- **System comparison:** deltas for every metric, win/tie/loss counts, a paired randomization test, and bootstrap confidence intervals for every mean and delta.
- **Pairwise judging:** an LLM compares two result lists side by side, in both orders to cancel position bias, with win rates, Wilson intervals, and a sign test.
- **Sampling:** reproducible random or stratified query samples and per-segment results.
- **Interactive dashboard:** one self-contained HTML file with charts and interval whiskers, system comparison, pairwise results, per-segment tables, and per-query drilldown. No server, no CDN.
- **Quality gates:** `llm-search-eval gate` and a reusable GitHub Action fail the build when a metric drops below a floor or regresses, and keep one pull request comment up to date with the result.
- **Live connectors:** fetch runs straight from Elasticsearch, OpenSearch, Algolia, Meilisearch, Typesense, or any HTTP/JSON search API.
- **Pluggable judges** by decorator or `module:Class`, a **deterministic mock judge** for CI, and a **content-addressed judgment cache** so re-runs never pay twice.
- **Flexible inputs:** JSONL, JSON, CSV, TSV, and TREC run/qrels files, with common field aliases.
- **Zero runtime dependencies**, Python 3.10 to 3.13, fully typed.

## Installation

```bash
pip install llm-search-eval
```

or straight from a release tag:

```bash
pip install "git+https://github.com/sadrmanesh/llm-search-eval@v0.4.0"
```

Optional extras let the connectors reuse official clients: `llm-search-eval[elasticsearch]`, `[opensearch]`, and `[algolia]`. They are not needed for the default HTTP mode.

Or run the Docker image from [Docker Hub](https://hub.docker.com/r/sadrmanesh/llm-search-eval) or the GitHub Container Registry (`ghcr.io/sadrmanesh/llm-search-eval`), for `linux/amd64` and `linux/arm64`. Mount your data into `/work`:

```bash
docker run --rm -v "$PWD:/work" sadrmanesh/llm-search-eval:0.4.0 run \
  -q eval/queries.jsonl -p eval/products.jsonl --qrels eval/qrels.csv \
  -s bm25=eval/runs/bm25.jsonl -s hybrid=eval/runs/hybrid.trec --judge mock -o reports
```

More in [docs/docker.md](docs/docker.md).

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

The output directory holds `report.md`, `report.json`, the `report.html` dashboard, `cost.json`, and `judgments.jsonl`. See the [sample report](examples/electronics/sample-report/report.md) and the [sample dashboard](examples/electronics/sample-report/report.html).

Switch to a real LLM judge, with a price and a budget:

```bash
export OPENAI_API_KEY=...
llm-search-eval run ... --judge openai=gpt-4o-mini --cache .judge-cache.jsonl \
  --price gpt-4o-mini=0.15,0.60 --max-cost 2
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
2. **Cached judgment**, if the same judge configuration, including its prompt version and prompt hash, has already seen this exact query and product content.
3. **Judge**, if `--judge` is set. Otherwise the result is counted as unlabeled (not relevant), and the report shows the coverage gap.

All systems are scored against the same merged label pool, so the ideal ranking used by nDCG and the recall denominator are identical for every system.

Every result records which prompt produced it. The OpenAI-compatible judges carry a prompt version (`relevance-v1`, `pairwise-v1`) and a 12-character SHA-256 of the prompt text. Both, with the provider and model, are written to `report.json`, the Judges and Pairwise sections of `report.md` and the dashboard, and each cache entry. They are also part of the cache key, so a judgment made with a different prompt is never reused. See [prompt versions](https://sadrmanesh.github.io/llm-search-eval/judges/#prompt-versions).

| Judge spec | Use it for |
| :--- | :--- |
| `mock` | Tests, CI, and offline dry runs. Deterministic term coverage over title, brand, category, and attributes. Not a quality signal. `mock=noise=0.2,seed=1` adds reproducible disagreement for trying panels. |
| `openai` or `openai=MODEL` | Any OpenAI-compatible chat completions API. Configure with `--model`, `--base-url` (or `OPENAI_BASE_URL`), and `--api-key-env` (default `OPENAI_API_KEY`), or per judge: `openai=MODEL,base_url=URL,api_key_env=VAR`. Local servers on `localhost` need no key. |
| `module:Class` | Your own judge. |

Running against a local model with Ollama:

```bash
llm-search-eval run ... --judge "openai=qwen2.5:14b,base_url=http://localhost:11434/v1"
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

## Judge panels and agreement

Repeat `--judge` to form a panel. Every member grades every pair and the panel combines the grades:

```bash
llm-search-eval run ... \
  --judge openai=gpt-4o-mini \
  --judge openai=gpt-4o \
  --judge "openai=qwen2.5:14b,base_url=http://localhost:11434/v1" \
  --aggregate majority --calibrate --calibration-sample 200
```

- `--aggregate` is `majority` (default), `mean`, `median`, `min`, or `max`. `--min-votes` sets how many members must answer; the default is a strict majority.
- The report shows the unanimous share, **Fleiss' kappa**, **Krippendorff's alpha** (nominal, ordinal, interval), and pairwise **Cohen's kappa** (plain and quadratic-weighted).
- `--calibrate` also sends gold-labeled pairs to the judges and reports exact, within-one, and binary agreement, kappa, and bias against the gold labels, for the panel and for each member. Gold labels still decide the scores.

Details: [docs/judges.md](docs/judges.md).

## Cost tracking and budgets

Every judge request records its token usage. Prices are never guessed: pass them per model in USD per million tokens with `--price MODEL=INPUT,OUTPUT` or `--price-file prices.json`. A price for `gpt-4o-mini` also covers dated snapshots such as `gpt-4o-mini-2024-07-18`, and models without a price show the cost as unknown rather than zero.

`--max-cost`, `--max-tokens`, and `--max-judgments` stop new requests once a limit is reached; remaining pairs stay unlabeled and the report says how many were skipped. Cache hits are free.

Before a paid run, `llm-search-eval estimate` takes the same arguments as `run` and prints the expected calls, tokens, and cost without calling any model. It exits with `1` when the estimate exceeds the budget, so CI can stop before spending anything:

```bash
llm-search-eval estimate -q queries.jsonl -p products.jsonl --qrels qrels.csv \
  -s bm25=runs/bm25.jsonl -s hybrid=runs/hybrid.trec \
  --judge openai=gpt-4o-mini --price gpt-4o-mini=0.15,0.60 --max-cost 2
```

Details: [docs/cost.md](docs/cost.md).

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

## Confidence intervals

Every mean gets a percentile bootstrap interval over queries, and every delta against the baseline gets a paired bootstrap interval, next to the randomization test p-value. `--bootstrap N` sets the resamples (default 1000, `0` turns intervals off) and `--confidence` the level (default 0.95). Details: [docs/statistics.md](docs/statistics.md).

## Pairwise comparison

Pointwise grades can miss differences in ordering. With `--pairwise-judge`, an LLM sees the top k results of two systems side by side and picks the list a shopper would prefer:

```bash
llm-search-eval run ... -s production=runs/prod.jsonl -s candidate=runs/cand.jsonl \
  --pairwise-judge openai=gpt-4o-mini --pairwise-k 5 --pairwise-cache .pairwise-cache.jsonl
```

Each query is judged in both orders and only consistent verdicts count as wins, which cancels position bias. The report shows wins, ties, losses, the win rate with a Wilson interval, an exact sign test, and how many queries got inconsistent verdicts. `--pairwise A:B` picks pairs (default: each system against the baseline), and `--no-swap` halves the cost. Details: [docs/pairwise.md](docs/pairwise.md).

## Sampling and strata

```bash
llm-search-eval run ... --sample 25% --stratify segment --min-per-stratum 5
llm-search-eval sample -q queries.jsonl -o to-label.jsonl --sample 300 --stratify lang
```

`--sample` takes a count, fraction, or percentage, and `--stratify` splits it across the values of any query field in proportion to their size. The sample is reproducible with `--seed`, and the report adds the primary metric per stratum. Details: [docs/sampling.md](docs/sampling.md).

## Reports and dashboard

`--output-dir` receives:

| File | Contents |
| :--- | :--- |
| `report.md` | Summary table with best values in bold, confidence intervals, comparison with p-values, win/tie/loss and delta intervals, all metric deltas, primary metric by query language and stratum, pairwise preference, label coverage, judges and agreement, and cost. |
| `report.json` | Everything above plus per-query metric values, rankings, labels, and the full configuration. |
| `report.html` | Interactive dashboard in one self-contained file: metric charts with interval whiskers, system comparison with per-query deltas, per-stratum results, pairwise verdicts, judge agreement, cost, and a searchable per-query drilldown that shows every system's ranking side by side. |
| `cost.json` | Token usage, cost per model, and budget state. |
| `judgments.jsonl` | Every judge label with its reason, source, panel votes, and gold label for calibration pairs. |

`--format` selects any of `md`, `json`, and `html` (all by default). `llm-search-eval report report.json` re-renders the Markdown or HTML from a saved JSON report. Details: [docs/reports.md](docs/reports.md).

The `run` command exits with code `0` on success, `2` for invalid input or configuration, and `3` when some judgments failed.

## Quality gates and the GitHub Action

`llm-search-eval gate` turns a report into a pass or fail check:

```bash
llm-search-eval gate reports/report.json --min ndcg@10=0.6 --max-drop 0.01 --significant-only
```

It checks metric floors and drops against the baseline system or against a `--reference` report from the default branch, optionally only when the drop is statistically significant, prints a Markdown table, and exits with `1` on failure.

The repository is also a reusable GitHub Action that runs the evaluation, applies the gate, writes the result to the job summary, and posts it as a pull request comment that is updated on every push:

```yaml
- uses: sadrmanesh/llm-search-eval@v0.4.0
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  with:
    queries: eval/queries.jsonl
    products: eval/products.jsonl
    qrels: eval/qrels.csv
    systems: |
      production=eval/runs/production.jsonl
      candidate=eval/runs/candidate.jsonl
    judges: openai=gpt-4o-mini
    max-cost: "2"
    min: ndcg@10=0.55
    max-drop: "0.01"
```

The comment needs `permissions: pull-requests: write` in the workflow; without it, or on pull requests from forks, the step only warns. Set `comment: "false"` to turn it off. Outside the action, `llm-search-eval comment gate.md report.md --repo OWNER/NAME --pr N` does the same with a `GITHUB_TOKEN`. All inputs and outputs: [docs/ci.md](docs/ci.md) and [docs/pr-comments.md](docs/pr-comments.md).

## Live search connectors

Evaluate the index you actually serve. `fetch` runs every query against the backend and writes a run file:

```bash
llm-search-eval fetch --backend elasticsearch --url http://localhost:9200 --index products \
  --queries eval/queries.jsonl -k 20 -o runs/es.jsonl
llm-search-eval fetch --backend algolia --index products --queries eval/queries.jsonl -o runs/algolia.jsonl
llm-search-eval fetch --backend meilisearch --url http://localhost:7700 --index products -q eval/queries.jsonl -o runs/meili.jsonl
llm-search-eval fetch --backend typesense --url http://localhost:8108 --index products --query-by title,brand -q eval/queries.jsonl -o runs/ts.jsonl
llm-search-eval fetch --backend http --url 'https://search.internal/api?q={{query}}&size={{k}}' \
  --header 'Authorization:Bearer ${SEARCH_TOKEN}' --results-path data.hits --id-path sku \
  -q eval/queries.jsonl -o runs/internal.jsonl
```

Elasticsearch and OpenSearch accept a JSON request template with `{{query}}`, `{{k}}`, and `{{lang}}` placeholders, so you can evaluate your production query as is. The generic `http` backend covers internal search APIs without code: a URL or body template, headers with `${ENV}` secrets, and dotted paths to the results and ids. Details: [docs/connectors.md](docs/connectors.md).

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

Judge panels, cost tracking, the dashboard, and gates have Python entry points too:

```python
from llm_search_eval import (
    Budget,
    CostTracker,
    JudgePanel,
    PriceTable,
    check_report,
    render_html,
)

panel = JudgePanel([create_judge("openai", model="gpt-4o-mini"), create_judge("mock")])
tracker = CostTracker(
    prices=PriceTable.parse_specs(["gpt-4o-mini=0.15,0.60"]),
    budget=Budget(max_cost_usd=2.0),
)
report = evaluate(dataset, runs, EvaluationConfig(calibrate=True), judge=panel, tracker=tracker)

with open("report.html", "w", encoding="utf-8") as fh:
    fh.write(render_html(report))
gate = check_report(report.to_dict(), floors={"ndcg@10": 0.6}, max_drop=0.01)
print(gate.passed)
```

Pairwise judging, intervals, sampling, and estimates:

```python
from llm_search_eval import bootstrap_ci, create_pairwise_judge, sample_queries
from llm_search_eval.estimate import estimate_run, render_estimate

config = EvaluationConfig(bootstrap=2000, sample_size=0.5, stratify_by="lang")
judge = create_pairwise_judge("openai", model="gpt-4o-mini")
print("\n".join(render_estimate(estimate_run(dataset, runs, config, pairwise_judge=judge))))
report = evaluate(dataset, runs, config, pairwise_judge=judge)
print(report.to_dict()["pairwise"]["comparisons"])
```

## Persian support

- Arabic `ي` and `ك` are unified with Persian `ی` and `ک`; Persian and Arabic-Indic digits become ASCII digits.
- Diacritics, tatweel, and directional marks are removed, and the zero width non-joiner is treated as a word boundary.
- Query language is detected from the script when `lang` is missing, and reports break down the primary metric by language.
- The LLM judge prompt states the query language and counts translations and transliterations between Persian and English as matches.

## Documentation

The full documentation site is at <https://sadrmanesh.github.io/llm-search-eval/>. The guides are also readable here on GitHub:

| Guide | Topic |
| :--- | :--- |
| [docs/judges.md](docs/judges.md) | Judge specs, panels, agreement, calibration |
| [docs/statistics.md](docs/statistics.md) | Bootstrap confidence intervals |
| [docs/pairwise.md](docs/pairwise.md) | Pairwise A versus B judging |
| [docs/sampling.md](docs/sampling.md) | Query sampling and stratification |
| [docs/cost.md](docs/cost.md) | Prices, budgets, `estimate`, `cost.json` |
| [docs/reports.md](docs/reports.md) | Report files and the HTML dashboard |
| [docs/ci.md](docs/ci.md) | The `gate` command and the GitHub Action |
| [docs/pr-comments.md](docs/pr-comments.md) | Pull request comments and permissions |
| [docs/connectors.md](docs/connectors.md) | Elasticsearch, OpenSearch, Algolia, Meilisearch, Typesense, HTTP/JSON |
| [docs/docker.md](docs/docker.md) | The Docker image on Docker Hub and GHCR |
| [docs/releasing.md](docs/releasing.md) | Versioning and PyPI publishing |

## Roadmap

Ideas for upcoming releases:

- A Vespa connector and multi-page fetching for very deep runs.
- Pairwise results as a gate condition.
- Active selection of the queries most worth labeling next.
- Interleaving and click log metrics for online comparison.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and conventions, and [CHANGELOG.md](CHANGELOG.md) for release notes.

## خلاصه فارسی

<div dir="rtl">

**llm-search-eval** ابزاری متن باز برای سنجش کیفیت جستجو و پیشنهاد محصول در فروشگاه های اینترنتی است. این ابزار معیارهای کلاسیک بازیابی اطلاعات مانند nDCG و MRR و MAP را با داوری مدل های زبانی ترکیب می کند تا نتایجی که برچسب ندارند هم ارزیابی شوند. چند سیستم جستجو را کنار هم مقایسه می کند و برای هر مقایسه آزمون معناداری آماری ارائه می دهد. پرسش های فارسی و انگلیسی هر دو پشتیبانی می شوند و نویسه های عربی، ارقام فارسی و فاصله های مجازی به شکل یکسان نرمال سازی می شوند.

در نسخه 0.2.0 چند داور مدل زبانی می توانند با هم رای بدهند و میزان توافق آن ها با شاخص های کاپای کوهن، کاپای فلایس و آلفای کریپندورف گزارش می شود. هزینه و توکن هر اجرا با سقف بودجه کنترل می شود. گزارش تعاملی HTML در یک فایل مستقل ساخته می شود. یک GitHub Action آماده هم هست که در صورت افت کیفیت جستجو، بررسی را ناموفق می کند. اتصال مستقیم به Elasticsearch و OpenSearch و Algolia هم اضافه شده است.

نسخه 0.3.0 مقایسه دوبه دو با داور مدل زبانی، بازه اطمینان بوت استرپ برای هر معیار و هر اختلاف، نمونه گیری لایه ای از پرسش ها، دستور `estimate` برای برآورد هزینه پیش از اجرا، دیدگاه خودکار و به روز شونده در Pull Request، و اتصال به Meilisearch و Typesense و هر API جستجوی JSON را اضافه می کند. داشبورد هم بازه های اطمینان، نتایج هر لایه و نمای مقایسه دوبه دو را نشان می دهد.

</div>

## License

[MIT](LICENSE) © 2026 Naser Sadrmanesh
