from __future__ import annotations

from pathlib import Path

import pandas as pd

from atb_cli.summary import run_summary


def test_example_summary_config_runs_against_query_output_columns(tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_json = tmp_path / "summary.json"

    pd.DataFrame(
        {
            "sample_accession": ["SAMN1", "SAMN2", "SAMN2"],
            "collection_date": ["2024-01-15", "2024-08-10", "2024-08-10"],
            "country": ["USA", "United Kingdom", "United Kingdom"],
            "instrument_platform": ["ILLUMINA", "ILLUMINA", "ILLUMINA"],
            "scientific_name": ["Escherichia coli", "Salmonella enterica", "Salmonella enterica"],
            "host": ["Homo sapiens", "Homo sapiens", "Homo sapiens"],
            "library_strategy": ["WGS", "WGS", "WGS"],
        }
    ).to_csv(input_csv, index=False)

    summary = run_summary(
        input_csv,
        config_path=Path("examples/summarise.toml"),
        output_json=output_json,
    )

    assert summary["unique_ids"] == 2
    assert "collection_date" in summary["date_columns"]
    assert "country" in summary["categorical_columns"]
    assert "instrument_platform" in summary["categorical_columns"]
    assert "scientific_name" in summary["categorical_columns"]
    assert "host" in summary["custom_columns"]
    assert "library_strategy" in summary["custom_columns"]
