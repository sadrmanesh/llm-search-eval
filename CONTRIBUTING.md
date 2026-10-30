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
pytest --cov
```

The test suite runs fully offline. Use the `mock` judge or a fake transport (see `tests/test_judges.py`) instead of calling a real API in tests.

## Conventions

- **Python 3.10+** with type hints on public functions. The package has no runtime dependencies; please discuss before adding one.
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

1. Move the `[Unreleased]` entries into a new version section in `CHANGELOG.md`.
2. Bump `version` in `pyproject.toml` and `__version__` in `src/llm_search_eval/__init__.py`.
3. Merge to `main`, tag `vX.Y.Z`, and publish a GitHub release with the changelog section as notes.

## Reporting issues

Please include the command you ran, the package version (`llm-search-eval --version`), and a minimal dataset that reproduces the problem.
