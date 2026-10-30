# Electronics catalog: lexical vs semantic vs hybrid

- **Queries:** 10 (en: 5, fa: 5)
- **Products:** 22
- **Gold labels:** 30
- **Judge:** mock
- **Depth:** top 10, relevant when grade >= 2, exponential gain
- **Primary metric:** `ndcg@10`, baseline `bm25`

## Summary

| System | ndcg@5 | ndcg@10 | precision@5 | recall@10 | mrr | map |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `bm25` | 0.5305 | 0.5305 | 0.2200 | 0.4833 | 0.8000 | 0.4306 |
| `semantic` | **0.9865** | **0.9865** | **0.4200** | **0.9667** | **1.0000** | **0.9667** |
| `hybrid` | 0.9767 | 0.9767 | **0.4200** | **0.9667** | **1.0000** | 0.9583 |

Best system by `ndcg@10`: **`semantic`**.

## Comparison against `bm25`

| System | Δ ndcg@10 | Relative | Win / tie / loss | p-value |
| :--- | ---: | ---: | ---: | ---: |
| `semantic` | +0.4561 | +86.0% | 10 / 0 / 0 | 0.0020 (significant) |
| `hybrid` | +0.4463 | +84.1% | 10 / 0 / 0 | 0.0020 (significant) |

p-values come from a two-sided paired randomization test over per-query `ndcg@10` (10000 permutations, seed 13).

### All metric deltas

| System | Metric | Baseline | System value | Δ | Relative |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `semantic` | ndcg@5 | 0.5305 | 0.9865 | +0.4561 | +86.0% |
| `semantic` | ndcg@10 | 0.5305 | 0.9865 | +0.4561 | +86.0% |
| `semantic` | precision@5 | 0.2200 | 0.4200 | +0.2000 | +90.9% |
| `semantic` | recall@10 | 0.4833 | 0.9667 | +0.4833 | +100.0% |
| `semantic` | mrr | 0.8000 | 1.0000 | +0.2000 | +25.0% |
| `semantic` | map | 0.4306 | 0.9667 | +0.5361 | +124.5% |
| `hybrid` | ndcg@5 | 0.5305 | 0.9767 | +0.4463 | +84.1% |
| `hybrid` | ndcg@10 | 0.5305 | 0.9767 | +0.4463 | +84.1% |
| `hybrid` | precision@5 | 0.2200 | 0.4200 | +0.2000 | +90.9% |
| `hybrid` | recall@10 | 0.4833 | 0.9667 | +0.4833 | +100.0% |
| `hybrid` | mrr | 0.8000 | 1.0000 | +0.2000 | +25.0% |
| `hybrid` | map | 0.4306 | 0.9583 | +0.5278 | +122.6% |

## `ndcg@10` by query language

| System | en | fa |
| :--- | ---: | ---: |
| `bm25` | 0.6292 (n=5) | 0.4317 (n=5) |
| `semantic` | 0.9731 (n=5) | 1.0000 (n=5) |
| `hybrid` | 0.9630 (n=5) | 0.9904 (n=5) |

## Label coverage

| System | Queries answered | Labeled in top 10 | Unknown products |
| :--- | ---: | ---: | ---: |
| `bm25` | 9/10 | 100.0% | 0 |
| `semantic` | 10/10 | 100.0% | 0 |
| `hybrid` | 10/10 | 100.0% | 0 |

Gold labels used: 30, new judgments: 49, from cache: 0, failed: 0, still unlabeled: 0.

## Judges

Judge `mock` labeled 49 pair(s). Grade distribution: 3: 8, 2: 5, 1: 10, 0: 26.

### Agreement with gold labels

| Rater | n | Exact | Within one | Binary | Weighted kappa | Mean bias |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `mock` | 30 | 33.3% | 66.7% | 63.3% | 0.257 | -1.000 |

Binary agreement treats grades >= 2 as relevant. Weighted kappa uses quadratic weights. A positive bias means the judge grades more leniently than the gold labels.

---
Produced by llm-search-eval 0.2.0 at 2026-10-30T16:36:22+00:00.
