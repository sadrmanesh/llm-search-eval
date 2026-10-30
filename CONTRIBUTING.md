# Contributing to llm-search-eval

Thanks for taking the time to contribute. This guide covers the development setup and the conventions the project follows.

## Development setup

```bash
git clone https://github.com/sadrmanesh/llm-search-eval
cd llm-search-eval
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

Every pull request must pass the same checks that CI runs:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov
```

The test suite runs fully offline. Use the `mock` judge or a fake transport (see `tests/test_judges.py`) instead of calling a real API in tests. Connector tests use fake HTTP transports and fake clients (see `tests/test_connectors.py`), so no search cluster or Algolia account is needed. The `action` job in CI exercises `action.yml` end to end; if you change the action, run it on a branch in your fork.

## Conventions

- **Python 3.10+** with type hints checked by mypy. The package has no runtime dependencies; connector clients are optional extras and must stay optional.
- **Formatting and linting** are handled by ruff. Keep lines at 100 characters.
- **Tests** accompany every behavior change. Metric changes need hand-computed expectations.
- **Errors** raised for bad input should be subclasses of `LLMSearchEvalError` with messages that point to the file and record.
- **Prompts:** if you change the judge prompt, bump `PROMPT_VERSION` in `judges/prompts.py` so cached judgments from the old prompt are not reused.
- **Changelog:** add a line under `## [Unreleased]` in `CHANGELOG.md`.

## Adding a judge

1. Subclass `llm_search_eval.judges.Judge` and implement `judge(query, product) -> Judgment`.
2. Override `fingerprint` so it changes whenever the output could change (model, prompt, settings).
3. Make the judge thread safe; the evaluator calls it concurrently.
4. Register it with `@register_judge("name")` and add tests.

## Commit messages

Use the imperative mood and keep the subject under 72 characters, for example `Add recall@k to the summary table`. Reference issues in the body when relevant.

## Releases

See [docs/releasing.md](docs/releasing.md). In short: move the `[Unreleased]` entries into a new version section in `CHANGELOG.md`, bump the version in `pyproject.toml` and `src/llm_search_eval/__init__.py`, merge to `main`, and push a `vX.Y.Z` tag. The release workflow builds, checks, and publishes the package.

## Reporting issues

Please include the command you ran, the package version (`llm-search-eval --version`), and a minimal dataset that reproduces the problem.
