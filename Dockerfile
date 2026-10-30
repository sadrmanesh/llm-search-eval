# syntax=docker/dockerfile:1

# Build the wheel from the source tree.
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src ./src
RUN python -m build --wheel --outdir /wheels

# Runtime: the CLI only, run as a non-root user in /work.
FROM python:3.12-slim AS runtime
# The connectors and judges work over plain HTTP, so no extras are needed.
# Add official clients at build time if you want them, for example:
#   docker build --build-arg EXTRAS=elasticsearch,opensearch .
ARG EXTRAS=""
LABEL org.opencontainers.image.title="llm-search-eval" \
      org.opencontainers.image.description="Evaluate product search quality with IR metrics, LLM judges, cost tracking, and CI quality gates" \
      org.opencontainers.image.source="https://github.com/sadrmanesh/llm-search-eval" \
      org.opencontainers.image.url="https://sadrmanesh.github.io/llm-search-eval/" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Naser Sadrmanesh <info.sadrmanesh@gmail.com>"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=build /wheels /tmp/wheels
RUN wheel="$(ls /tmp/wheels/*.whl)" \
    && if [ -n "${EXTRAS}" ]; then pip install "${wheel}[${EXTRAS}]"; else pip install "${wheel}"; fi \
    && rm -rf /tmp/wheels \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /work \
    && chown app:app /work
USER app
WORKDIR /work
ENTRYPOINT ["llm-search-eval"]
CMD ["--help"]
