# Data formats

Every file can be `.jsonl`, `.json`, `.csv`, or `.tsv`. Field names are case-insensitive.

**Queries**: `query_id` (alias `qid`), `text` (alias `query`), optional `lang`. Language is detected when omitted.

```json
{"query_id": "q06", "text": "هدفون بی سیم نویز کنسلینگ", "lang": "fa"}
```

**Products**: `product_id` (alias `id`, `doc_id`), `title` (alias `name`), optional `description`, `category`, `brand`, `price`, `attributes`. Any other column becomes an attribute that judges can see.

```json
{"product_id": "p06", "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", "brand": "Sony", "category": "Headphones"}
```

**Gold labels** (optional): `query_id`, `product_id`, `relevance` (alias `label`) on the graded scale below. TREC qrels files (`.qrels`, `.txt`) are also accepted.

| Grade | Meaning |
| :---: | :--- |
| 3 | Exact match: fully satisfies the query |
| 2 | Relevant: satisfies the main intent with minor gaps |
| 1 | Partially relevant: related, but misses key requirements |
| 0 | Irrelevant |

**System runs**: one file per system, passed as `--system NAME=PATH`. Any of these layouts work:

- one row per result with `query_id`, `product_id`, and `rank` (ascending) or `score` (descending); file order is used otherwise;
- one object per query: `{"query_id": "q1", "results": ["p3", "p1", "p7"]}`;
- TREC run files (`.trec`, `.run`): `qid Q0 docid rank score tag`.
