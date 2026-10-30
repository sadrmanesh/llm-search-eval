# Getting started

## Installation

```bash
pip install llm-search-eval
```

or straight from a release tag:

```bash
pip install "git+https://github.com/sadrmanesh/llm-search-eval@v0.2.0"
```

Optional extras let the connectors reuse official clients: `llm-search-eval[elasticsearch]`, `[opensearch]`, and `[algolia]`. They are not needed for the default HTTP mode.

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

The output directory holds `report.md`, `report.json`, the `report.html` dashboard, `cost.json`, and `judgments.jsonl`. See the [sample report](https://github.com/sadrmanesh/llm-search-eval/blob/main/examples/electronics/sample-report/report.md) and the [sample dashboard](https://sadrmanesh.github.io/llm-search-eval/demo/report.html).

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
