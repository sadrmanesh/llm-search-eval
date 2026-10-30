# Cost and budgets

Every request to an OpenAI-compatible judge records the token usage returned by
the API. The billed model name from the response is used, so dated snapshots are
tracked separately.

## Prices

Prices change often and differ between providers, so none are built in. Supply
them in USD per million input and output tokens:

```bash
llm-search-eval run ... --price gpt-4o-mini=0.15,0.60 --price gpt-4o=2.50,10
```

or keep them in a JSON file and pass `--price-file prices.json`:

```json
{
  "gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
  "gpt-4o": [2.50, 10.00]
}
```

A price applies to the exact model name and to any name that starts with it, so
`gpt-4o-mini` also covers `gpt-4o-mini-2024-07-18`; the longest match wins.
Models without a price still count tokens, and the total cost is reported as
unknown instead of a misleading partial number.

## Budgets

| Option | Stops judging when |
| :--- | :--- |
| `--max-cost USD` | the priced cost reaches the limit |
| `--max-tokens N` | input plus output tokens reach the limit |
| `--max-judgments N` | N fresh judgments have been started |

Cache hits are free and never count against a budget. When a limit is reached,
the remaining pairs are left unlabeled, the run still completes, and the report
and the console show how many pairs were skipped. With `--concurrency` above
one, requests that were already in flight can finish after the limit, so keep a
small margin.

## Reports

The Markdown report has a **Cost and usage** section, and `cost.json` holds the
same data for automation:

```json
{
  "judgments": 49,
  "cache_hits": 12,
  "requests": 49,
  "prompt_tokens": 61250,
  "completion_tokens": 2450,
  "total_tokens": 63700,
  "cost_usd": 0.010658,
  "unpriced_models": [],
  "models": {"gpt-4o-mini-2024-07-18": {"requests": 49, "cost_usd": 0.010658, "...": "..."}},
  "budget": {"max_cost_usd": 1.0, "exhausted": false, "skipped_pairs": 0, "...": "..."}
}
```

For a panel, `requests` counts every member request, while `judgments` counts
pairs.
