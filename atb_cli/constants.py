"""Constants used by the ATB CLI."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "atb-cli"
DEFAULT_REGISTRY_URL = "https://osf.io/h7wzy/files/osfstorage"
DEFAULT_SEQUENCE_URL_TEMPLATE = "s3://allthebacteria-assemblies/<SAMPLE_ID>.fa.gz"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TOP_N = 20
DEFAULT_ACCESSION_COLUMNS = ("sample_accession", "accession", "sample_id", "id", "run_accession")
DEFAULT_QUERY_OUTPUT = "query_results.csv"
DEFAULT_SUMMARY_OUTPUT = "summary.json"
DEFAULT_PROVENANCE_OUTPUT = "query_provenance.json"
DEFAULT_PIPELINE_DIR = "atb_run"
ENV_HOME = "ATB_CLI_HOME"


def default_home() -> Path:
    return Path.home() / ".local" / "share" / APP_NAME
