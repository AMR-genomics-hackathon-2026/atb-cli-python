"""Filter parsing and application for query TOML files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .io_utils import ConfigError

SUPPORTED_OPS = {
    "eq",
    "ne",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "contains",
    "startswith",
    "endswith",
    "is_null",
    "not_null",
}

_DATE_LIKE_RE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?(?:[T ][^ ]+)?(?:Z|[+-]\d{2}:\d{2})?$")


@dataclass(slots=True)
class FilterRule:
    column: str
    op: str
    value: Any = None



def parse_filters(config: dict[str, Any]) -> list[FilterRule]:
    filters = config.get("filters", [])
    if not isinstance(filters, list):
        raise ConfigError("Query config must contain a [[filters]] array")

    rules: list[FilterRule] = []
    for index, item in enumerate(filters, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"Filter #{index} must be a table")
        column = item.get("column")
        op = item.get("op")
        value = item.get("value")
        if not column or not isinstance(column, str):
            raise ConfigError(f"Filter #{index} is missing a string column")
        if op not in SUPPORTED_OPS:
            allowed = ", ".join(sorted(SUPPORTED_OPS))
            raise ConfigError(f"Unsupported op in filter #{index}: {op!r}. Allowed: {allowed}")
        if op in {"between", "in", "not_in"} and value is None:
            raise ConfigError(f"Filter #{index} with op={op!r} requires a value")
        rules.append(FilterRule(column=column, op=op, value=value))
    return rules



def _coerce_date_like(series: pd.Series, value: Any) -> tuple[pd.Series, Any]:
    if pd.api.types.is_datetime64_any_dtype(series):
        if isinstance(value, list):
            return series, [pd.to_datetime(v) for v in value]
        return series, pd.to_datetime(value)
    if _is_date_like_value(value):
        parsed = pd.to_datetime(series, errors="coerce")
        if parsed.notna().any():
            if isinstance(value, list):
                return parsed, [pd.to_datetime(v) for v in value]
            return parsed, pd.to_datetime(value)
    return series, value



def _is_date_like_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_DATE_LIKE_RE.fullmatch(value))
    if isinstance(value, list) and value:
        return all(isinstance(item, str) and _DATE_LIKE_RE.fullmatch(item) for item in value)
    return False



def apply_rule(frame: pd.DataFrame, rule: FilterRule) -> pd.Series:
    if rule.column not in frame.columns:
        raise ConfigError(f"Column {rule.column!r} not found in parquet data")
    series = frame[rule.column]
    series, value = _coerce_date_like(series, rule.value)

    if rule.op == "eq":
        return series == value
    if rule.op == "ne":
        return series != value
    if rule.op == "in":
        return series.isin(value)
    if rule.op == "not_in":
        return ~series.isin(value)
    if rule.op == "gt":
        return series > value
    if rule.op == "gte":
        return series >= value
    if rule.op == "lt":
        return series < value
    if rule.op == "lte":
        return series <= value
    if rule.op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise ConfigError(f"between filter on {rule.column!r} requires a 2-item list")
        return series.between(value[0], value[1])
    if rule.op == "contains":
        return series.astype(str).str.contains(str(value), na=False, regex=False)
    if rule.op == "startswith":
        return series.astype(str).str.startswith(str(value), na=False)
    if rule.op == "endswith":
        return series.astype(str).str.endswith(str(value), na=False)
    if rule.op == "is_null":
        return series.isna()
    if rule.op == "not_null":
        return series.notna()
    raise ConfigError(f"Unhandled filter op {rule.op!r}")



def apply_filters(frame: pd.DataFrame, rules: list[FilterRule]) -> pd.DataFrame:
    if not rules:
        return frame.copy()
    mask = pd.Series(True, index=frame.index)
    for rule in rules:
        mask &= apply_rule(frame, rule)
    return frame.loc[mask].copy()



def project_and_order(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    select = config.get("select")
    if select:
        missing = [column for column in select if column not in frame.columns]
        if missing:
            raise ConfigError(f"Selected columns not found in result: {', '.join(missing)}")
        frame = frame.loc[:, select]

    if config.get("distinct", False):
        frame = frame.drop_duplicates()

    sort_by = config.get("sort_by", [])
    if sort_by:
        missing = [column for column in sort_by if column not in frame.columns]
        if missing:
            raise ConfigError(f"Sort columns not found in result: {', '.join(missing)}")
        frame = frame.sort_values(by=sort_by)

    limit = config.get("limit")
    if limit is not None:
        frame = frame.head(int(limit))

    return frame.reset_index(drop=True)
