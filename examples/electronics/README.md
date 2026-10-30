# Electronics example

A small bilingual (English and Persian) electronics catalog used by the quick start and the test suite.

| File | Contents |
| :--- | :--- |
| `queries.jsonl` | 10 queries, 5 English and 5 Persian. `q09` has no `lang` field and uses Arabic letter forms to exercise detection and normalization. |
| `products.jsonl` | 22 products, including Persian listings and kitchen distractors. |
| `qrels.csv` | 30 graded gold labels (0 to 3). Deliberately incomplete, so the judge has gaps to fill. |
| `runs/bm25.jsonl` | Lexical baseline, one row per result with `rank`. Weak on Persian queries and returns nothing for `q09`. |
| `runs/semantic.csv` | Embedding retriever, one row per result with `score`. |
| `runs/hybrid.trec` | Hybrid retriever in TREC run format. |
| `sample-report/` | Output of the command below. |

```bash
llm-search-eval run \
  -q examples/electronics/queries.jsonl \
  -p examples/electronics/products.jsonl \
  --qrels examples/electronics/qrels.csv \
  -s bm25=examples/electronics/runs/bm25.jsonl \
  -s semantic=examples/electronics/runs/semantic.csv \
  -s hybrid=examples/electronics/runs/hybrid.trec \
  --judge mock \
  --title "Electronics catalog: lexical vs semantic vs hybrid" \
  -o examples/electronics/sample-report
```

The mock judge is a deterministic stand-in for tests. Use `--judge openai` for meaningful labels.
