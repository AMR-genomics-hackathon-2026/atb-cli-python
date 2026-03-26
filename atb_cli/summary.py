"""Summary statistics for query result CSV files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_toml
from .constants import DEFAULT_SUMMARY_OUTPUT, DEFAULT_TOP_N
from .io_utils import DataError, write_json

DEFAULT_DATE_COLUMNS = ["collection_date"]
DEFAULT_CATEGORICAL_COLUMNS = ["country", "instrument_platform", "scientific_name", "library_strategy"]



def _existing_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]



def _missing_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {column: int(value) for column, value in frame.isna().sum().to_dict().items()}



def _top_values(frame: pd.DataFrame, column: str, *, top_n: int) -> dict[str, int]:
    counts = frame[column].dropna().astype(str).value_counts().head(top_n)
    return {str(key): int(value) for key, value in counts.to_dict().items()}


def _value_distribution_summary(frame: pd.DataFrame, column: str, *, top_n: int) -> dict[str, Any]:
    return {
        "non_null": int(frame[column].notna().sum()),
        "unique": int(frame[column].nunique(dropna=True)),
        "top_values": _top_values(frame, column, top_n=top_n),
    }


def _date_column_summary(frame: pd.DataFrame, column: str) -> dict[str, Any] | None:
    parsed = pd.to_datetime(frame[column], errors="coerce")
    if not parsed.notna().any():
        return None
    return {
        "non_null": int(parsed.notna().sum()),
        "min": parsed.min().date().isoformat(),
        "max": parsed.max().date().isoformat(),
    }



def build_summary(frame: pd.DataFrame, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    summary_section = config.get("summary", {})
    top_n = int(summary_section.get("top_n", DEFAULT_TOP_N))
    date_columns = _existing_columns(frame, summary_section.get("date_columns", DEFAULT_DATE_COLUMNS))
    categorical_columns = _existing_columns(frame, summary_section.get("categorical_columns", DEFAULT_CATEGORICAL_COLUMNS))

    id_column = summary_section.get("id_column")
    if id_column and id_column not in frame.columns:
        raise DataError(f"Configured id_column {id_column!r} does not exist in the CSV")

    summary: dict[str, Any] = {
        "total_rows": int(len(frame)),
        "columns": list(frame.columns),
        "missing_values": _missing_counts(frame),
    }
    if id_column:
        summary["unique_ids"] = int(frame[id_column].nunique(dropna=True))

    date_stats: dict[str, Any] = {}
    for column in date_columns:
        summary_for_column = _date_column_summary(frame, column)
        if summary_for_column is not None:
            date_stats[column] = summary_for_column
    if date_stats:
        summary["date_columns"] = date_stats

    categorical_stats: dict[str, Any] = {}
    for column in categorical_columns:
        categorical_stats[column] = _value_distribution_summary(frame, column, top_n=top_n)
    if categorical_stats:
        summary["categorical_columns"] = categorical_stats

    custom_columns = summary_section.get("custom_columns", [])
    custom_stats: dict[str, Any] = {}
    for column in custom_columns:
        if column not in frame.columns:
            continue
        custom_stats[column] = _value_distribution_summary(frame, column, top_n=top_n)
    if custom_stats:
        summary["custom_columns"] = custom_stats

    return summary



def run_summary(input_csv: Path, *, config_path: Path | None = None, output_json: Path | None = None) -> dict[str, Any]:
    if not input_csv.exists():
        raise DataError(f"CSV file not found: {input_csv}")
    frame = pd.read_csv(input_csv)
    config = load_toml(config_path) if config_path else None
    summary = build_summary(frame, config)
    output_json = output_json or Path(DEFAULT_SUMMARY_OUTPUT)
    write_json(output_json, summary)
    return summary
