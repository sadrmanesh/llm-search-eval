# Metrics

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
