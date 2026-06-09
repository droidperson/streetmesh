"""Routing table placeholders for future mesh behavior."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingTable:
    """In-memory routing table placeholder."""

    peers: set[str] = field(default_factory=set)

    def add_peer(self, node_id: str) -> None:
        self.peers.add(node_id)
