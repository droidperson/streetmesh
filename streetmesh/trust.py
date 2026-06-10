"""Persistent local trust state for StreetMesh node identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Literal, get_args


TrustState = Literal[
    "unknown",
    "observed",
    "candidate",
    "trusted",
    "privileged",
    "quarantined",
    "blocked",
    "revoked",
]
TRUST_STATES = frozenset(get_args(TrustState))


class TrustStoreError(ValueError):
    """Raised when persisted trust state is invalid."""


@dataclass(frozen=True)
class TrustEntry:
    node_id: str
    state: TrustState


class TrustStore:
    """Node trust states persisted as JSON."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._entries: dict[str, TrustEntry] = {}

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        create_if_missing: bool = True,
    ) -> "TrustStore":
        store = cls(path)
        if not path.exists():
            if create_if_missing:
                store.save()
            return store
        try:
            with path.open("r", encoding="utf-8") as trust_file:
                raw = json.load(trust_file)
        except json.JSONDecodeError as exc:
            raise TrustStoreError(f"invalid JSON in trust store: {exc}") from exc
        except OSError as exc:
            raise TrustStoreError(f"could not read trust store: {exc}") from exc

        entries = raw.get("nodes") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise TrustStoreError("trust store must contain a nodes list")
        for value in entries:
            if not isinstance(value, dict):
                raise TrustStoreError("trust entry must be a JSON object")
            store.set_state(value.get("node_id"), value.get("state"), save=False)
        return store

    def get_state(self, node_id: object) -> TrustState:
        if not isinstance(node_id, str):
            return "unknown"
        entry = self._entries.get(node_id)
        return entry.state if entry is not None else "unknown"

    def set_state(
        self,
        node_id: object,
        state: object,
        *,
        save: bool = True,
    ) -> TrustEntry:
        if not isinstance(node_id, str) or not node_id.strip():
            raise TrustStoreError("node_id must be a non-empty string")
        if not isinstance(state, str) or state not in TRUST_STATES:
            raise TrustStoreError(f"invalid trust state: {state!r}")
        entry = TrustEntry(node_id=node_id, state=state)
        self._entries[node_id] = entry
        if save:
            self.save()
        return entry

    def add_trusted(self, node_id: str) -> TrustEntry:
        return self.set_state(node_id, "trusted")

    def add_blocked(self, node_id: str) -> TrustEntry:
        return self.set_state(node_id, "blocked")

    def list_entries(self) -> list[TrustEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.node_id)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as trust_file:
            json.dump(
                {"nodes": [asdict(entry) for entry in self.list_entries()]},
                trust_file,
                indent=2,
                sort_keys=True,
            )
            trust_file.write("\n")
