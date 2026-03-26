"""Filesystem and HTTP helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import requests

from .constants import DEFAULT_TIMEOUT_SECONDS, ENV_HOME, default_home


class AtbCliError(RuntimeError):
    """Base error class for user-facing CLI failures."""


class ConfigError(AtbCliError):
    """Raised for invalid user configuration."""


class RemoteError(AtbCliError):
    """Raised for remote fetch/download failures."""


class DataError(AtbCliError):
    """Raised for invalid local data or query assumptions."""



def get_app_home() -> Path:
    root = Path(os.environ.get(ENV_HOME, default_home()))
    root.mkdir(parents=True, exist_ok=True)
    (root / "db").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    return root



def state_file() -> Path:
    return get_app_home() / "state" / "state.json"



def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)



def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")



def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def fetch_json(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    if response.status_code != 200:
        raise RemoteError(f"Request failed for {url!r}: HTTP {response.status_code}")
    return response.json()



def download_file(url: str, destination: Path, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as response:
        if response.status_code != 200:
            raise RemoteError(f"Download failed for {url!r}: HTTP {response.status_code}")
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
