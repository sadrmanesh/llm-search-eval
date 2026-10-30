---
hide:
  - navigation
---

# llm-search-eval

**Measure product search quality with classic IR metrics and panels of LLM relevance judges, compare systems with statistical rigor, and block ranking regressions in CI.**

Built for e-commerce teams who ship ranking changes (BM25 to vectors, hybrid retrieval, rerankers, query rewriting) and need a trustworthy answer to one question: *is the new system actually better for shoppers?* Persian and English queries are both first-class.

[Get started](getting-started.md){ .md-button .md-button--primary }
[Live sample dashboard](https://sadrmanesh.github.io/llm-search-eval/demo/report.html){ .md-button }
[Try it in the browser](https://huggingface.co/spaces/sadrmanesh/llm-search-eval-demo){ .md-button }
[GitHub](https://github.com/sadrmanesh/llm-search-eval){ .md-button }

```bash
pip install llm-search-eval
llm-search-eval run --queries queries.jsonl --products products.jsonl \
  --qrels qrels.csv --system bm25=runs/bm25.jsonl --system hybrid=runs/hybrid.trec \
  --judge openai=gpt-4o-mini --output-dir reports/
```

## Why

Offline search evaluation usually breaks down in the same places:

- **Labels run out.** A gold set labelled last quarter does not cover the products a new retriever surfaces today, so unlabeled results silently count as misses and the new system looks worse than it is.
- **Averages hide noise.** A +2% nDCG gain on 50 queries can easily be chance.
- **One model is one opinion.** A single LLM judge has its own biases, and nobody checks how well it agrees with the humans who wrote the gold labels.
- **Costs creep.** Judging thousands of pairs with a frontier model adds up, and nobody notices until the invoice.
- **Multilingual catalogs are messy.** Persian text mixes Arabic and Persian code points, digit systems, and zero width joiners, which breaks naive matching.

`llm-search-eval` merges your gold labels with LLM judgments for the gaps, can ask several judges and measure how much they agree with each other and with your gold labels, tracks every token against a budget, scores every system on the same label pool, attaches a paired significance test to every comparison, and turns the result into a dashboard and a pass or fail check for pull requests.

## Features

- **Classic IR metrics:** nDCG@k (exponential or linear gain), precision@k, recall@k, MRR, MAP, with configurable relevance threshold and evaluation depth.
- **LLM-as-judge:** graded 0 to 3 relevance labels from any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama, LM Studio, internal gateways), with retries, backoff, and robust JSON parsing.
- **Judge panels:** combine several judges by majority, mean, median, min, or max, and tolerate individual failures.
- **Agreement statistics:** Cohen's kappa (plain and weighted), Fleiss' kappa, and Krippendorff's alpha between judges, plus calibration of every judge against your gold labels.
- **Cost tracking:** token usage per model, user-supplied prices, budgets on cost, tokens, or judgments, and an `estimate` command that predicts the cost before any call.
- **System comparison:** deltas for every metric, win/tie/loss counts, a paired randomization test, and bootstrap confidence intervals for every mean and delta.
- **Pairwise judging:** an LLM compares two result lists side by side, in both orders to cancel position bias, and reports win rates with intervals and a sign test.
- **Sampling:** reproducible random or stratified query samples, with per-segment results.
- **Interactive dashboard:** one self-contained HTML file with charts, system comparison, and per-query drilldown. No server, no CDN.
- **Quality gates:** `llm-search-eval gate` and a reusable GitHub Action fail the build when a metric drops below a floor or regresses, and post the result as a pull request comment that updates on every push.
- **Live connectors:** fetch runs straight from Elasticsearch, OpenSearch, Algolia, Meilisearch, Typesense, or any HTTP/JSON search API.
- **Pluggable judges** by decorator or `module:Class`, a **deterministic mock judge** for CI, and a **content-addressed judgment cache** so re-runs never pay twice.
- **Flexible inputs:** JSONL, JSON, CSV, TSV, and TREC run/qrels files, with common field aliases.
- **Zero runtime dependencies**, Python 3.10 to 3.13, fully typed.

## Explore

<div class="grid cards" markdown>

-   **Relevance judges**

    ---

    Gold labels first, cached judgments next, and an LLM judge for the gaps.

    [Relevance judges](relevance-judges.md)

-   **Panels and agreement**

    ---

    Several judges, one verdict, with kappa and alpha to show how far to trust it.

    [Panels and agreement](judges.md)

-   **Pairwise comparison**

    ---

    Ask which of two result lists a shopper would prefer, with position bias cancelled.

    [Pairwise comparison](pairwise.md)

-   **Confidence intervals**

    ---

    Bootstrap intervals for every mean and every difference between systems.

    [Confidence intervals](statistics.md)

-   **Cost and budgets**

    ---

    Estimate the cost before a run, then track every token against hard limits.

    [Cost and budgets](cost.md)

-   **Reports and dashboard**

    ---

    Markdown, JSON, and one self-contained interactive HTML dashboard.

    [Reports and dashboard](reports.md)

-   **Quality gates in CI**

    ---

    Fail a pull request when a metric regresses, and report it in a comment.

    [Quality gates](ci.md)

-   **Live search connectors**

    ---

    Evaluate the Elasticsearch, OpenSearch, Algolia, Meilisearch, Typesense, or custom API you actually serve.

    [Connectors](connectors.md)

</div>

## License

MIT. Copyright (c) 2026 Naser Sadrmanesh.
