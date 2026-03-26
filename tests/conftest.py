from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atb_cli.constants import ENV_HOME

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_app_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "atb-cli-home"))
