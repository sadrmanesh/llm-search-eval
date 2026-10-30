"""Loading datasets and system runs from JSONL, JSON, CSV/TSV, and TREC files.

Field names are matched case-insensitively and a few common aliases are accepted
(``qid`` for ``query_id``, ``doc_id`` for ``product_id``, ``label`` for
``relevance``) so that existing evaluation data can be reused without rewriting.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from llm_search_eval.errors import DatasetError
from llm_search_eval.models import MAX_RELEVANCE, MIN_RELEVANCE, Dataset, Product, Qrels, Query, Run
from llm_search_eval.text import detect_language

log = logging.getLogger(__name__)

_QUERY_ID = ("query_id", "qid", "queryid", "query-id")
_PRODUCT_ID = ("product_id", "pid", "doc_id", "docid", "item_id", "id")
_QUERY_TEXT = ("text", "query", "query_text", "q")
_TITLE = ("title", "name", "product_name")
_RELEVANCE = ("relevance", "label", "grade", "rel")
_PRODUCT_FIELDS = {"description", "category", "brand", "price", "attributes"}


Record = dict[str, Any]


def _lower_keys(record: Mapping[str, Any]) -> Record:
    return {str(k).strip().lower(): v for k, v in record.items()}


def _pick(record: Record, names: Iterable[str]) -> tuple[str | None, Any]:
    for name in names:
        value = record.get(name)
        if value is not None and value != "":
            return name, value
    return None, None


def _require(record: Record, names: tuple[str, ...], what: str, where: str) -> str:
    _, value = _pick(record, names)
    if value is None:
        raise DatasetError(f"{where}: missing {what} (expected one of: {', '.join(names)})")
    return str(value).strip()


def read_records(path: str | Path) -> list[Record]:
    """Read a list of records from ``.jsonl``, ``.json``, ``.csv`` or ``.tsv``."""
    path = Path(path)
    if not path.is_file():
        raise DatasetError(f"{path}: file not found")
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        return list(_read_jsonl(path))
    if suffix == ".json":
        return _read_json(path)
    if suffix in {".csv", ".tsv"}:
        return _read_csv(path, delimiter="\t" if suffix == ".tsv" else ",")
    raise DatasetError(f"{path}: unsupported file type {suffix!r} (use .jsonl, .json, .csv, .tsv)")


def _read_jsonl(path: Path) -> Iterator[Record]:
    with path.open(encoding="utf-8-sig") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise DatasetError(f"{path}:{lineno}: expected a JSON object per line")
            yield _lower_keys(obj)


def _read_json(path: Path) -> list[Record]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path}: invalid JSON ({exc.msg} at line {exc.lineno})") from exc
    if isinstance(data, dict):
        # Accept {"records": [...]} or a single top-level list under any one key.
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) != 1:
            raise DatasetError(f"{path}: expected a JSON array of objects")
        data = lists[0]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise DatasetError(f"{path}: expected a JSON array of objects")
    return [_lower_keys(x) for x in data]


def _read_csv(path: Path, delimiter: str) -> list[Record]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if reader.fieldnames is None:
            return []
        return [_lower_keys({k: v for k, v in row.items() if k is not None}) for row in reader]


def load_queries(path: str | Path) -> dict[str, Query]:
    queries: dict[str, Query] = {}
    for i, rec in enumerate(read_records(path), start=1):
        where = f"{path} record {i}"
        qid = _require(rec, _QUERY_ID, "query id", where)
        text = _require(rec, _QUERY_TEXT, "query text", where)
        lang = str(rec.get("lang") or rec.get("language") or "").strip() or detect_language(text)
        if qid in queries:
            raise DatasetError(f"{where}: duplicate query id {qid!r}")
        queries[qid] = Query(query_id=qid, text=text, lang=lang)
    if not queries:
        raise DatasetError(f"{path}: no queries found")
    return queries


def _parse_attributes(rec: Record, used: set[str]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    raw = rec.get("attributes")
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, Mapping):
        attrs.update({str(k): _scalar(v) for k, v in raw.items()})
    for key, value in rec.items():
        if key not in used and key not in _PRODUCT_FIELDS and value not in (None, ""):
            attrs[key] = _scalar(value)
    return attrs


def _scalar(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def load_products(path: str | Path) -> dict[str, Product]:
    products: dict[str, Product] = {}
    for i, rec in enumerate(read_records(path), start=1):
        where = f"{path} record {i}"
        id_key, pid = _pick(rec, _PRODUCT_ID)
        title_key, title = _pick(rec, _TITLE)
        if pid is None:
            raise DatasetError(f"{where}: missing product id (expected one of: product_id, id)")
        if title is None:
            raise DatasetError(f"{where}: missing product title")
        pid = str(pid).strip()
        if pid in products:
            raise DatasetError(f"{where}: duplicate product id {pid!r}")
        products[pid] = Product(
            product_id=pid,
            title=str(title).strip(),
            description=_scalar(rec.get("description") or ""),
            category=_scalar(rec.get("category") or ""),
            brand=_scalar(rec.get("brand") or ""),
            price=_scalar(rec.get("price") or ""),
            attributes=_parse_attributes(rec, {id_key or "", title_key or ""}),
        )
    if not products:
        raise DatasetError(f"{path}: no products found")
    return products


def parse_relevance(value: Any, where: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{where}: relevance {value!r} is not a number") from exc
    if not number.is_integer() or not MIN_RELEVANCE <= number <= MAX_RELEVANCE:
        raise DatasetError(
            f"{where}: relevance must be an integer in [{MIN_RELEVANCE}, {MAX_RELEVANCE}], "
            f"got {value!r}"
        )
    return int(number)


def load_qrels(path: str | Path) -> Qrels:
    """Load graded relevance labels. TREC qrels (``qid 0 docid rel``) are also accepted."""
    path = Path(path)
    if path.suffix.lower() in {".qrels", ".txt"}:
        return _load_trec_qrels(path)
    qrels: Qrels = {}
    for i, rec in enumerate(read_records(path), start=1):
        where = f"{path} record {i}"
        qid = _require(rec, _QUERY_ID, "query id", where)
        pid = _require(rec, _PRODUCT_ID, "product id", where)
        _, rel = _pick(rec, _RELEVANCE)
        qrels.setdefault(qid, {})[pid] = parse_relevance(rel, where)
    return qrels


def _load_trec_qrels(path: Path) -> Qrels:
    if not path.is_file():
        raise DatasetError(f"{path}: file not found")
    qrels: Qrels = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 4:
            raise DatasetError(f"{path}:{lineno}: expected 'qid iter docid relevance'")
        qid, _, pid, rel = parts
        qrels.setdefault(qid, {})[pid] = parse_relevance(rel, f"{path}:{lineno}")
    return qrels


def load_run(path: str | Path, name: str | None = None) -> Run:
    """Load ranked results for one system.

    Supported layouts:

    * one row per result with ``query_id``, ``product_id`` and either ``rank``
      (ascending) or ``score`` (descending); file order is used when neither exists;
    * one JSON object per query with ``query_id`` and a ``results`` list of ids;
    * TREC run files (``.trec`` / ``.run``): ``qid Q0 docid rank score tag``.
    """
    path = Path(path)
    name = name or path.stem
    if path.suffix.lower() in {".trec", ".run"}:
        rows = _read_trec_run(path)
    else:
        rows = []
        for i, rec in enumerate(read_records(path), start=1):
            where = f"{path} record {i}"
            qid = _require(rec, _QUERY_ID, "query id", where)
            results = rec.get("results")
            if results is not None:
                if isinstance(results, str):
                    results = [r for r in (s.strip() for s in results.split("|")) if r]
                if not isinstance(results, list):
                    raise DatasetError(f"{where}: 'results' must be a list of product ids")
                for pos, item in enumerate(results, start=1):
                    pid = item.get("product_id") if isinstance(item, dict) else item
                    rows.append((qid, str(pid), float(pos), None, len(rows)))
                continue
            pid = _require(rec, _PRODUCT_ID, "product id", where)
            rows.append(
                (
                    qid,
                    pid,
                    _number(rec.get("rank"), where),
                    _number(rec.get("score"), where),
                    len(rows),
                )
            )
    return Run(name=name, rankings=_rank(rows, path))


def _number(value: Any, where: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{where}: {value!r} is not a number") from exc


def _read_trec_run(path: Path) -> list[tuple[str, str, float | None, float | None, int]]:
    if not path.is_file():
        raise DatasetError(f"{path}: file not found")
    rows: list[tuple[str, str, float | None, float | None, int]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 5:
            raise DatasetError(f"{path}:{lineno}: expected 'qid Q0 docid rank score [tag]'")
        where = f"{path}:{lineno}"
        rows.append(
            (parts[0], parts[2], _number(parts[3], where), _number(parts[4], where), len(rows))
        )
    return rows


def _rank(
    rows: list[tuple[str, str, float | None, float | None, int]], path: Path
) -> dict[str, list[str]]:
    grouped: dict[str, list[tuple[str, float | None, float | None, int]]] = {}
    for qid, pid, rank, score, order in rows:
        grouped.setdefault(qid, []).append((pid, rank, score, order))
    rankings: dict[str, list[str]] = {}
    for qid, items in grouped.items():
        if all(rank is not None for _, rank, _, _ in items):
            items.sort(key=lambda x: (x[1], x[3]))
        elif all(score is not None for _, _, score, _ in items):
            items.sort(key=lambda x: (-x[2], x[3]))  # type: ignore[operator]
        else:
            items.sort(key=lambda x: x[3])
        seen: set[str] = set()
        ranked: list[str] = []
        for pid, *_ in items:
            if pid in seen:
                log.warning("%s: duplicate product %r for query %r ignored", path, pid, qid)
                continue
            seen.add(pid)
            ranked.append(pid)
        rankings[qid] = ranked
    return rankings


def load_dataset(
    queries: str | Path, products: str | Path, qrels: str | Path | None = None
) -> Dataset:
    return Dataset(
        queries=load_queries(queries),
        products=load_products(products),
        qrels=load_qrels(qrels) if qrels else {},
    )


def write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_run(path: str | Path, run: Run) -> Path:
    """Write a run as JSONL, one row per query: ``{"query_id": ..., "results": [...]}``.

    The output loads back with :func:`load_run`. A ``.trec`` or ``.run`` suffix
    writes the TREC run format instead.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        if path.suffix.lower() in {".trec", ".run"}:
            tag = run.name.replace(" ", "_") or "run"
            for qid, ranked in run.rankings.items():
                for rank, pid in enumerate(ranked, start=1):
                    fh.write(f"{qid} Q0 {pid} {rank} {len(ranked) - rank + 1} {tag}\n")
        else:
            for qid, ranked in run.rankings.items():
                fh.write(json.dumps({"query_id": qid, "results": ranked}, ensure_ascii=False))
                fh.write("\n")
    return path
