# Pull request comments

The GitHub Action posts the gate result and the report as a comment on the
pull request, and updates that same comment on every new push instead of
adding another one. The comment is found by a hidden marker
(`<!-- llm-search-eval:report -->`).

## Permissions

Posting a comment needs write access to pull requests. Grant it in the
workflow or job:

```yaml
permissions:
  contents: read
  pull-requests: write
```

Without it, the comment step prints a warning and the job continues; the job
summary still has the full report.

## Pull requests from forks

On the `pull_request` event, workflows triggered from a fork get a read-only
token, so the comment is skipped with a warning. The safe options are:

- accept that fork pull requests only get the job summary;
- or post the comment from a separate workflow triggered by `workflow_run`,
  which has a write token and only downloads the report artifact.

Do not switch to `pull_request_target` just to get a comment: it runs with a
write token and secrets, and checking out the fork's code in that context lets
the pull request run arbitrary code with those permissions.

## Inputs

| Input | Default | Description |
| :--- | :--- | :--- |
| `comment` | `true` | Post or update the comment on `pull_request` events. Set `false` to turn it off. |
| `comment-id` | `report` | Comment identity. Jobs with different ids (for example one per locale) keep separate comments. |
| `github-token` | `${{ github.token }}` | Token used to post. |

The `comment-url` output holds the link to the comment when one was posted.

## From the command line

The same feature is available outside the action, for example in another CI
system:

```bash
export GITHUB_TOKEN=...
llm-search-eval comment reports/gate.md reports/report.md --repo owner/name --pr 42
```

In GitHub Actions, `--repo` and `--pr` come from the environment. `--id`
selects the comment identity, `--dry-run` prints the comment instead of
posting it, and `--strict` turns a skipped comment into an error. Comments
longer than GitHub's limit of 65536 characters are cut at a line break with a
note pointing to the job summary.
