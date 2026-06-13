"""Persistent local trust state for StreetMesh node identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
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
BindingStatus = Literal[
    "unbound",
    "bound",
    "name_conflict",
    "stale_binding",
    "unknown",
]
BINDING_STATUSES = frozenset(get_args(BindingStatus))


class TrustStoreError(ValueError):
    """Raised when persisted trust state is invalid."""


@dataclass(frozen=True)
class TrustEntry:
    node_id: str
    state: TrustState
    node_name: str | None = None
    fingerprint: str | None = None
    first_trusted: int | None = None
    last_confirmed: int | None = None
    binding_status: BindingStatus = "unbound"
    public_key_id: str | None = None

    @property
    def trust_state(self) -> TrustState:
        return self.state


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
            store.set_state(
                value.get("node_id"),
                value.get("state", value.get("trust_state")),
                node_name=value.get("node_name"),
                fingerprint=value.get("fingerprint"),
                public_key_id=value.get("public_key_id"),
                first_trusted=value.get("first_trusted"),
                last_confirmed=value.get("last_confirmed"),
                binding_status=value.get("binding_status", "unbound"),
                save=False,
            )
        return store

    def get_state(self, node_id: object) -> TrustState:
        if not isinstance(node_id, str):
            return "unknown"
        entry = self._entries.get(node_id)
        return entry.state if entry is not None else "unknown"

    def get_entry(self, node_id: object) -> TrustEntry | None:
        if not isinstance(node_id, str):
            return None
        return self._entries.get(node_id)

    def get_by_name(self, node_name: object) -> TrustEntry | None:
        if not isinstance(node_name, str):
            return None
        matches = [
            entry
            for entry in self._entries.values()
            if entry.node_name == node_name and entry.binding_status == "bound"
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def set_state(
        self,
        node_id: object,
        state: object,
        *,
        node_name: object = None,
        fingerprint: object = None,
        public_key_id: object = None,
        first_trusted: object = None,
        last_confirmed: object = None,
        binding_status: object = None,
        save: bool = True,
    ) -> TrustEntry:
        if not isinstance(node_id, str) or not node_id.strip():
            raise TrustStoreError("node_id must be a non-empty string")
        if not isinstance(state, str) or state not in TRUST_STATES:
            raise TrustStoreError(f"invalid trust state: {state!r}")
        existing = self._entries.get(node_id)
        resolved_name = _optional_string("node_name", node_name)
        resolved_fingerprint = _optional_string("fingerprint", fingerprint)
        resolved_public_key_id = _optional_string("public_key_id", public_key_id)
        resolved_first_trusted = _optional_epoch("first_trusted", first_trusted)
        resolved_last_confirmed = _optional_epoch("last_confirmed", last_confirmed)
        resolved_binding_status = binding_status
        if resolved_binding_status is None:
            resolved_binding_status = (
                existing.binding_status if existing is not None else "unbound"
            )
        if (
            not isinstance(resolved_binding_status, str)
            or resolved_binding_status not in BINDING_STATUSES
        ):
            raise TrustStoreError(
                f"invalid binding status: {resolved_binding_status!r}"
            )
        entry = TrustEntry(
            node_id=node_id,
            state=state,
            node_name=(
                resolved_name
                if resolved_name is not None
                else existing.node_name if existing is not None else None
            ),
            fingerprint=(
                resolved_fingerprint
                if resolved_fingerprint is not None
                else existing.fingerprint if existing is not None else None
            ),
            public_key_id=(
                resolved_public_key_id
                if resolved_public_key_id is not None
                else existing.public_key_id if existing is not None else None
            ),
            first_trusted=(
                resolved_first_trusted
                if resolved_first_trusted is not None
                else existing.first_trusted if existing is not None else None
            ),
            last_confirmed=(
                resolved_last_confirmed
                if resolved_last_confirmed is not None
                else existing.last_confirmed if existing is not None else None
            ),
            binding_status=resolved_binding_status,
        )
        self._entries[node_id] = entry
        if save:
            self.save()
        return entry

    def add_trusted(
        self,
        node_id: str,
        *,
        node_name: str | None = None,
        fingerprint: str | None = None,
        public_key_id: str | None = None,
        now: int | None = None,
    ) -> TrustEntry:
        if node_name is not None:
            return self.bind_name(
                node_id,
                node_name,
                "trusted",
                fingerprint=fingerprint,
                public_key_id=public_key_id,
                now=now,
            )
        return self.set_state(
            node_id,
            "trusted",
            fingerprint=fingerprint,
            public_key_id=public_key_id,
        )

    def add_blocked(
        self,
        node_id: str,
        *,
        node_name: str | None = None,
        fingerprint: str | None = None,
        public_key_id: str | None = None,
        now: int | None = None,
    ) -> TrustEntry:
        if node_name is not None:
            return self.bind_name(
                node_id,
                node_name,
                "blocked",
                fingerprint=fingerprint,
                public_key_id=public_key_id,
                now=now,
            )
        return self.set_state(
            node_id,
            "blocked",
            fingerprint=fingerprint,
            public_key_id=public_key_id,
        )

    def bind_name(
        self,
        node_id: str,
        node_name: str,
        state: TrustState,
        *,
        fingerprint: str | None = None,
        public_key_id: str | None = None,
        now: int | None = None,
    ) -> TrustEntry:
        existing_binding = self.get_by_name(node_name)
        if existing_binding is not None and existing_binding.node_id != node_id:
            raise TrustStoreError(
                f"node name {node_name!r} is already bound to {existing_binding.node_id}"
            )
        current_time = int(time.time() if now is None else now)
        existing = self.get_entry(node_id)
        first_trusted = existing.first_trusted if existing is not None else None
        if state == "trusted" and first_trusted is None:
            first_trusted = current_time
        return self.set_state(
            node_id,
            state,
            node_name=node_name,
            fingerprint=fingerprint,
            public_key_id=public_key_id,
            first_trusted=first_trusted,
            last_confirmed=current_time,
            binding_status="bound",
        )

    def binding_status_for_claim(
        self,
        node_id: object,
        node_name: object,
    ) -> BindingStatus:
        if not isinstance(node_id, str) or not isinstance(node_name, str):
            return "unknown"
        binding = self.get_by_name(node_name)
        if binding is not None:
            if binding.node_id == node_id:
                return "bound"
            return "name_conflict"
        entry = self.get_entry(node_id)
        if entry is not None and entry.binding_status == "bound":
            if entry.node_name == node_name:
                return "bound"
            return "stale_binding"
        if entry is not None and entry.node_name == node_name:
            return entry.binding_status
        return "unbound"

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


def _optional_string(field: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TrustStoreError(f"{field} must be a non-empty string or null")
    return value


def _optional_epoch(field: str, value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TrustStoreError(f"{field} must be Unix epoch seconds or null")
    return value
