# Sampling and strata

Large query sets are expensive to judge. A reproducible sample keeps CI fast
and labeling budgets small, and stratification keeps every segment
represented.

## Sample during a run

```bash
llm-search-eval run ... --sample 200 --stratify lang
llm-search-eval run ... --sample 25% --stratify segment --min-per-stratum 5
```

`--sample` takes a count (`200`), a fraction (`0.25`) or a percentage (`25%`).
With `--stratify FIELD`, the sample is split across the values of a query field
in proportion to their size (largest remainder), with at least
`--min-per-stratum` queries (default 1) from each group. The seed is `--seed`,
so the same inputs always give the same sample. Gold labels of queries that
are not in the sample are ignored.

## Write a sample to a file

```bash
llm-search-eval sample -q queries.jsonl -o eval/sample.jsonl --sample 300 --stratify segment
```

This is useful to pick the queries that humans should label next.

## Query fields

Any extra field in the queries file can be used for stratification, for
example:

```json
{"query_id": "q1", "text": "گوشی سامسونگ", "lang": "fa", "segment": "head", "category": "phones"}
```

`lang` (or `language`) groups by query language; queries without a language
count as `und`. Queries without the field fall in a `(none)` group.

## Reports

The report records the population size, the sample size, the seed and the
per-group counts. With `--stratify` on a field other than the language, the
report adds a table of the primary metric per group, so you can see whether a
change helps head queries but hurts the long tail. `--stratify` without
`--sample` keeps every query and only adds that table.

## Python

```python
from llm_search_eval import sample_queries

result = sample_queries(dataset.queries, 0.25, stratify_by="segment", seed=7)
print(result.to_dict()["strata"])
```
