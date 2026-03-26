from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from atb_cli.io_utils import DataError
from atb_cli.query import normalize_query_config, run_query
from atb_cli.registry import installed_db_path, set_current_version


def test_normalize_query_config_hoists_query_options_from_filter_entries() -> None:
    query_config = {
        "filters": [
            {"column": "country", "op": "eq", "value": "UK"},
            {
                "column": "collection_date",
                "op": "not_null",
                "select": ["sample_id", "collection_date"],
                "sort_by": ["collection_date", "sample_id"],
                "distinct": True,
                "limit": 2,
            },
        ]
    }

    normalized = normalize_query_config(query_config)

    assert normalized["select"] == ["sample_id", "collection_date"]
    assert normalized["sort_by"] == ["collection_date", "sample_id"]
    assert normalized["distinct"] is True
    assert normalized["limit"] == 2
    assert normalized["filters"] == [
        {"column": "country", "op": "eq", "value": "UK"},
        {"column": "collection_date", "op": "not_null"},
    ]


def test_run_query_applies_hoisted_query_options(tmp_path: Path) -> None:
    parquet_path = tmp_path / "db.parquet"
    filters_path = tmp_path / "query.toml"
    output_csv = tmp_path / "result.csv"
    provenance_json = tmp_path / "provenance.json"

    pd.DataFrame(
        {
            "sample_id": ["b", "a", "a", "z"],
            "collection_date": ["2024-01-02", "2024-01-01", "2024-01-01", "2024-01-03"],
            "country": ["UK", "UK", "UK", "DE"],
        }
    ).to_parquet(parquet_path, index=False)

    filters_path.write_text(
        "\n".join(
            [
                "[[filters]]",
                'column = "country"',
                'op = "eq"',
                'value = "UK"',
                "",
                "[[filters]]",
                'column = "collection_date"',
                'op = "not_null"',
                'select = ["sample_id", "collection_date"]',
                'sort_by = ["collection_date", "sample_id"]',
                "distinct = true",
                "limit = 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_query(
        filters_path=filters_path,
        output_csv=output_csv,
        provenance_json=provenance_json,
        db_path=parquet_path,
    )

    output = pd.read_csv(output_csv)
    provenance = json.loads(provenance_json.read_text(encoding="utf-8"))

    assert result.row_count == 1
    assert output.to_dict(orient="records") == [{"sample_id": "a", "collection_date": "2024-01-01"}]
    assert provenance["database_version"] == "custom"
    assert provenance["query_config"]["select"] == ["sample_id", "collection_date"]
    assert provenance["query_config"]["limit"] == 1


def test_example_query_toml_runs_against_main_atb_style_schema(tmp_path: Path) -> None:
    parquet_path = tmp_path / "db.parquet"
    output_csv = tmp_path / "result.csv"
    provenance_json = tmp_path / "provenance.json"

    pd.DataFrame(
        {
            "sample_accession": ["SAMN1", "SAMN2", "SAMN3"],
            "run_accession": ["SRR1", "SRR2", "SRR3"],
            "accession": ["ACC1", "ACC2", "ACC3"],
            "collection_date": ["2024-01-15", "2024-08-10", "2023-12-31"],
            "country": ["USA", "United Kingdom", "France"],
            "scientific_name": ["Escherichia coli", "Salmonella enterica", "Escherichia coli"],
            "host": ["Homo sapiens", "Homo sapiens", "Gallus gallus"],
            "instrument_platform": ["ILLUMINA", "ILLUMINA", "OXFORD_NANOPORE"],
            "library_strategy": ["WGS", "WGS", "WGS"],
        }
    ).to_parquet(parquet_path, index=False)

    result = run_query(
        filters_path=Path("examples/query.toml"),
        output_csv=output_csv,
        provenance_json=provenance_json,
        db_path=parquet_path,
    )

    output = pd.read_csv(output_csv)

    assert result.row_count == 2
    assert list(output.columns) == [
        "sample_accession",
        "run_accession",
        "accession",
        "collection_date",
        "country",
        "scientific_name",
        "host",
        "instrument_platform",
        "library_strategy",
    ]
    assert output["sample_accession"].tolist() == ["SAMN1", "SAMN2"]


def test_run_query_uses_compatible_installed_version_when_current_is_auxiliary(monkeypatch, tmp_path: Path) -> None:
    main_path = installed_db_path("2025-05-06")
    sylph_path = installed_db_path("sylph")
    main_path.parent.mkdir(parents=True, exist_ok=True)
    sylph_path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        {
            "sample_accession": ["SAMN1"],
            "run_accession": ["SRR1"],
            "accession": ["ACC1"],
            "collection_date": ["2024-01-15"],
            "country": ["USA"],
            "scientific_name": ["Escherichia coli"],
            "host": ["Homo sapiens"],
            "instrument_platform": ["ILLUMINA"],
            "library_strategy": ["WGS"],
        }
    ).to_parquet(main_path, index=False)
    pd.DataFrame(
        {
            "sample_accession": ["SAMN1"],
            "run_accession": ["SRR1"],
            "Species": ["Escherichia coli"],
        }
    ).to_parquet(sylph_path, index=False)

    set_current_version("sylph")
    monkeypatch.setattr("atb_cli.query.get_local_release_metadata", lambda version: {"version": version})

    result = run_query(
        filters_path=Path("examples/query.toml"),
        output_csv=tmp_path / "query_results.csv",
        provenance_json=tmp_path / "query_provenance.json",
    )

    assert result.version == "2025-05-06"
    assert result.row_count == 1


def test_run_query_reports_explicit_version_schema_mismatch(monkeypatch, tmp_path: Path) -> None:
    sylph_path = installed_db_path("sylph")
    sylph_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "sample_accession": ["SAMN1"],
            "run_accession": ["SRR1"],
            "Species": ["Escherichia coli"],
        }
    ).to_parquet(sylph_path, index=False)
    monkeypatch.setattr("atb_cli.query.get_local_release_metadata", lambda version: {"version": version})

    with pytest.raises(DataError) as excinfo:
        run_query(
            filters_path=Path("examples/query.toml"),
            output_csv=tmp_path / "query_results.csv",
            provenance_json=tmp_path / "query_provenance.json",
            version="sylph",
        )

    assert "does not contain the required query columns" in str(excinfo.value)
    assert "country" in str(excinfo.value)
