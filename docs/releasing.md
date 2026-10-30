# Releasing

Versions follow [Semantic Versioning](https://semver.org/). The version lives in
`pyproject.toml` and `src/llm_search_eval/__init__.py`, and the two must match.

## Steps

1. Move the `[Unreleased]` entries in `CHANGELOG.md` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section and update the links at the bottom.
2. Bump the version in both files.
3. Open a pull request and wait for CI.
4. After merging, tag the merge commit and push the tag:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

5. Create a GitHub release for the tag with the changelog section as notes.

## Publishing to PyPI

Pushing a `v*` tag runs `.github/workflows/release.yml`. It checks that the tag
matches the package version, builds the sdist and wheel, runs `twine check`,
and then publishes with the first method that is configured:

| Method | Setup |
| :--- | :--- |
| Trusted publishing (recommended) | Add this repository and the `release.yml` workflow with environment `pypi` as a trusted publisher on PyPI, then set the repository variable `PYPI_TRUSTED_PUBLISHING` to `true`. |
| API token | Add a PyPI token as the `PYPI_API_TOKEN` repository secret. |

When neither is configured, the publish job prints a notice and finishes
without uploading, so tagging never fails just because PyPI is not set up yet.
The built distributions are always available as the `dist` workflow artifact.

## Docker images

The same tag also builds the [Docker image](docker.md) for `linux/amd64` and
`linux/arm64` and pushes it to `ghcr.io/sadrmanesh/llm-search-eval` with the
built-in `GITHUB_TOKEN`. A second job copies every platform from GHCR to Docker
Hub with `docker buildx imagetools create`. It runs only when the
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets are set (a Docker
Hub access token with Read and Write scope) and skips with a notice otherwise.

## Mirrors

`.github/workflows/mirror.yml` pushes `main` and every tag to `gitlab.com/sadrmanesh/llm-search-eval`. It runs only when the `GITLAB_TOKEN` repository secret is set (a GitLab access token with the `write_repository` scope) and skips with a notice otherwise. Set the `GITLAB_NAMESPACE` repository variable to mirror to another GitLab namespace. GitHub stays the main repository for issues and pull requests.
