"""Configuration loading utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io_utils import ConfigError

try:  # pragma: no cover - exercised depending on interpreter version
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]



def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"TOML file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc



def config_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()



def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)
