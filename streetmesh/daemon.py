"""StreetMesh daemon lifecycle."""

from __future__ import annotations

from pathlib import Path


class StreetMeshDaemon:
    """Placeholder daemon for Milestone 0.

    The daemon intentionally does not open sockets or start network services in
    this milestone. Later milestones can expand this class into the runtime
    coordinator.
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def run(self) -> int:
        print("StreetMesh daemon skeleton is installed.")
        print("Networking is not implemented in Milestone 0.")
        print(f"Configuration path: {self.config_path}")
        return 0
