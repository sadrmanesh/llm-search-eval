# Python API

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

Pairwise comparison, confidence intervals, sampling, estimates, and pull
request comments:

```python
from llm_search_eval import (
    bootstrap_ci,
    create_pairwise_judge,
    sample_queries,
)
from llm_search_eval.estimate import estimate_run, render_estimate
from llm_search_eval.pairwise import PairwiseCache

config = EvaluationConfig(bootstrap=2000, confidence=0.9, sample_size=0.5, stratify_by="lang")
judge = create_pairwise_judge("openai", model="gpt-4o-mini")

print("\n".join(render_estimate(estimate_run(dataset, runs, config, pairwise_judge=judge))))

report = evaluate(
    dataset,
    runs,
    config,
    pairwise_judge=judge,
    pairwise_cache=PairwiseCache(".pairwise-cache.jsonl"),
)
print(report.to_dict()["pairwise"]["comparisons"][0]["win_rate_b"])
print(bootstrap_ci([0.4, 0.7, 0.9, 0.5]))
subset = sample_queries(dataset.queries, 100, stratify_by="segment", seed=7).queries
```

Posting a comment from your own script:

```python
import os

from llm_search_eval.github import GitHubClient, PullRequestContext, upsert_comment

context = PullRequestContext("owner/name", 42)
result = upsert_comment(GitHubClient(os.environ["GITHUB_TOKEN"]), context, render_markdown(report))
print(result.action, result.url)
```
