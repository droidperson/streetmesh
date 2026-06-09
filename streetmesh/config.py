"""Configuration loading for StreetMesh."""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    data_dir: Path
    listen_host: str
    listen_port: int


@dataclass(frozen=True)
class StreetMeshConfig:
    path: Path
    node: NodeConfig


def load_config(path: Path) -> StreetMeshConfig:
    resolved = path.expanduser()
    parser = ConfigParser()

    if not resolved.exists():
        raise ConfigError(f"configuration file not found: {resolved}")

    parser.read(resolved)
    if "node" not in parser:
        raise ConfigError("missing required [node] section")

    section = parser["node"]
    node_id = section.get("id", "").strip()
    if not node_id:
        raise ConfigError("missing required node.id")

    data_dir = Path(section.get("data_dir", "var/lib/streetmesh")).expanduser()
    listen_host = section.get("listen_host", "127.0.0.1").strip()
    listen_port = section.getint("listen_port", fallback=0)
    if not 0 <= listen_port <= 65535:
        raise ConfigError("node.listen_port must be between 0 and 65535")

    return StreetMeshConfig(
        path=resolved,
        node=NodeConfig(
            node_id=node_id,
            data_dir=data_dir,
            listen_host=listen_host,
            listen_port=listen_port,
        ),
    )
