"""Local state storage placeholders."""

from __future__ import annotations

from pathlib import Path


class StateStore:
    """Placeholder for durable local state."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
