"""Configuration loading for StreetMesh."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


DEFAULT_DATA_DIR = Path("data")
DEFAULT_NODE_NAME = "node01@local@mesh"


@dataclass(frozen=True)
class NodeConfig:
    node_name: str
    data_dir: Path


@dataclass(frozen=True)
class StreetMeshConfig:
    path: Path | None
    node: NodeConfig


def load_config(
    path: Path | None = None,
    *,
    data_dir: Path | None = None,
    node_name: str | None = None,
) -> StreetMeshConfig:
    """Load configuration from JSON and apply command-line overrides."""

    resolved = path.expanduser() if path is not None else None
    values: dict[str, Any] = {}

    if resolved is not None:
        values = _load_json_config(resolved)

    configured_node_name = str(values.get("node_name", DEFAULT_NODE_NAME)).strip()
    configured_data_dir = Path(str(values.get("data_dir", DEFAULT_DATA_DIR))).expanduser()

    if node_name is not None:
        configured_node_name = node_name.strip()
    if data_dir is not None:
        configured_data_dir = data_dir.expanduser()

    if not configured_node_name:
        raise ConfigError("node_name must not be empty")

    return StreetMeshConfig(
        path=resolved,
        node=NodeConfig(
            node_name=configured_node_name,
            data_dir=configured_data_dir,
        ),
    )


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in configuration file: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read configuration file: {exc}") from exc

    if not isinstance(raw_config, dict):
        raise ConfigError("configuration file must contain a JSON object")

    node_config = raw_config.get("node", raw_config)
    if not isinstance(node_config, dict):
        raise ConfigError("node configuration must be a JSON object")

    allowed_keys = {"node_name", "data_dir"}
    unknown_keys = set(node_config) - allowed_keys
    if unknown_keys:
        unknown = ", ".join(sorted(unknown_keys))
        raise ConfigError(f"unknown configuration option(s): {unknown}")

    return dict(node_config)
