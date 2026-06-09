"""Node identity primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeIdentity:
    """Stable local node identity placeholder."""

    node_id: str
    display_name: str = ""
