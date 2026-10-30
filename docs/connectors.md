# Live search connectors

Supported backends: Elasticsearch, OpenSearch, Algolia, Meilisearch, Typesense,
and any HTTP API that answers with JSON.

`llm-search-eval fetch` sends every query to a running search backend and saves
the ranked product ids as a run file that `run` can score. Requests go over
plain HTTP with the standard library, so no extra package is needed.

## Elasticsearch and OpenSearch

```bash
export ELASTICSEARCH_API_KEY=...      # or --username with ELASTICSEARCH_PASSWORD
llm-search-eval fetch \
  --backend elasticsearch --url https://search.example.com:9200 --index products \
  --queries eval/queries.jsonl -k 20 -o runs/es-current.jsonl
```

By default the connector sends a `multi_match` query over
`title^3,brand^2,category,description`; change the fields with `--fields`. To
evaluate your real production query, put the request body in a JSON file and
pass `--template`:

```json
{
  "size": "{{k}}",
  "query": {
    "bool": {
      "must": {"multi_match": {"query": "{{query}}", "fields": ["title^3", "title.fa^3", "brand"]}},
      "filter": {"term": {"in_stock": true}}
    }
  }
}
```

The placeholders `{{query}}`, `{{k}}`, `{{lang}}`, and `{{query_id}}` are filled in
for every query. A placeholder that makes up a whole JSON string keeps the
value's type, so `"{{k}}"` becomes a number. Product ids come from the document
`_id`, or from a source field set with `--id-field`.

OpenSearch works the same way with `--backend opensearch`, reading
`OPENSEARCH_API_KEY` or `OPENSEARCH_PASSWORD`.

## Algolia

```bash
export ALGOLIA_APP_ID=...
export ALGOLIA_API_KEY=...   # a search-only key is enough
llm-search-eval fetch --backend algolia --index products \
  --queries eval/queries.jsonl -k 20 --params '{"filters": "in_stock:true"}' \
  -o runs/algolia.jsonl
```

Product ids come from `objectID` unless `--id-field` names another attribute.

## Meilisearch

```bash
export MEILI_API_KEY=...     # a search key; MEILISEARCH_API_KEY also works
llm-search-eval fetch --backend meilisearch --url http://localhost:7700 --index products \
  --queries eval/queries.jsonl -k 20 --params '{"filter": "in_stock = true"}' \
  -o runs/meili.jsonl
```

The URL defaults to `MEILI_URL` and then `http://localhost:7700`. Product ids
come from the `id` attribute unless `--id-field` names another one. `--params`
is merged into the search request, so filters, `attributesToSearchOn`, or a
`hybrid` block for semantic search can be evaluated as they are served.

## Typesense

```bash
export TYPESENSE_API_KEY=...
llm-search-eval fetch --backend typesense --url http://localhost:8108 --index products \
  --query-by title,brand,description --queries eval/queries.jsonl -k 20 \
  -o runs/typesense.jsonl
```

`--index` is the collection name, and `--query-by` lists the fields to search
(default `title,description`). The URL defaults to `TYPESENSE_URL` and then
`http://localhost:8108`. Each query is sent through the multi search endpoint;
Typesense returns at most 250 hits per page, so `-k` above 250 is rejected.
Extra search parameters such as `filter_by` or `sort_by` go in `--params`.

## Any HTTP/JSON search API

Internal search services rarely speak a standard protocol. The `http` backend
describes the request and the response without code:

```bash
export SEARCH_TOKEN=...
llm-search-eval fetch --backend http \
  --url 'https://search.internal/v2/search?q={{query}}&size={{k}}&lang={{lang}}' \
  --header 'Authorization:Bearer ${SEARCH_TOKEN}' \
  --results-path data.hits --id-path product.sku \
  --queries eval/queries.jsonl -k 20 -o runs/internal.jsonl
```

- `--url` is the full request URL. Placeholders in it are URL-encoded.
- `--method POST` (or `PUT`) with `--body request.json` sends a JSON body
  template with the same placeholders as the Elasticsearch template.
- `--header NAME:VALUE` is repeatable; `${NAME}` in a value is read from the
  environment, and a missing variable is an error, so secrets never end up in
  shell history or in an empty header.
- `--results-path` is the dotted path to the list of results in the response
  (default `results`); numbers select list items, as in `data.0.hits`.
- `--id-path` is the dotted path to the product id inside one result
  (default `id`).

## Options

| Option | Description |
| :--- | :--- |
| `-k` | Results per query (default 10). |
| `--concurrency` | Parallel requests (default 4). |
| `--timeout` | Seconds per request. Rate limits and server errors are retried with backoff. |
| `-o` | Output file. `.jsonl` writes one object per query; `.trec` or `.run` writes a TREC run. |

Queries that fail are reported and left out of the run file, and the command
exits with code `3`, so a partial fetch is never mistaken for a complete one.

## Python API and official clients

```python
from llm_search_eval.connectors import ElasticsearchConnector, fetch_run
from llm_search_eval.io import load_queries, write_run

connector = ElasticsearchConnector("http://localhost:9200", "products", fields=["title^2", "brand"])
result = fetch_run(connector, load_queries("eval/queries.jsonl"), k=20, name="es")
write_run("runs/es.jsonl", result.run)
```

To reuse a configured official client (for example with cloud authentication),
install the matching extra and pass the client:

```bash
pip install "llm-search-eval[elasticsearch]"   # or [opensearch], [algolia]
```

```python
from elasticsearch import Elasticsearch

connector = ElasticsearchConnector(
    index="products", client=Elasticsearch(cloud_id=..., api_key=...)
)
```

For Algolia, pass an `algoliasearch.search.client.SearchClientSync`.
`MeilisearchConnector`, `TypesenseConnector` and `HTTPJSONConnector` use only
the standard library. Custom
backends only need to subclass `SearchConnector` and implement
`search(query, k) -> list[str]`.
