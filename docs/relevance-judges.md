# Relevance judges

For every (query, product) pair in each system's top `depth` results, labels are resolved in this order:

1. **Gold label** from `--qrels`, if present. Gold labels are never re-judged.
2. **Cached judgment**, if the same judge configuration has already seen this exact query and product content.
3. **Judge**, if `--judge` is set. Otherwise the result is counted as unlabeled (not relevant), and the report shows the coverage gap.

All systems are scored against the same merged label pool, so the ideal ranking used by nDCG and the recall denominator are identical for every system.

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
