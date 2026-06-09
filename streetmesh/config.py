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
DEFAULT_ANNOUNCE_INTERVAL = 30
DEFAULT_UDP_PORT = 40404
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_BROADCAST_HOST = "255.255.255.255"


@dataclass(frozen=True)
class NodeConfig:
    node_name: str
    data_dir: Path
    announce_interval: int
    udp_port: int
    bind_host: str
    broadcast_host: str


@dataclass(frozen=True)
class StreetMeshConfig:
    path: Path | None
    node: NodeConfig


def load_config(
    path: Path | None = None,
    *,
    data_dir: Path | None = None,
    node_name: str | None = None,
    announce_interval: int | None = None,
    udp_port: int | None = None,
) -> StreetMeshConfig:
    """Load configuration from JSON and apply command-line overrides."""

    resolved = path.expanduser() if path is not None else None
    values: dict[str, Any] = {}

    if resolved is not None:
        values = _load_json_config(resolved)

    configured_node_name = str(values.get("node_name", DEFAULT_NODE_NAME)).strip()
    configured_data_dir = Path(str(values.get("data_dir", DEFAULT_DATA_DIR))).expanduser()
    configured_announce_interval = _get_positive_int(
        values,
        "announce_interval",
        DEFAULT_ANNOUNCE_INTERVAL,
    )
    configured_udp_port = _get_udp_port(values, "udp_port", DEFAULT_UDP_PORT)
    configured_bind_host = str(values.get("bind_host", DEFAULT_BIND_HOST)).strip()
    configured_broadcast_host = str(
        values.get("broadcast_host", DEFAULT_BROADCAST_HOST)
    ).strip()

    if node_name is not None:
        configured_node_name = node_name.strip()
    if data_dir is not None:
        configured_data_dir = data_dir.expanduser()
    if announce_interval is not None:
        configured_announce_interval = _validate_positive_int(
            "announce_interval",
            announce_interval,
        )
    if udp_port is not None:
        configured_udp_port = _validate_udp_port("udp_port", udp_port)

    if not configured_node_name:
        raise ConfigError("node_name must not be empty")
    if not configured_bind_host:
        raise ConfigError("bind_host must not be empty")
    if not configured_broadcast_host:
        raise ConfigError("broadcast_host must not be empty")

    return StreetMeshConfig(
        path=resolved,
        node=NodeConfig(
            node_name=configured_node_name,
            data_dir=configured_data_dir,
            announce_interval=configured_announce_interval,
            udp_port=configured_udp_port,
            bind_host=configured_bind_host,
            broadcast_host=configured_broadcast_host,
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

    allowed_keys = {
        "node_name",
        "data_dir",
        "announce_interval",
        "udp_port",
        "bind_host",
        "broadcast_host",
    }
    unknown_keys = set(node_config) - allowed_keys
    if unknown_keys:
        unknown = ", ".join(sorted(unknown_keys))
        raise ConfigError(f"unknown configuration option(s): {unknown}")

    return dict(node_config)


def _get_positive_int(values: dict[str, Any], key: str, default: int) -> int:
    return _validate_positive_int(key, values.get(key, default))


def _validate_positive_int(key: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _get_udp_port(values: dict[str, Any], key: str, default: int) -> int:
    return _validate_udp_port(key, values.get(key, default))


def _validate_udp_port(key: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
        raise ConfigError(f"{key} must be between 0 and 65535")
    return value
