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
