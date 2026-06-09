"""Awareness Store for known StreetMesh nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Literal


LOGGER = logging.getLogger(__name__)
UpdateStatus = Literal["discovered", "refreshed", "ignored"]


@dataclass(frozen=True)
class AwarenessUpdate:
    status: UpdateStatus
    entry: "NodeEntry | None"


@dataclass
class NodeEntry:
    node_id: str
    node_name: str
    first_seen: int
    last_seen: int
    expires: int
    is_local: bool
    seq: int

    @classmethod
    def from_json(cls, value: object) -> "NodeEntry | None":
        if not isinstance(value, dict):
            return None

        try:
            node_id = value["node_id"]
            node_name = value["node_name"]
            first_seen = value["first_seen"]
            last_seen = value["last_seen"]
            expires = value["expires"]
            is_local = value["is_local"]
            seq = value["seq"]
        except KeyError:
            return None

        if not isinstance(node_id, str) or not node_id.strip():
            return None
        if not isinstance(node_name, str) or not node_name.strip():
            return None
        if not isinstance(first_seen, int) or isinstance(first_seen, bool):
            return None
        if not isinstance(last_seen, int) or isinstance(last_seen, bool):
            return None
        if not isinstance(expires, int) or isinstance(expires, bool):
            return None
        if not isinstance(is_local, bool):
            return None
        if not isinstance(seq, int) or isinstance(seq, bool):
            return None

        return cls(
            node_id=node_id,
            node_name=node_name,
            first_seen=first_seen,
            last_seen=last_seen,
            expires=expires,
            is_local=is_local,
            seq=seq,
        )


class AwarenessStore:
    """In-memory and optionally persisted directory of known nodes."""

    def __init__(
        self,
        *,
        local_node_id: str | None = None,
        path: Path | None = None,
    ) -> None:
        self.local_node_id = local_node_id
        self.path = path
        self._nodes_by_id: dict[str, NodeEntry] = {}
        self._node_names: dict[str, str] = {}

    def add_local_node(
        self,
        *,
        node_id: str,
        node_name: str,
        expires: int,
        now: int | None = None,
    ) -> NodeEntry:
        self.local_node_id = node_id
        entry = NodeEntry(
            node_id=node_id,
            node_name=node_name,
            first_seen=_epoch(now),
            last_seen=_epoch(now),
            expires=expires,
            is_local=True,
            seq=0,
        )
        self._store_entry(entry)
        return entry

    def update_from_knowledge_object(
        self,
        knowledge_object: dict[str, Any],
        *,
        now: int | None = None,
    ) -> AwarenessUpdate:
        node_data = _node_data_from_knowledge_object(knowledge_object)
        if node_data is None:
            return AwarenessUpdate("ignored", None)

        node_id, node_name, expires, seq = node_data
        is_local = self.local_node_id == node_id
        seen_at = _epoch(now)
        existing = self._nodes_by_id.get(node_id)

        if existing is not None:
            if seq < existing.seq:
                return AwarenessUpdate("ignored", existing)

            old_name = existing.node_name
            existing.node_name = node_name
            existing.last_seen = seen_at
            existing.expires = expires
            existing.is_local = is_local
            existing.seq = seq
            if old_name != node_name:
                self._node_names.pop(old_name, None)
            self._node_names[node_name] = node_id
            LOGGER.info(
                "Node refreshed: node_name=%s node_id=%s seq=%s expires=%s",
                node_name,
                node_id,
                seq,
                expires,
            )
            return AwarenessUpdate("refreshed", existing)

        entry = NodeEntry(
            node_id=node_id,
            node_name=node_name,
            first_seen=seen_at,
            last_seen=seen_at,
            expires=expires,
            is_local=is_local,
            seq=seq,
        )
        self._store_entry(entry)
        LOGGER.info(
            "Node discovered: node_name=%s node_id=%s seq=%s expires=%s",
            node_name,
            node_id,
            seq,
            expires,
        )
        return AwarenessUpdate("discovered", entry)

    def get_by_node_id(self, node_id: str) -> NodeEntry | None:
        return self._nodes_by_id.get(node_id)

    def get_by_node_name(self, node_name: str) -> NodeEntry | None:
        node_id = self._node_names.get(node_name)
        if node_id is None:
            return None
        return self._nodes_by_id.get(node_id)

    def list_nodes(self) -> list[NodeEntry]:
        return sorted(self._nodes_by_id.values(), key=lambda entry: entry.node_name)

    def save(self) -> None:
        if self.path is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as directory_file:
            json.dump(
                {
                    "nodes": [asdict(entry) for entry in self.list_nodes()],
                },
                directory_file,
                indent=2,
                sort_keys=True,
            )
            directory_file.write("\n")

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        local_node_id: str | None = None,
    ) -> "AwarenessStore":
        store = cls(local_node_id=local_node_id, path=path)
        if not path.exists():
            return store

        try:
            with path.open("r", encoding="utf-8") as directory_file:
                raw = json.load(directory_file)
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Awareness Store load failed: %s", exc)
            return store

        nodes = raw.get("nodes") if isinstance(raw, dict) else None
        if not isinstance(nodes, list):
            return store

        for raw_entry in nodes:
            entry = NodeEntry.from_json(raw_entry)
            if entry is not None:
                if local_node_id is not None:
                    entry.is_local = entry.node_id == local_node_id
                store._store_entry(entry)
        return store

    def _store_entry(self, entry: NodeEntry) -> None:
        existing = self._nodes_by_id.get(entry.node_id)
        if existing is not None and existing.node_name != entry.node_name:
            self._node_names.pop(existing.node_name, None)
        self._nodes_by_id[entry.node_id] = entry
        self._node_names[entry.node_name] = entry.node_id


def _node_data_from_knowledge_object(
    knowledge_object: dict[str, Any],
) -> tuple[str, str, int, int] | None:
    if knowledge_object.get("type") != "NODE":
        return None

    origin = knowledge_object.get("origin")
    subject = knowledge_object.get("subject")
    expires = knowledge_object.get("expires")
    seq = knowledge_object.get("seq")
    payload = knowledge_object.get("payload")

    if not isinstance(origin, str) or not origin.strip():
        return None
    if not isinstance(subject, str) or not subject.strip():
        return None
    if not isinstance(expires, int) or isinstance(expires, bool):
        return None
    if not isinstance(seq, int) or isinstance(seq, bool):
        return None
    if not isinstance(payload, dict):
        return None

    payload_node_id = payload.get("node_id")
    payload_node_name = payload.get("node_name")
    if payload_node_id != origin:
        return None
    if payload_node_name != subject:
        return None

    return origin, subject, expires, seq


def _epoch(now: int | None) -> int:
    return int(time.time() if now is None else now)
