# Docker

Every release publishes a CLI image for `linux/amd64` and `linux/arm64` with the tags `X.Y.Z`, `X.Y`, and `latest`, to two registries with the same content:

| Registry | Image |
| :--- | :--- |
| Docker Hub | [`sadrmanesh/llm-search-eval`](https://hub.docker.com/r/sadrmanesh/llm-search-eval) |
| GitHub Container Registry | [`ghcr.io/sadrmanesh/llm-search-eval`](https://github.com/sadrmanesh/llm-search-eval/pkgs/container/llm-search-eval) |

The entry point is `llm-search-eval`, the working directory is `/work`, and the process runs as an unprivileged user (uid `10001`). Mount your data into `/work` and pass the same arguments as the installed CLI:

```bash
docker run --rm -v "$PWD:/work" sadrmanesh/llm-search-eval:0.3.2 run \
  -q eval/queries.jsonl -p eval/products.jsonl --qrels eval/qrels.csv \
  -s bm25=eval/runs/bm25.jsonl -s hybrid=eval/runs/hybrid.trec \
  --judge mock -o reports
```

The container must be able to write the output directory. If your user id is not `10001`, add `--user "$(id -u):$(id -g)"`.

LLM judges read their API key from the environment, so pass it through without putting it on the command line:

```bash
docker run --rm -v "$PWD:/work" -e OPENAI_API_KEY sadrmanesh/llm-search-eval:0.3.2 run \
  -q eval/queries.jsonl -p eval/products.jsonl --qrels eval/qrels.csv \
  -s production=eval/runs/production.jsonl -s candidate=eval/runs/candidate.jsonl \
  --judge openai=gpt-4o-mini --max-cost 2 -o reports
```

For a local model server such as Ollama or vLLM on the host, set `OPENAI_BASE_URL` and add `--add-host=host.docker.internal:host-gateway` on Linux.

The other commands work the same way, for example the quality gate:

```bash
docker run --rm -v "$PWD:/work" sadrmanesh/llm-search-eval:0.3.2 gate reports/report.json --min ndcg@10=0.55
```

## Build the image yourself

```bash
docker build -t llm-search-eval .
```

The connectors work over plain HTTP, so the image has no extras. To include the official clients, pass them at build time:

```bash
docker build --build-arg EXTRAS=elasticsearch,opensearch,algolia -t llm-search-eval .
```
