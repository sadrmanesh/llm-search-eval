# Judges and agreement

Gold labels are always preferred. A judge only grades the (query, product) pairs
that appear in a system's top results and have no gold label, unless calibration
is turned on (see below). Every judgment is cached by content, so a re-run with
the same judge configuration costs nothing.

## Judge specs

`--judge` takes a spec and can be repeated:

| Spec | Meaning |
| :--- | :--- |
| `mock` | Deterministic term coverage judge for tests and offline runs. |
| `mock=noise=0.2,seed=7` | Mock judge that moves 20% of grades one step, reproducibly. Useful for trying panels offline. |
| `openai` | OpenAI-compatible judge using `--model`, `--base-url`, and `--api-key-env`. |
| `openai=gpt-4o-mini` | Same, with the model set for this judge only. |
| `openai=qwen2.5:14b,base_url=http://localhost:11434/v1` | Per-judge options: `model`, `base_url`, `api_key_env`, `timeout`, and any other constructor argument. |
| `my_package.judges:MyJudge` | Your own `Judge` subclass, optionally with `=key=value,...` options. |

## Judge panels

Two or more `--judge` options form a panel. Every member grades every pair in
parallel, and the panel combines the grades:

| `--aggregate` | Result |
| :--- | :--- |
| `majority` (default) | Most common grade. Ties go to the tied grade closest to the mean, then to the lower grade. |
| `mean` | Mean grade, rounded half up. |
| `median` | Median grade, rounded half up. |
| `min` / `max` | Strictest or most lenient member. |

A member that fails (timeout, bad response) does not sink the pair as long as
`--min-votes` members answered. The default is a strict majority of the panel.

```bash
export OPENAI_API_KEY=...
export OPENROUTER_API_KEY=...
llm-search-eval run ... \
  --judge openai=gpt-4o-mini \
  --judge "openai=meta-llama/llama-3.3-70b-instruct,base_url=https://openrouter.ai/api/v1,api_key_env=OPENROUTER_API_KEY" \
  --judge "openai=qwen2.5:14b,base_url=http://localhost:11434/v1" \
  --aggregate majority --cache .judge-cache.jsonl
```

The individual votes are stored in `judgments.jsonl` and in the cache, so
agreement statistics are available for cached pairs too.

## Inter-judge agreement

For a panel, the report includes:

| Statistic | Notes |
| :--- | :--- |
| Unanimous share | Pairs on which every member gave the same grade. |
| Fleiss' kappa | Chance-corrected agreement for any number of raters (nominal). |
| Krippendorff's alpha | Nominal, ordinal, and interval variants. Handles missing votes. The ordinal value is the most informative one for 0 to 3 grades. |
| Pairwise Cohen's kappa | Plain and quadratic-weighted kappa for every pair of members. |

As a rough guide, kappa or alpha above 0.8 is strong agreement, 0.6 to 0.8 is
substantial, and below 0.4 means the grading instructions or models need work.

## Calibration against gold labels

`--calibrate` also sends gold-labeled pairs to the judge so you can measure how
well it agrees with your human labels. Gold labels still decide the scores; the
extra judgments are only used for the agreement table. Limit the cost with
`--calibration-sample N`, which picks a reproducible random subset.

The gold agreement table reports, for the judge and for every panel member:

- exact agreement and agreement within one grade;
- binary agreement at the relevance threshold, which is what binary metrics see;
- Cohen's kappa and quadratic-weighted kappa;
- mean bias (positive means more lenient than the gold labels);
- a confusion matrix in `report.json` (rows are gold grades, columns are judge grades).

## Prompt versions

Every LLM judge prompt has a version and a hash. `PROMPT_VERSION` (`relevance-v1`) and `PAIRWISE_PROMPT_VERSION` (`pairwise-v1`) in `llm_search_eval.judges.prompts` are bumped by hand when a prompt changes. `PROMPT_HASH` and `PAIRWISE_PROMPT_HASH` are the first 12 hex characters of a SHA-256 over the rendered system prompt and the user prompt template, so they change on any edit to the text, even one where the version was not bumped.

The judge's provider (the host of its endpoint, for example `api.openai.com` or `localhost:11434`), model, prompt version, and prompt hash are written to:

- `report.json`, in `judging` and `pairwise` and in each pairwise comparison, and for a panel in `judging.panel.judges`, one entry per member;
- the Judges and Pairwise preference sections of `report.md` and the HTML dashboard;
- every new entry in the judgment cache and the pairwise cache, under `judge`.

The prompt version and hash are also part of the judge fingerprint, which is part of the cache key. A judgment made with a different prompt has a different key, so it is never served from the cache; the pair is judged again. Cache files written before 0.4.0 have keys without the hash, so their entries are judged again once after upgrading. The mock judges use no prompt, so their prompt fields are `null` and their cache keys are unchanged. Custom judges report `null` fields unless they override `info`.

## Python API

```python
from llm_search_eval import EvaluationConfig, JudgePanel, create_judge, evaluate

panel = JudgePanel(
    [create_judge("openai", model="gpt-4o-mini"), create_judge("openai", model="gpt-4o")],
    aggregation="mean",
)
report = evaluate(dataset, runs, EvaluationConfig(calibrate=True), judge=panel)
print(report.to_dict()["judging"]["gold_agreement"]["judge"]["weighted_kappa"])
```

The statistics are also available on their own in `llm_search_eval.agreement`:
`cohen_kappa`, `fleiss_kappa`, `krippendorff_alpha`, `inter_judge_agreement`, and
`gold_agreement`.
