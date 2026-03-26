from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atb_cli.cli import cli


def test_versions_command_without_state() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["versions"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["current_version"] is None
    assert payload["installed"] is False


def test_help_lists_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "fetch" in result.output
    assert "query" in result.output
    assert "summarise" in result.output


def test_fetch_command_downloads_all_osf_parquet_files(monkeypatch, tmp_path) -> None:
    downloads: list[tuple[str, str]] = []
    current = {"version": None}

    monkeypatch.setattr(
        "atb_cli.cli.load_registry",
        lambda registry: {
            "latest": "2026-03-01",
            "versions": {
                "2026-02-01": {
                    "parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-2",
                    "release_date": "2026-02-02T12:34:56Z",
                },
                "2026-03-01": {
                    "parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-3",
                    "release_date": "2026-03-02T12:34:56Z",
                },
            },
        },
    )
    monkeypatch.setattr("atb_cli.cli.is_osf_source", lambda registry: True)

    def fake_fetch_release(release, *, force: bool = False) -> Path:
        target = tmp_path / release.version / "atb.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(release.parquet_url, encoding="utf-8")
        downloads.append((release.version, str(target.resolve())))
        current["version"] = release.version
        return target

    monkeypatch.setattr("atb_cli.release_workflow.fetch_release", fake_fetch_release)
    monkeypatch.setattr("atb_cli.cli.set_current_version", lambda version: current.__setitem__("version", version))
    monkeypatch.setattr("atb_cli.cli.current_version", lambda: current["version"])

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["count"] == 2
    assert payload["current_version"] == "2026-03-01"
    assert [item["version"] for item in payload["fetched"]] == ["2026-02-01", "2026-03-01"]
    assert downloads == [
        ("2026-02-01", str((tmp_path / "2026-02-01" / "atb.parquet").resolve())),
        ("2026-03-01", str((tmp_path / "2026-03-01" / "atb.parquet").resolve())),
    ]


def test_update_command_downloads_only_newer_osf_parquet_files(monkeypatch, tmp_path) -> None:
    downloads: list[tuple[str, str]] = []
    current = {"version": "2026-02-01"}

    monkeypatch.setattr(
        "atb_cli.cli.load_registry",
        lambda registry: {
            "latest": "2026-04-01",
            "versions": {
                "2026-02-01": {
                    "parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-2",
                    "release_date": "2026-02-02T12:34:56Z",
                },
                "2026-03-01": {
                    "parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-3",
                    "release_date": "2026-03-02T12:34:56Z",
                },
                "2026-04-01": {
                    "parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-4",
                    "release_date": "2026-04-02T12:34:56Z",
                },
            },
        },
    )
    monkeypatch.setattr("atb_cli.cli.is_osf_source", lambda registry: True)
    monkeypatch.setattr("atb_cli.cli.current_version", lambda: current["version"])

    def fake_fetch_release(release, *, force: bool = False) -> Path:
        target = tmp_path / release.version / "atb.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(release.parquet_url, encoding="utf-8")
        downloads.append((release.version, str(target.resolve())))
        current["version"] = release.version
        return target

    monkeypatch.setattr("atb_cli.release_workflow.fetch_release", fake_fetch_release)
    monkeypatch.setattr("atb_cli.cli.set_current_version", lambda version: current.__setitem__("version", version))

    runner = CliRunner()
    result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "updated"
    assert payload["count"] == 2
    assert payload["current_version"] == "2026-04-01"
    assert [item["version"] for item in payload["fetched"]] == ["2026-03-01", "2026-04-01"]
    assert downloads == [
        ("2026-03-01", str((tmp_path / "2026-03-01" / "atb.parquet").resolve())),
        ("2026-04-01", str((tmp_path / "2026-04-01" / "atb.parquet").resolve())),
    ]


def test_update_command_reports_up_to_date_for_current_osf_release(monkeypatch) -> None:
    monkeypatch.setattr(
        "atb_cli.cli.load_registry",
        lambda registry: {
            "latest": "2026-04-01",
            "versions": {
                "2026-03-01": {"parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-3"},
                "2026-04-01": {"parquet_url": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-4"},
            },
        },
    )
    monkeypatch.setattr("atb_cli.cli.is_osf_source", lambda registry: True)
    monkeypatch.setattr("atb_cli.cli.current_version", lambda: "2026-04-01")

    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch_release should not be called when already up to date")

    monkeypatch.setattr("atb_cli.cli.fetch_release", fail_fetch)

    runner = CliRunner()
    result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {"status": "up-to-date", "version": "2026-04-01"}
