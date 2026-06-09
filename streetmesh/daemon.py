"""StreetMesh daemon lifecycle."""

from __future__ import annotations

from .config import StreetMeshConfig
from .identity import IdentityError, load_or_create_identity


class StreetMeshDaemon:
    """Placeholder daemon for Milestone 1.

    The daemon intentionally does not open sockets or start network services in
    this milestone.
    """

    def __init__(self, config: StreetMeshConfig) -> None:
        self.config = config

    def run(self) -> int:
        try:
            identity = load_or_create_identity(
                self.config.node.data_dir,
                self.config.node.node_name,
            )
        except IdentityError as exc:
            print(f"Identity error: {exc}")
            return 1

        print("StreetMesh daemon skeleton is installed.")
        print("Networking is not implemented in Milestone 1.")
        print(f"Node ID: {identity.node_id}")
        print(f"Node name: {identity.node_name}")
        print(f"Data directory: {self.config.node.data_dir}")
        return 0
