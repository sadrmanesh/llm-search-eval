# Quality gates in CI

## The `gate` command

`llm-search-eval gate` reads a `report.json`, checks it against thresholds,
prints a Markdown table of the checks, and exits with `1` when any check fails.

```bash
llm-search-eval gate reports/report.json \
  --min ndcg@10=0.60 --min recall@10=0.70 \
  --max-drop 0.01 \
  --summary "$GITHUB_STEP_SUMMARY"
```

| Option | Meaning |
| :--- | :--- |
| `--min METRIC=VALUE` | The mean of the metric must be at least VALUE for every checked system. Repeatable. |
| `--max-drop X` | A metric may not fall by more than X (absolute). |
| `--max-relative-drop X` | A metric may not fall by more than X as a fraction, for example `0.02` for 2%. |
| `--metric M` | Metrics for the drop checks. Repeatable. Defaults to the primary metric. |
| `--reference OLD.json` | Compare each system with the same system in an earlier report instead of with the baseline system. |
| `--significant-only` | Fail on a drop only when the paired randomization test gives p below `--alpha` (default 0.05). |
| `--system NAME` | Check only these systems. Repeatable. |
| `--summary FILE` / `--json FILE` | Append the Markdown table to a file and write the results as JSON. |

Without `--reference`, drops are measured from the baseline system in the same
report, which fits a pull request that adds a candidate system next to the
current one. With `--reference`, keep a `report.json` from the default branch
(for example as an artifact or in the repository) and compare against it.

Exit codes: `0` passed, `1` a check failed, `2` invalid input.

## GitHub Action

The repository is also a composite GitHub Action. It installs the tool, runs the
evaluation, applies the gate, writes the gate result and the full report to
the job summary, and posts or updates a comment on the pull request (see
[Pull request comments](pr-comments.md)).

```yaml
name: Search quality
on: pull_request

permissions:
  contents: read
  pull-requests: write   # for the report comment

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/cache@v4
        with:
          path: .judge-cache.jsonl
          key: judge-cache-${{ github.run_id }}
          restore-keys: judge-cache-

      - name: Evaluate rankings
        id: search-eval
        uses: sadrmanesh/llm-search-eval@v0.3.0
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        with:
          queries: eval/queries.jsonl
          products: eval/products.jsonl
          qrels: eval/qrels.csv
          systems: |
            production=eval/runs/production.jsonl
            candidate=eval/runs/candidate.jsonl
          judges: |
            openai=gpt-4o-mini
          cache: .judge-cache.jsonl
          prices: |
            gpt-4o-mini=0.15,0.60
          max-cost: "2"
          pairwise-judge: openai=gpt-4o-mini
          sample: "300"
          stratify: segment
          min: |
            ndcg@10=0.55
          max-drop: "0.01"
          significant-only: "true"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: search-evaluation
          path: ${{ steps.search-eval.outputs.report-dir }}
```

### Inputs

| Input | Default | Description |
| :--- | :--- | :--- |
| `queries`, `products` | required | Dataset files. |
| `qrels` | | Gold labels. |
| `systems` | required | One `NAME=PATH` per line; the first is the baseline unless `baseline` is set. |
| `judges` | | One judge spec per line; two or more form a panel. |
| `aggregate` | `majority` | Panel aggregation. |
| `calibrate` | `false` | Judge gold pairs too and report agreement with gold. |
| `cache` | | Judgment cache path. |
| `prices` | | One `MODEL=INPUT,OUTPUT` per line. |
| `max-cost`, `max-tokens`, `max-judgments` | | Budget limits (see [Cost and budgets](cost.md)). |
| `pairwise-judge` | | Pairwise judge spec; turns on [pairwise comparison](pairwise.md). |
| `pairwise` | | Pairs to compare, one `A:B` per line. Defaults to each system against the baseline. |
| `metrics`, `primary`, `baseline`, `permutations`, `title` | | Evaluation settings. |
| `bootstrap`, `confidence` | `1000`, `0.95` | [Confidence intervals](statistics.md); `0` resamples turns them off. |
| `sample`, `stratify` | | [Query sampling](sampling.md): a count, fraction or percentage, and a query field. |
| `args` | | Extra `run` arguments, one per line. |
| `min` | | One `METRIC=VALUE` floor per line. |
| `max-drop`, `max-relative-drop` | | Regression limits. |
| `reference` | | Earlier `report.json` to compare against. |
| `gate-metrics` | | Metrics for the drop checks, one per line. |
| `significant-only` | `false` | Ignore drops that are not significant. |
| `fail-on-regression` | `true` | Fail the step when the gate fails. |
| `comment` | `true` | Post or update a pull request comment with the gate result and the report. |
| `comment-id` | `report` | Comment identity; jobs with different ids keep separate comments. |
| `github-token` | `${{ github.token }}` | Token for the comment. Needs `pull-requests: write`. |
| `output-dir` | `llm-search-eval-report` | Report directory. |
| `python-version` | `3.12` | Python used by the action. |
| `package` | the action's own version | pip requirement to install instead. |

### Outputs

| Output | Description |
| :--- | :--- |
| `report-dir` | Directory with all reports. |
| `report-json`, `report-html` | Paths to `report.json` and the dashboard. |
| `passed` | `true` when every gate check passed or no gate was configured. |
| `comment-url` | Link to the pull request comment, when one was posted. |

API keys are read from the environment of the step, as in the example above.

To check the cost before a paid run, call `llm-search-eval estimate` with the
same options in an earlier step; it exits with `1` when the budget is too
small.
