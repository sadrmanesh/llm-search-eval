# Pairwise comparison

Pointwise judging grades one product at a time and turns the grades into
metrics. Pairwise judging asks a more direct question: *for this query, which
of the two result lists would a shopper prefer?* It is a useful second opinion
when two systems are close on nDCG, when gold labels are thin, or when the
difference is in the ordering of results that are all "somewhat relevant".

```bash
llm-search-eval run -q queries.jsonl -p products.jsonl --qrels qrels.csv \
  -s production=runs/production.jsonl -s candidate=runs/candidate.jsonl \
  --pairwise-judge openai=gpt-4o-mini --pairwise-k 5 \
  --pairwise-cache .pairwise-cache.jsonl -o reports/
```

Pairwise comparison runs next to the normal pointwise evaluation. It does not
need `--judge`, and it does not change any metric.

## How it works

For every query, the judge sees the query and the top `--pairwise-k` products
(default 5) of system A and of system B as two numbered lists, and answers
`A`, `B` or `tie` with a short reason.

- **Position bias is cancelled.** By default each query is judged twice, once
  with A shown first and once with B shown first. A system wins a query only
  when both orders agree. When they disagree the query counts as a tie, and
  when they pick opposite winners it is also counted as *inconsistent*, which
  tells you how stable the judge is. `--no-swap` halves the cost and keeps only
  the first order.
- **Free shortcuts.** Queries where both systems return the same top k are ties
  without a judge call, and queries where neither returns anything are skipped.
- **Caching.** Verdicts are cached by judge, query and the exact content of
  both lists, so only queries whose results changed are judged again. The
  judge part includes the pairwise prompt version and hash, which the report
  also shows next to the model (see [prompt versions](judges.md#prompt-versions)).
- **Budgets.** Pairwise calls share the token tracker and the `--max-cost`,
  `--max-tokens` and `--max-judgments` limits with pointwise judging.

## Choosing pairs

Without `--pairwise`, every system is compared with the baseline. To pick pairs
yourself, repeat `--pairwise A:B`:

```bash
--pairwise production:candidate --pairwise candidate:candidate-rerank
```

## Reading the result

| Column | Meaning |
| :--- | :--- |
| B wins, Ties, A wins | Query counts after combining both orders. |
| B win rate | Share of decided queries (ties left out) that B won, with a Wilson confidence interval. |
| p-value | Exact two-sided sign test on wins against losses. |
| Inconsistent | Queries where the two orders picked opposite winners. |

A win rate whose interval lies entirely above 50% is a clear preference for B.
`report.json` keeps the verdicts of every query under `pairwise.comparisons`,
and the dashboard lists them with the judge's reasons.

## Judges

| Spec | Judge |
| :--- | :--- |
| `openai=MODEL[,base_url=URL,...]` | Any OpenAI-compatible endpoint; takes the same options as the pointwise judge, plus `max_product_chars` (default 400). |
| `mock[=margin=0.05]` | Offline judge for tests and CI: compares the DCG of the mock relevance grades of both lists. |
| `module:Class` | Your own subclass of `llm_search_eval.judges.pairwise.PairwiseJudge`. |

```python
from llm_search_eval import PairwiseJudge, PairwiseVerdict, register_pairwise_judge


@register_pairwise_judge("house")
class HouseJudge(PairwiseJudge):
    def compare(self, query, first, second):
        return PairwiseVerdict("A" if len(first) >= len(second) else "B", "longer list")
```

Before a paid run, `llm-search-eval estimate` with the same options shows how
many pairwise calls are needed (see [Cost and budgets](cost.md)).
