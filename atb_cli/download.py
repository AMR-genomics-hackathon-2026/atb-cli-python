"""Sequence download support."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import pandas as pd
import requests

from .constants import DEFAULT_ACCESSION_COLUMNS, DEFAULT_SEQUENCE_URL_TEMPLATE, DEFAULT_TIMEOUT_SECONDS
from .io_utils import DataError, RemoteError
from .registry import current_version, get_local_release_metadata, installed_db_path


@dataclass(slots=True)
class SequenceDownloadPlan:
    accession_column: str
    accessions: list[str]
    url_template: str
    assembly_urls: dict[str, str]



def resolve_sequence_template(version: str | None = None, template: str | None = None) -> tuple[str, str | None]:
    if template:
        return template, version

    selected_version = version or current_version()
    if not selected_version:
        return DEFAULT_SEQUENCE_URL_TEMPLATE, None

    try:
        metadata = get_local_release_metadata(selected_version)
    except DataError:
        metadata = {}

    sequence_template = metadata.get("sequence_url_template")
    if not sequence_template:
        return DEFAULT_SEQUENCE_URL_TEMPLATE, selected_version
    return str(sequence_template), selected_version



def detect_accession_column(frame: pd.DataFrame) -> str:
    for candidate in DEFAULT_ACCESSION_COLUMNS:
        if candidate in frame.columns:
            return candidate
    available = ", ".join(frame.columns)
    raise DataError(
        "Could not detect an accession/sample-id column in the CSV. "
        f"Expected one of {DEFAULT_ACCESSION_COLUMNS}, found: {available}"
    )



def iter_accessions(frame: pd.DataFrame, accession_column: str | None = None, max_samples: int | None = None) -> Iterable[str]:
    column = accession_column or detect_accession_column(frame)
    if column not in frame.columns:
        raise DataError(f"Column {column!r} not found in CSV")
    values = frame[column].dropna().astype(str).tolist()
    if max_samples is not None:
        values = values[:max_samples]
    return values


def _is_truthy_flag(value: object) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "na", "nan", "none"}
    return bool(value)


def _load_assembly_aws_urls(sample_accessions: list[str]) -> dict[str, str]:
    assembly_path = installed_db_path("assembly")
    if not assembly_path.exists() or not sample_accessions:
        return {}

    assembly = pd.read_parquet(
        assembly_path,
        columns=["sample_accession", "asm_fasta_on_osf", "aws_url"],
        filters=[("sample_accession", "in", sample_accessions)],
    )
    urls: dict[str, str] = {}
    for row in assembly.itertuples(index=False):
        sample_accession = getattr(row, "sample_accession", None)
        aws_url = getattr(row, "aws_url", None)
        if not isinstance(sample_accession, str) or not sample_accession:
            continue
        if sample_accession in urls:
            continue
        if not _is_truthy_flag(getattr(row, "asm_fasta_on_osf", None)):
            continue
        if not isinstance(aws_url, str) or not aws_url or aws_url == "NA":
            continue
        urls[sample_accession] = aws_url
    return urls


def _build_download_plan(
    frame: pd.DataFrame,
    *,
    accession_column: str | None,
    version: str | None,
    sequence_url_template: str | None,
    max_samples: int | None,
) -> SequenceDownloadPlan:
    column = accession_column or detect_accession_column(frame)
    accessions = list(iter_accessions(frame, column, max_samples=max_samples))
    if not accessions:
        raise DataError("No accessions found to download")

    url_template, _ = resolve_sequence_template(version=version, template=sequence_url_template)
    assembly_urls = _load_assembly_aws_urls(accessions) if column == "sample_accession" else {}
    return SequenceDownloadPlan(
        accession_column=column,
        accessions=accessions,
        url_template=url_template,
        assembly_urls=assembly_urls,
    )


def _render_sequence_url(template: str, accession: str) -> str:
    rendered = template.replace("<SAMPLE_ID>", accession)
    try:
        rendered = rendered.format(
            accession=accession,
            sample_id=accession,
            sample_accession=accession,
            id=accession,
            run_accession=accession,
        )
    except KeyError as exc:
        raise DataError(f"Unknown placeholder in sequence URL template: {exc.args[0]!r}") from exc
    return _s3_url_to_https(rendered)


def _s3_url_to_https(url: str) -> str:
    prefix = "s3://"
    if not url.startswith(prefix):
        return url

    remainder = url[len(prefix) :]
    bucket, _, key = remainder.partition("/")
    if not bucket or not key:
        raise DataError(f"Invalid S3 sequence URL: {url!r}")
    return f"https://{bucket}.s3.amazonaws.com/{quote(key, safe='/._-')}"


def _decode_sequence_payload(payload: bytes, url: str) -> str:
    if url.endswith(".gz"):
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:
            raise RemoteError(f"Downloaded gzip sequence payload for {url!r} could not be decompressed") from exc
    return payload.decode("utf-8").strip()



def download_sequences(
    input_csv: Path,
    output_fasta: Path,
    *,
    accession_column: str | None = None,
    version: str | None = None,
    sequence_url_template: str | None = None,
    max_samples: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    if not input_csv.exists():
        raise DataError(f"CSV file not found: {input_csv}")

    frame = pd.read_csv(input_csv)
    plan = _build_download_plan(
        frame,
        accession_column=accession_column,
        version=version,
        sequence_url_template=sequence_url_template,
        max_samples=max_samples,
    )
    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped_missing: list[str] = []
    with output_fasta.open("w", encoding="utf-8") as handle:
        session = requests.Session()
        for accession in plan.accessions:
            url = plan.assembly_urls.get(accession) or _render_sequence_url(plan.url_template, accession)
            response = session.get(url, timeout=timeout)
            if response.status_code != 200:
                if response.status_code == 404:
                    skipped_missing.append(accession)
                    continue
                raise RemoteError(f"Failed to download sequence for {accession!r}: HTTP {response.status_code}")
            content = _decode_sequence_payload(response.content, url)
            if not content:
                continue
            if not content.startswith(">"):
                content = f">{accession}\n{content}"
            handle.write(content)
            handle.write("\n")
            count += 1
    if count == 0 and skipped_missing:
        missing_preview = ", ".join(skipped_missing[:5])
        raise DataError(
            "No downloadable FASTA files were found for the selected samples. "
            f"Missing examples: {missing_preview}"
        )
    return count
