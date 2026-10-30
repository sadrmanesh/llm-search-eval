# Confidence intervals

A mean over 50 queries is an estimate, not a fact. Every report now shows how
precise each number is.

## Metric intervals

For each system and metric, `run` resamples the queries with replacement
(1000 times by default) and computes the percentile bootstrap interval of the
mean. The Markdown report has a table for the primary metric:

```text
## Confidence intervals for `ndcg@10`

| System   |   Mean |           95% CI | Queries |
| bm25     | 0.5305 | [0.3970, 0.6293] |      10 |
| semantic | 0.9865 | [0.9657, 1.0000] |      10 |
```

## Delta intervals

For every comparison against the baseline, the same queries are resampled for
both systems (a paired bootstrap), and the report shows the interval of the
difference. When the interval of a delta does not include zero, the change is
unlikely to be noise. This complements the paired randomization test p-value,
which is still reported.

## Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--bootstrap N` | `1000` | Number of resamples. `0` turns intervals off. |
| `--confidence C` | `0.95` | Confidence level, for example `0.9`. |
| `--seed N` | `13` | Seed shared with the randomization test, so reports are reproducible. |

In `report.json`, each metric entry has `ci_low` and `ci_high`, and so does
each entry in `comparison.deltas`. The dashboard shows the intervals in the
metric table and as whiskers on the charts.

## Python

```python
from llm_search_eval import bootstrap_ci, paired_bootstrap_ci

interval = bootstrap_ci([0.4, 0.7, 0.9, 0.5], confidence=0.9, resamples=2000)
print(interval.low, interval.high, interval.contains(0.6))

delta = paired_bootstrap_ci(candidate_scores, baseline_scores)
```

`llm_search_eval.stats` also has `wilson_interval` (used for pairwise win
rates) and an exact `sign_test`.

## Caveats

- The bootstrap treats queries as a random sample of real traffic. If your
  query set is hand-picked, the interval describes that set, not your users.
- With fewer than about 20 queries, intervals are rough; collect more queries
  before trusting small differences.
