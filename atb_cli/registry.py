"""Registry and installed-version management.

This module supports two release sources:

1. A static registry JSON file/URL.
2. An OSF storage page or node ID, where .parquet files are discovered dynamically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import DEFAULT_REGISTRY_URL
from .io_utils import DataError, download_file, fetch_json, get_app_home, read_json, sha256_file, state_file, write_json

_OSF_STORAGE_PAGE_RE = re.compile(r"^https?://osf\.io/(?P<node>[A-Za-z0-9]{5})/files/osfstorage/?(?:$|[?#])")
_OSF_NODE_PAGE_RE = re.compile(r"^https?://osf\.io/(?P<node>[A-Za-z0-9]{5})/?(?:$|[?#])")
_OSF_API_FILES_RE = re.compile(r"^https?://api\.osf\.io/v2/nodes/(?P<node>[A-Za-z0-9]{5})/files/osfstorage/?(?:$|[?#])")
_VERSION_PATTERNS = (
    re.compile(r"(?P<value>\d{4}-\d{2}-\d{2})"),
    re.compile(r"(?P<value>\d{8})"),
    re.compile(r"(?P<value>v?\d+\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)?)", re.IGNORECASE),
)


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    parquet_url: str
    checksum_sha256: str | None = None
    sequence_url_template: str | None = None
    release_date: str | None = None



def _extract_osf_node_id(source: str) -> str | None:
    if source.startswith("osf://"):
        node_id = source.removeprefix("osf://").strip("/")
        return node_id or None
    for pattern in (_OSF_STORAGE_PAGE_RE, _OSF_NODE_PAGE_RE, _OSF_API_FILES_RE):
        match = pattern.match(source)
        if match:
            return match.group("node")
    return None



def _is_osf_source(source: str) -> bool:
    return _extract_osf_node_id(source) is not None



def _extract_href(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("href", "url"):
            href = value.get(key)
            if isinstance(href, str) and href:
                return href
    return None



def _extract_nested_href(mapping: dict[str, Any], *path: str) -> str | None:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _extract_href(current)



def _osf_api_url(node_id: str) -> str:
    return f"https://api.osf.io/v2/nodes/{node_id}/files/osfstorage/"



def _fetch_all_osf_entries(url: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        payload = fetch_json(next_url)
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise DataError(f"Unexpected OSF API payload for {next_url!r}: data is not a list")
        entries.extend(item for item in data if isinstance(item, dict))
        links = payload.get("links") or {}
        next_url = _extract_href(links.get("next"))
    return entries



def _list_osf_files(source: str) -> list[dict[str, Any]]:
    node_id = _extract_osf_node_id(source)
    if not node_id:
        raise DataError(f"Could not parse an OSF node ID from {source!r}")

    queue = [_osf_api_url(node_id)]
    seen_urls: set[str] = set()
    files: list[dict[str, Any]] = []

    while queue:
        url = queue.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        for item in _fetch_all_osf_entries(url):
            attributes = item.get("attributes") or {}
            kind = attributes.get("kind")
            if kind == "file":
                files.append(item)
                continue
            if kind == "folder":
                folder_url = (
                    _extract_nested_href(item, "relationships", "files", "links", "related")
                    or _extract_nested_href(item, "links", "move")
                )
                if folder_url and folder_url not in seen_urls:
                    queue.append(folder_url)

    return files



def _coerce_release_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    # Preserve ISO timestamps, but normalize YYYYMMDD to YYYY-MM-DD.
    if re.fullmatch(r"\d{8}", value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value



def _infer_version_from_filename(name: str) -> str:
    stem = Path(name).stem
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(stem)
        if match:
            value = match.group("value")
            if re.fullmatch(r"\d{8}", value):
                return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
            return value
    return stem.replace(" ", "_")



def _parse_sort_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidates = [value]
    if value.endswith("Z"):
        candidates.append(value[:-1] + "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        candidates.append(value + "T00:00:00+00:00")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None



def _build_osf_registry(source: str) -> dict[str, Any]:
    node_id = _extract_osf_node_id(source)
    if not node_id:
        raise DataError(f"Could not parse OSF source {source!r}")

    versions: dict[str, dict[str, Any]] = {}
    latest_key: str | None = None
    latest_sort: tuple[datetime, str] | None = None

    for item in _list_osf_files(source):
        attributes = item.get("attributes") or {}
        name = attributes.get("name")
        if not isinstance(name, str) or not name.lower().endswith(".parquet"):
            continue

        download_url = _extract_nested_href(item, "links", "download")
        if not download_url:
            continue

        version = _infer_version_from_filename(name)
        release_date = _coerce_release_date(
            attributes.get("date_modified")
            or attributes.get("modified")
            or attributes.get("date_created")
            or attributes.get("created")
        )
        record = {
            "parquet_url": download_url,
            "release_date": release_date,
            "source_name": name,
            "source": "osf",
            "node_id": node_id,
            "provider": "osfstorage",
            "page_url": f"https://osf.io/{node_id}/files/osfstorage",
        }
        versions[version] = record

        sort_date = _parse_sort_date(release_date) or datetime.min.replace(tzinfo=timezone.utc)
        sort_key = (sort_date, version)
        if latest_sort is None or sort_key > latest_sort:
            latest_sort = sort_key
            latest_key = version

    if not versions:
        raise DataError(
            f"No .parquet files were discovered from OSF source {source!r}. "
            "Check that the project is public and that parquet files are present."
        )

    if latest_key is None:
        latest_key = sorted(versions.keys())[-1]

    return {
        "latest": latest_key,
        "versions": versions,
        "source": "osf",
        "node_id": node_id,
        "provider": "osfstorage",
        "page_url": f"https://osf.io/{node_id}/files/osfstorage",
        "api_url": _osf_api_url(node_id),
    }



def load_registry(registry: str | None = None) -> dict[str, Any]:
    source = registry or DEFAULT_REGISTRY_URL
    if _is_osf_source(source):
        return _build_osf_registry(source)
    if source.startswith("http://") or source.startswith("https://"):
        return fetch_json(source)
    return read_json(Path(source))


def is_osf_source(source: str | None = None) -> bool:
    return _is_osf_source(source or DEFAULT_REGISTRY_URL)



def latest_version(registry_data: dict[str, Any]) -> str:
    latest = registry_data.get("latest")
    versions = registry_data.get("versions", {})
    if latest and latest in versions:
        return latest
    if versions:
        return sorted(versions.keys())[-1]
    raise DataError("Registry contains no versions")



def resolve_release(registry_data: dict[str, Any], version: str | None = None) -> ReleaseInfo:
    versions = registry_data.get("versions", {})
    selected = version or latest_version(registry_data)
    if selected not in versions:
        available = ", ".join(sorted(versions.keys())) or "<none>"
        raise DataError(f"Unknown version {selected!r}. Available versions: {available}")

    payload = versions[selected]
    parquet_url = payload.get("parquet_url")
    if not parquet_url:
        raise DataError(f"Registry entry for {selected!r} has no parquet_url")

    return ReleaseInfo(
        version=selected,
        parquet_url=parquet_url,
        checksum_sha256=payload.get("checksum_sha256"),
        sequence_url_template=payload.get("sequence_url_template"),
        release_date=payload.get("release_date"),
    )


def ordered_versions(registry_data: dict[str, Any]) -> list[str]:
    versions = registry_data.get("versions", {})
    if not versions:
        raise DataError("Registry contains no versions")

    minimum = datetime.min.replace(tzinfo=timezone.utc)

    def sort_key(item: tuple[str, Any]) -> tuple[datetime, str]:
        version, payload = item
        release_date: str | None = None
        if isinstance(payload, dict):
            release_date = _coerce_release_date(payload.get("release_date"))
        return (_parse_sort_date(release_date) or minimum, version)

    ordered = [version for version, _ in sorted(versions.items(), key=sort_key)]
    latest = latest_version(registry_data)
    return [version for version in ordered if version != latest] + [latest]



def installed_db_dir(version: str) -> Path:
    return get_app_home() / "db" / version



def installed_db_path(version: str) -> Path:
    return installed_db_dir(version) / "atb.parquet"



def installed_metadata_path(version: str) -> Path:
    return installed_db_dir(version) / "metadata.json"



def is_installed(version: str) -> bool:
    return installed_db_path(version).exists()



def read_state() -> dict[str, Any]:
    path = state_file()
    if not path.exists():
        return {}
    return read_json(path)



def write_state(payload: dict[str, Any]) -> None:
    write_json(state_file(), payload)



def current_version() -> str | None:
    return read_state().get("current_version")



def set_current_version(version: str) -> None:
    state = read_state()
    state["current_version"] = version
    write_state(state)



def fetch_release(release: ReleaseInfo, *, force: bool = False) -> Path:
    target = installed_db_path(release.version)
    metadata_path = installed_metadata_path(release.version)
    if target.exists() and not force:
        return target

    download_file(release.parquet_url, target)
    actual_sha256 = sha256_file(target)
    if release.checksum_sha256 and release.checksum_sha256 != actual_sha256:
        target.unlink(missing_ok=True)
        raise DataError(
            f"Checksum mismatch for version {release.version!r}: expected {release.checksum_sha256}, got {actual_sha256}"
        )

    write_json(
        metadata_path,
        {
            "version": release.version,
            "parquet_url": release.parquet_url,
            "checksum_sha256": actual_sha256,
            "sequence_url_template": release.sequence_url_template,
            "release_date": release.release_date,
        },
    )
    set_current_version(release.version)
    return target



def get_local_release_metadata(version: str) -> dict[str, Any]:
    path = installed_metadata_path(version)
    if not path.exists():
        raise DataError(f"Version {version!r} is not installed")
    return read_json(path)
