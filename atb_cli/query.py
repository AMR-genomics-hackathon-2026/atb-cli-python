"""Query execution over local parquet data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from . import __version__
from .config import canonical_json, config_digest, load_toml
from .constants import DEFAULT_PROVENANCE_OUTPUT, DEFAULT_QUERY_OUTPUT
from .filters import apply_filters, parse_filters, project_and_order
from .io_utils import DataError, get_app_home, write_json
from .registry import current_version, get_local_release_metadata, installed_db_path

QUERY_OPTION_KEYS = ("select", "sort_by", "distinct", "limit")
_DATE_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(slots=True)
class QueryResult:
    output_csv: Path
    provenance_json: Path
    row_count: int
    version: str


@dataclass(slots=True)
class ResolvedDatabase:
    path: Path
    version: str
    columns: set[str]



def _required_query_columns(query_config: dict[str, Any]) -> set[str]:
    columns: set[str] = set()

    filters = query_config.get("filters", [])
    if isinstance(filters, list):
        for item in filters:
            if not isinstance(item, dict):
                continue
            column = item.get("column")
            if isinstance(column, str) and column:
                columns.add(column)

    for key in ("select", "sort_by"):
        values = query_config.get(key, [])
        if isinstance(values, list):
            columns.update(value for value in values if isinstance(value, str) and value)

    return columns


def _read_parquet_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def _missing_columns(required_columns: set[str], available_columns: set[str]) -> str:
    return ", ".join(sorted(required_columns - available_columns))


def _installed_database_candidates(required_columns: set[str]) -> list[ResolvedDatabase]:
    db_root = get_app_home() / "db"
    matches: list[ResolvedDatabase] = []
    if not db_root.exists():
        return matches

    for candidate in db_root.iterdir():
        path = candidate / "atb.parquet"
        if not candidate.is_dir() or not path.exists():
            continue
        columns = _read_parquet_columns(path)
        if required_columns.issubset(columns):
            matches.append(ResolvedDatabase(path=path, version=candidate.name, columns=columns))

    def sort_key(item: ResolvedDatabase) -> tuple[int, int, str]:
        is_date_version = 1 if _DATE_VERSION_RE.fullmatch(item.version) else 0
        matched_columns = len(required_columns & item.columns)
        return (is_date_version, matched_columns, item.version)

    return sorted(matches, key=sort_key, reverse=True)


def resolve_db(
    version: str | None = None,
    db_path: Path | None = None,
    *,
    query_config: dict[str, Any] | None = None,
) -> ResolvedDatabase:
    if db_path:
        if not db_path.exists():
            raise DataError(f"Database path does not exist: {db_path}")
        return ResolvedDatabase(path=db_path, version=version or "custom", columns=_read_parquet_columns(db_path))

    required_columns = _required_query_columns(query_config or {})
    selected_version = version or current_version()
    if selected_version:
        path = installed_db_path(selected_version)
        if path.exists():
            columns = _read_parquet_columns(path)
            if not required_columns or required_columns.issubset(columns):
                return ResolvedDatabase(path=path, version=selected_version, columns=columns)
            if version:
                raise DataError(
                    f"Version {selected_version!r} does not contain the required query columns: "
                    f"{_missing_columns(required_columns, columns)}."
                )
        elif version:
            raise DataError(f"Version {selected_version!r} is not installed. Run `atb fetch --version {selected_version}`.")

    matches = _installed_database_candidates(required_columns)
    if matches:
        return matches[0]

    if not selected_version:
        raise DataError("No local database available. Run `atb fetch` first or pass --db-path.")

    path = installed_db_path(selected_version)
    if path.exists():
        columns = _read_parquet_columns(path)
        raise DataError(
            f"Current version {selected_version!r} does not contain the required query columns: "
            f"{_missing_columns(required_columns, columns)}. "
            "Pass --version or --db-path to target a compatible parquet file."
        )
    raise DataError(f"Version {selected_version!r} is not installed. Run `atb fetch --version {selected_version}`.")


def resolve_db_path(
    version: str | None = None,
    db_path: Path | None = None,
    *,
    query_config: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    resolved = resolve_db(version=version, db_path=db_path, query_config=query_config)
    return resolved.path, resolved.version


def normalize_query_config(query_config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(query_config)
    filters = normalized.get("filters", [])
    if not isinstance(filters, list):
        return normalized

    normalized_filters: list[Any] = []
    hoisted: dict[str, Any] = {}
    for item in filters:
        if not isinstance(item, dict):
            normalized_filters.append(item)
            continue

        filter_item = dict(item)
        for key in QUERY_OPTION_KEYS:
            if key not in filter_item:
                continue
            if key not in normalized and key not in hoisted:
                hoisted[key] = filter_item[key]
            filter_item.pop(key, None)
        normalized_filters.append(filter_item)

    normalized["filters"] = normalized_filters
    for key, value in hoisted.items():
        normalized[key] = value
    return normalized



def run_query(
    *,
    filters_path: Path,
    output_csv: Path | None = None,
    provenance_json: Path | None = None,
    version: str | None = None,
    db_path: Path | None = None,
    extra_limit: int | None = None,
) -> QueryResult:
    query_config = normalize_query_config(load_toml(filters_path))
    rules = parse_filters(query_config)
    resolved_db = resolve_db(version=version, db_path=db_path, query_config=query_config)

    frame = pd.read_parquet(resolved_db.path)
    filtered = apply_filters(frame, rules)
    projected = project_and_order(filtered, query_config)
    if extra_limit is not None:
        projected = projected.head(extra_limit).reset_index(drop=True)

    output_csv = output_csv or Path(DEFAULT_QUERY_OUTPUT)
    provenance_json = provenance_json or Path(DEFAULT_PROVENANCE_OUTPUT)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    provenance_json.parent.mkdir(parents=True, exist_ok=True)

    projected.to_csv(output_csv, index=False)

    metadata: dict[str, Any] = {
        "cli_version": __version__,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "query_config_path": str(filters_path.resolve()),
        "query_config_sha256": config_digest(filters_path),
        "query_config": query_config,
        "query_config_canonical_json": canonical_json(query_config),
        "database_path": str(resolved_db.path.resolve()),
        "database_version": resolved_db.version,
        "result_csv": str(output_csv.resolve()),
        "row_count": int(len(projected)),
    }
    if extra_limit is not None:
        metadata["extra_limit"] = int(extra_limit)
    if resolved_db.version != "custom":
        metadata["database_release"] = get_local_release_metadata(resolved_db.version)
    write_json(provenance_json, metadata)

    return QueryResult(
        output_csv=output_csv,
        provenance_json=provenance_json,
        row_count=int(len(projected)),
        version=resolved_db.version,
    )
