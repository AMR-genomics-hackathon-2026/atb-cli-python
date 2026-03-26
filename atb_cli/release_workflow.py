"""Higher-level release fetch/update workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .registry import fetch_release, latest_version, ordered_versions, resolve_release


@dataclass(slots=True)
class DownloadedRelease:
    version: str
    parquet_path: Path

    def to_payload(self) -> dict[str, str]:
        return {"version": self.version, "parquet_path": str(self.parquet_path.resolve())}


def fetch_versions(registry_data: dict[str, object], versions: list[str], *, force: bool) -> list[DownloadedRelease]:
    downloaded: list[DownloadedRelease] = []
    for version in versions:
        release = resolve_release(registry_data, version)
        parquet_path = fetch_release(release, force=force)
        downloaded.append(DownloadedRelease(version=release.version, parquet_path=parquet_path))
    return downloaded


def versions_for_default_fetch(registry_data: dict[str, object], *, osf_source: bool) -> list[str]:
    if osf_source:
        return ordered_versions(registry_data)
    return [latest_version(registry_data)]


def versions_for_update(
    registry_data: dict[str, object],
    *,
    local_current: str | None,
    force: bool,
    osf_source: bool,
) -> list[str]:
    if not osf_source:
        remote_latest = latest_version(registry_data)
        if local_current == remote_latest and not force:
            return []
        return [remote_latest]

    versions = ordered_versions(registry_data)
    if force:
        return versions
    if local_current in versions:
        current_index = versions.index(local_current)
        return versions[current_index + 1 :]
    return versions
