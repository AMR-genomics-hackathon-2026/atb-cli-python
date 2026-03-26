"""Click-based CLI entry point for ATB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from . import __version__
from .constants import DEFAULT_PIPELINE_DIR, DEFAULT_REGISTRY_URL
from .download import download_sequences
from .io_utils import AtbCliError, write_json
from .query import run_query
from .release_workflow import fetch_versions, versions_for_default_fetch, versions_for_update
from .registry import (
    current_version,
    get_local_release_metadata,
    installed_db_path,
    is_osf_source,
    is_installed,
    latest_version,
    load_registry,
    resolve_release,
    set_current_version,
    fetch_release,
)
from .summary import run_summary


class OrderedGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@click.group(cls=OrderedGroup)
@click.version_option(version=__version__, prog_name="atb")
def cli() -> None:
    """Versioned, reproducible CLI tooling for querying ATB parquet releases."""



def _emit(payload: dict[str, Any]) -> None:
    click.echo(json.dumps(payload, indent=2, sort_keys=True))



def _source_help() -> str:
    return (
        "Release source: local/remote registry JSON, or an OSF storage page URL. "
        f"Defaults to {DEFAULT_REGISTRY_URL}"
    )


def _fetched_payload(downloaded) -> list[dict[str, str]]:
    return [item.to_payload() for item in downloaded]


@cli.command("fetch")
@click.option("--version", "db_version", help="ATB release version to use")
@click.option("--registry", help=_source_help())
@click.option("--force", is_flag=True, help="Re-download even if already installed")
def fetch_cmd(db_version: str | None, registry: str | None, force: bool) -> None:
    """Fetch a parquet release from the configured source."""
    registry_data = load_registry(registry)
    source_is_osf = is_osf_source(registry)
    if db_version is None:
        downloaded = fetch_versions(
            registry_data,
            versions_for_default_fetch(registry_data, osf_source=source_is_osf),
            force=force,
        )
        if source_is_osf:
            set_current_version(latest_version(registry_data))
            _emit({"count": len(downloaded), "current_version": current_version(), "fetched": _fetched_payload(downloaded)})
            return

        downloaded_release = downloaded[0]
        _emit(downloaded_release.to_payload())
        return

    release = resolve_release(registry_data, db_version)
    path = fetch_release(release, force=force)
    _emit({"version": release.version, "parquet_path": str(path.resolve())})


@cli.command("update")
@click.option("--registry", help=_source_help())
@click.option("--force", is_flag=True, help="Re-download even if already current")
def update_cmd(registry: str | None, force: bool) -> None:
    """Fetch the latest release if it is newer than the current one."""
    registry_data = load_registry(registry)
    remote_latest = latest_version(registry_data)
    local_current = current_version()
    source_is_osf = is_osf_source(registry)
    versions_to_fetch = versions_for_update(
        registry_data,
        local_current=local_current,
        force=force,
        osf_source=source_is_osf,
    )
    if not versions_to_fetch:
        _emit({"status": "up-to-date", "version": remote_latest})
        return

    if source_is_osf:
        downloaded = fetch_versions(registry_data, versions_to_fetch, force=force)
        set_current_version(remote_latest)
        _emit(
            {
                "status": "updated",
                "count": len(downloaded),
                "current_version": current_version(),
                "fetched": _fetched_payload(downloaded),
            }
        )
        return

    release = resolve_release(registry_data, remote_latest)
    path = fetch_release(release, force=force)
    _emit({"status": "updated", "version": release.version, "parquet_path": str(path.resolve())})


@cli.command("versions")
@click.option("--version", "db_version", help="ATB release version to inspect")
def versions_cmd(db_version: str | None) -> None:
    """Show current and installed release metadata."""
    version = db_version or current_version()
    payload: dict[str, Any] = {
        "current_version": current_version(),
        "requested_version": version,
        "installed": bool(version and is_installed(version)),
    }
    if version and is_installed(version):
        payload["metadata"] = get_local_release_metadata(version)
        payload["parquet_path"] = str(installed_db_path(version).resolve())
    _emit(payload)


@cli.command("query")
@click.option("--filters", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Path to TOML query filters")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=Path("query_results.csv"), show_default=True, help="Output CSV path")
@click.option("--provenance", type=click.Path(dir_okay=False, path_type=Path), default=Path("query_provenance.json"), show_default=True, help="Output JSON containing query provenance")
@click.option("--version", "db_version", help="ATB release version to use")
@click.option("--db-path", type=click.Path(exists=False, dir_okay=False, path_type=Path), help="Explicit parquet database path")
def query_cmd(filters: Path, output: Path, provenance: Path, db_version: str | None, db_path: Path | None) -> None:
    """Run a reproducible query against the local parquet release."""
    result = run_query(
        filters_path=filters,
        output_csv=output,
        provenance_json=provenance,
        version=db_version,
        db_path=db_path,
    )
    _emit(
        {
            "status": "ok",
            "database_version": result.version,
            "rows": result.row_count,
            "output_csv": str(result.output_csv.resolve()),
            "provenance_json": str(result.provenance_json.resolve()),
        }
    )


@cli.command("summarise")
@click.option("--input", "input_csv", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Input CSV path")
@click.option("--config", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Optional TOML summary config")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=Path("summary.json"), show_default=True, help="Output JSON path")
def summarise_cmd(input_csv: Path, config: Path | None, output: Path) -> None:
    """Generate summary statistics for a query result CSV."""
    summary = run_summary(input_csv, config_path=config, output_json=output)
    _emit(summary)


@cli.command("download")
@click.option("--input", "input_csv", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Input CSV path")
@click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path), help="Output FASTA path")
@click.option("--accession-column", help="CSV column to use for accession/sample ID")
@click.option("--sequence-url-template", help="Template like https://host/{accession}.fasta")
@click.option("--version", "db_version", help="ATB release version to use")
@click.option("--max-samples", type=int, help="Limit the number of downloaded samples")
def download_cmd(
    input_csv: Path,
    output: Path,
    accession_column: str | None,
    sequence_url_template: str | None,
    db_version: str | None,
    max_samples: int | None,
) -> None:
    """Download sequences for sample IDs/accessions in a CSV."""
    count = download_sequences(
        input_csv,
        output,
        accession_column=accession_column,
        version=db_version,
        sequence_url_template=sequence_url_template,
        max_samples=max_samples,
    )
    _emit({"status": "ok", "downloaded": count, "output_fasta": str(output.resolve())})


@cli.command("run")
@click.option("--filters", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Path to TOML query filters")
@click.option("--summary-config", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Optional TOML summary config")
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path), default=Path(DEFAULT_PIPELINE_DIR), show_default=True, help="Output directory")
@click.option("--download", "download_enabled", is_flag=True, help="Also download sequences")
@click.option("--sequence-url-template", help="Template like https://host/{accession}.fasta")
@click.option("--accession-column", help="CSV column to use for accession/sample ID")
@click.option("--version", "db_version", help="ATB release version to use")
@click.option("--db-path", type=click.Path(exists=False, dir_okay=False, path_type=Path), help="Explicit parquet database path")
@click.option("--max-samples", type=int, help="Limit records in pipeline and downloads")
def run_cmd(
    filters: Path,
    summary_config: Path | None,
    output_dir: Path,
    download_enabled: bool,
    sequence_url_template: str | None,
    accession_column: str | None,
    db_version: str | None,
    db_path: Path | None,
    max_samples: int | None,
) -> None:
    """Run query, summarise, and optionally download in a single reproducible pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)

    query_output = output_dir / "query_results.csv"
    provenance_output = output_dir / "query_provenance.json"
    summary_output = output_dir / "summary.json"
    pipeline_output = output_dir / "pipeline.json"
    fasta_output = output_dir / "sequences.fasta"

    query_result = run_query(
        filters_path=filters,
        output_csv=query_output,
        provenance_json=provenance_output,
        version=db_version,
        db_path=db_path,
        extra_limit=max_samples,
    )

    summary = run_summary(query_output, config_path=summary_config, output_json=summary_output)
    payload: dict[str, Any] = {
        "status": "ok",
        "cli_version": __version__,
        "output_dir": str(output_dir.resolve()),
        "database_version": query_result.version,
        "rows": query_result.row_count,
        "max_samples": max_samples,
        "summary_json": str(summary_output.resolve()),
        "query_csv": str(query_output.resolve()),
        "provenance_json": str(provenance_output.resolve()),
        "summary_preview": {
            "total_rows": summary.get("total_rows"),
            "date_columns": summary.get("date_columns", {}),
        },
    }

    if download_enabled:
        downloaded = download_sequences(
            query_output,
            fasta_output,
            accession_column=accession_column,
            version=db_version,
            sequence_url_template=sequence_url_template,
            max_samples=max_samples,
        )
        payload["downloaded_sequences"] = downloaded
        payload["output_fasta"] = str(fasta_output.resolve())

    write_json(pipeline_output, payload)
    _emit(payload)



def main() -> None:
    try:
        cli()
    except AtbCliError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
