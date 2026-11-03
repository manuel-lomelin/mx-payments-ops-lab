"""Small YAML config loader. Config lives in /config so ops can tune without code changes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@lru_cache(maxsize=32)
def _load(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load /config/<name>.yaml. Returns a fresh copy so callers can mutate it."""
    import copy

    return copy.deepcopy(_load(str(Path(config_dir) / f"{name}.yaml")))
