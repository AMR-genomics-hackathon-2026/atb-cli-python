from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

from atb_cli.constants import DEFAULT_SEQUENCE_URL_TEMPLATE
from atb_cli.download import download_sequences, iter_accessions, resolve_sequence_template
from atb_cli.io_utils import DataError
from atb_cli.registry import installed_db_path


def test_iter_accessions_prefers_sample_accession() -> None:
    frame = pd.DataFrame(
        {
            "sample_accession": ["SAMN1"],
            "accession": ["ACC1"],
        }
    )

    assert list(iter_accessions(frame)) == ["SAMN1"]


def test_download_sequences_supports_s3_gzip_template(monkeypatch, tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_fasta = tmp_path / "sequences.fasta"
    pd.DataFrame({"sample_accession": ["SAMN1"]}).to_csv(input_csv, index=False)

    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, content: bytes):
            self.status_code = 200
            self.content = content

    class FakeSession:
        def get(self, url: str, timeout: int):
            requested_urls.append(url)
            payload = gzip.compress(b">SAMN1\nACGT\n")
            return FakeResponse(payload)

    monkeypatch.setattr("atb_cli.download.requests.Session", lambda: FakeSession())

    count = download_sequences(
        input_csv,
        output_fasta,
        sequence_url_template="s3://allthebacteria-assemblies/<SAMPLE_ID>.fa.gz",
    )

    assert count == 1
    assert requested_urls == ["https://allthebacteria-assemblies.s3.amazonaws.com/SAMN1.fa.gz"]
    assert output_fasta.read_text(encoding="utf-8") == ">SAMN1\nACGT\n"


def test_resolve_sequence_template_falls_back_to_default_when_metadata_missing(monkeypatch) -> None:
    monkeypatch.setattr("atb_cli.download.current_version", lambda: "sylph")
    monkeypatch.setattr("atb_cli.download.get_local_release_metadata", lambda version: {"version": version, "sequence_url_template": None})

    template, resolved_version = resolve_sequence_template()

    assert template == DEFAULT_SEQUENCE_URL_TEMPLATE
    assert resolved_version == "sylph"


def test_download_sequences_uses_default_template_without_flag(monkeypatch, tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_fasta = tmp_path / "sequences.fasta"
    pd.DataFrame({"sample_accession": ["SAMN1"]}).to_csv(input_csv, index=False)

    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, content: bytes):
            self.status_code = 200
            self.content = content

    class FakeSession:
        def get(self, url: str, timeout: int):
            requested_urls.append(url)
            payload = gzip.compress(b">SAMN1\nACGT\n")
            return FakeResponse(payload)

    monkeypatch.setattr("atb_cli.download.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("atb_cli.download.current_version", lambda: "sylph")
    monkeypatch.setattr("atb_cli.download.get_local_release_metadata", lambda version: {"version": version, "sequence_url_template": None})

    count = download_sequences(input_csv, output_fasta)

    assert count == 1
    assert requested_urls == ["https://allthebacteria-assemblies.s3.amazonaws.com/SAMN1.fa.gz"]
    assert output_fasta.read_text(encoding="utf-8") == ">SAMN1\nACGT\n"


def test_download_sequences_uses_assembly_aws_url_for_sample_accession(monkeypatch, tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_fasta = tmp_path / "sequences.fasta"
    pd.DataFrame({"sample_accession": ["SAMN1"]}).to_csv(input_csv, index=False)

    assembly_path = installed_db_path("assembly")
    assembly_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "sample_accession": ["SAMN1"],
            "asm_fasta_on_osf": [1],
            "aws_url": ["https://allthebacteria-assemblies.s3.eu-west-2.amazonaws.com/SAMN1.fa.gz"],
        }
    ).to_parquet(assembly_path, index=False)

    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, content: bytes):
            self.status_code = 200
            self.content = content

    class FakeSession:
        def get(self, url: str, timeout: int):
            requested_urls.append(url)
            return FakeResponse(gzip.compress(b">SAMN1\nACGT\n"))

    monkeypatch.setattr("atb_cli.download.requests.Session", lambda: FakeSession())

    count = download_sequences(input_csv, output_fasta)

    assert count == 1
    assert requested_urls == ["https://allthebacteria-assemblies.s3.eu-west-2.amazonaws.com/SAMN1.fa.gz"]


def test_download_sequences_skips_missing_samples_when_some_are_available(monkeypatch, tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_fasta = tmp_path / "sequences.fasta"
    pd.DataFrame({"sample_accession": ["SAMN1", "SAMN2"]}).to_csv(input_csv, index=False)

    assembly_path = installed_db_path("assembly")
    assembly_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "sample_accession": ["SAMN1", "SAMN2"],
            "asm_fasta_on_osf": [1, 0],
            "aws_url": ["https://allthebacteria-assemblies.s3.eu-west-2.amazonaws.com/SAMN1.fa.gz", "NA"],
        }
    ).to_parquet(assembly_path, index=False)

    class FakeResponse:
        def __init__(self, status_code: int, content: bytes):
            self.status_code = status_code
            self.content = content

    class FakeSession:
        def get(self, url: str, timeout: int):
            if url.endswith("SAMN1.fa.gz"):
                return FakeResponse(200, gzip.compress(b">SAMN1\nACGT\n"))
            return FakeResponse(404, b"")

    monkeypatch.setattr("atb_cli.download.requests.Session", lambda: FakeSession())

    count = download_sequences(input_csv, output_fasta)

    assert count == 1
    assert output_fasta.read_text(encoding="utf-8") == ">SAMN1\nACGT\n"


def test_download_sequences_errors_when_all_selected_samples_are_missing(monkeypatch, tmp_path: Path) -> None:
    input_csv = tmp_path / "query_results.csv"
    output_fasta = tmp_path / "sequences.fasta"
    pd.DataFrame({"sample_accession": ["SAMN2"]}).to_csv(input_csv, index=False)

    assembly_path = installed_db_path("assembly")
    assembly_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "sample_accession": ["SAMN2"],
            "asm_fasta_on_osf": [0],
            "aws_url": ["NA"],
        }
    ).to_parquet(assembly_path, index=False)

    class FakeResponse:
        status_code = 404
        content = b""

    class FakeSession:
        def get(self, url: str, timeout: int):
            return FakeResponse()

    monkeypatch.setattr("atb_cli.download.requests.Session", lambda: FakeSession())

    with pytest.raises(DataError) as excinfo:
        download_sequences(input_csv, output_fasta)

    assert "No downloadable FASTA files were found" in str(excinfo.value)
