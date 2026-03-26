from __future__ import annotations

import pandas as pd

from atb_cli.filters import apply_filters, parse_filters, project_and_order


def test_parse_and_apply_filters() -> None:
    config = {
        "filters": [
            {"column": "country", "op": "in", "value": ["UK", "FR"]},
            {"column": "value", "op": "gte", "value": 2},
        ]
    }
    frame = pd.DataFrame(
        {
            "sample_id": ["a", "b", "c"],
            "country": ["UK", "DE", "FR"],
            "value": [1, 2, 3],
        }
    )

    rules = parse_filters(config)
    result = apply_filters(frame, rules)

    assert result["sample_id"].tolist() == ["c"]


def test_project_and_order() -> None:
    frame = pd.DataFrame(
        {
            "sample_id": ["b", "a", "a"],
            "collection_date": ["2024-01-02", "2024-01-01", "2024-01-01"],
            "country": ["UK", "FR", "FR"],
        }
    )
    config = {
        "select": ["sample_id", "collection_date"],
        "distinct": True,
        "sort_by": ["collection_date", "sample_id"],
    }

    result = project_and_order(frame, config)

    assert result.to_dict(orient="records") == [
        {"sample_id": "a", "collection_date": "2024-01-01"},
        {"sample_id": "b", "collection_date": "2024-01-02"},
    ]


def test_apply_filters_coerces_date_like_string_columns() -> None:
    config = {
        "filters": [
            {"column": "collection_date", "op": "between", "value": ["2024-01-01", "2024-01-31"]},
        ]
    }
    frame = pd.DataFrame(
        {
            "sample_accession": ["a", "b", "c"],
            "collection_date": ["2024-01-15", "2024-02-01", "not-a-date"],
        }
    )

    rules = parse_filters(config)
    result = apply_filters(frame, rules)

    assert result["sample_accession"].tolist() == ["a"]
