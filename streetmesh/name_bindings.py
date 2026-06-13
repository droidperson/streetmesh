"""Persistent local node-name bindings and conflict observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import time
from typing import Literal, get_args

from .trust import BindingStatus


BindingState = Literal["bound", "local"]
BindingSource = Literal["local", "trusted", "manual", "observed"]
BINDING_STATES = frozenset(get_args(BindingState))
BINDING_SOURCES = frozenset(get_args(BindingSource))


class NameBindingError(ValueError):
    """Raised when persisted name binding state is invalid."""


@dataclass(frozen=True)
class NameBinding:
    node_name: str
    node_id: str
    fingerprint: str | None = None
    public_key_id: str | None = None
    binding_state: BindingState = "bound"
    first_bound: int = 0
    last_confirmed: int = 0
    source: BindingSource = "manual"
    notes: str | None = None

    @classmethod
    def from_json(cls, value: object) -> "NameBinding":
        if not isinstance(value, dict):
            raise NameBindingError("name binding must be a JSON object")
        return cls(
            node_name=_required_string("node_name", value.get("node_name")),
            node_id=_required_string("node_id", value.get("node_id")),
            fingerprint=_optional_string("fingerprint", value.get("fingerprint")),
            public_key_id=_optional_string("public_key_id", value.get("public_key_id")),
            binding_state=_binding_state(value.get("binding_state", "bound")),
            first_bound=_epoch("first_bound", value.get("first_bound", 0)),
            last_confirmed=_epoch("last_confirmed", value.get("last_confirmed", 0)),
            source=_binding_source(value.get("source", "manual")),
            notes=_optional_string("notes", value.get("notes")),
        )


@dataclass(frozen=True)
class NameConflict:
    node_name: str
    bound_node_id: str
    claimant_node_id: str
    claimant_fingerprint: str | None = None
    claimant_public_key_id: str | None = None
    first_seen: int = 0
    last_seen: int = 0
    reason: str = "name-already-bound-to-different-node"

    @classmethod
    def from_json(cls, value: object) -> "NameConflict":
        if not isinstance(value, dict):
            raise NameBindingError("name conflict must be a JSON object")
        return cls(
            node_name=_required_string("node_name", value.get("node_name")),
            bound_node_id=_required_string(
                "bound_node_id", value.get("bound_node_id")
            ),
            claimant_node_id=_required_string(
                "claimant_node_id", value.get("claimant_node_id")
            ),
            claimant_fingerprint=_optional_string(
                "claimant_fingerprint", value.get("claimant_fingerprint")
            ),
            claimant_public_key_id=_optional_string(
                "claimant_public_key_id", value.get("claimant_public_key_id")
            ),
            first_seen=_epoch("first_seen", value.get("first_seen", 0)),
            last_seen=_epoch("last_seen", value.get("last_seen", 0)),
            reason=_required_string(
                "reason",
                value.get("reason", "name-already-bound-to-different-node"),
            ),
        )


class NameBindingRegistry:
    """Local ownership memory for stable node-name bindings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._bindings: dict[str, NameBinding] = {}
        self._conflicts: dict[tuple[str, str], NameConflict] = {}

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        create_if_missing: bool = False,
    ) -> "NameBindingRegistry":
        registry = cls(path)
        if not path.exists():
            if create_if_missing:
                registry.save()
            return registry
        try:
            with path.open("r", encoding="utf-8") as binding_file:
                raw = json.load(binding_file)
        except json.JSONDecodeError as exc:
            raise NameBindingError(f"invalid JSON in name binding registry: {exc}") from exc
        except OSError as exc:
            raise NameBindingError(f"could not read name binding registry: {exc}") from exc
        if not isinstance(raw, dict):
            raise NameBindingError("name binding registry must be a JSON object")
        bindings = raw.get("bindings", [])
        conflicts = raw.get("conflicts", [])
        if not isinstance(bindings, list) or not isinstance(conflicts, list):
            raise NameBindingError("name binding registry lists are invalid")
        for value in bindings:
            binding = NameBinding.from_json(value)
            if binding.node_name in registry._bindings:
                raise NameBindingError(
                    f"duplicate name binding: {binding.node_name!r}"
                )
            registry._bindings[binding.node_name] = binding
        for value in conflicts:
            conflict = NameConflict.from_json(value)
            registry._conflicts[
                (conflict.node_name, conflict.claimant_node_id)
            ] = conflict
        return registry

    def bind(
        self,
        node_name: str,
        node_id: str,
        *,
        fingerprint: str | None = None,
        public_key_id: str | None = None,
        binding_state: BindingState = "bound",
        source: BindingSource = "manual",
        notes: str | None = None,
        now: int | None = None,
        save: bool = True,
    ) -> NameBinding:
        resolved_name = _required_string("node_name", node_name)
        resolved_id = _required_string("node_id", node_id)
        resolved_fingerprint = _optional_string("fingerprint", fingerprint)
        resolved_public_key_id = _optional_string("public_key_id", public_key_id)
        resolved_state = _binding_state(binding_state)
        resolved_source = _binding_source(source)
        resolved_notes = _optional_string("notes", notes)
        current_time = int(time.time() if now is None else now)
        existing = self._bindings.get(resolved_name)
        if existing is not None and existing.node_id != resolved_id:
            raise NameBindingError(
                f"node name {resolved_name!r} is already bound to {existing.node_id}"
            )
        binding = NameBinding(
            node_name=resolved_name,
            node_id=resolved_id,
            fingerprint=resolved_fingerprint or (
                existing.fingerprint if existing is not None else None
            ),
            public_key_id=resolved_public_key_id or (
                existing.public_key_id if existing is not None else None
            ),
            binding_state=resolved_state,
            first_bound=(
                existing.first_bound if existing is not None else current_time
            ),
            last_confirmed=current_time,
            source=resolved_source,
            notes=resolved_notes or (existing.notes if existing is not None else None),
        )
        self._bindings[resolved_name] = binding
        if save:
            self.save()
        return binding

    def bind_local(
        self,
        node_name: str,
        node_id: str,
        *,
        fingerprint: str | None = None,
        public_key_id: str | None = None,
        now: int | None = None,
        save: bool = True,
    ) -> NameBinding:
        return self.bind(
            node_name,
            node_id,
            fingerprint=fingerprint,
            public_key_id=public_key_id,
            binding_state="local",
            source="local",
            notes="local privileged identity",
            now=now,
            save=save,
        )

    def get(self, node_name: object) -> NameBinding | None:
        if not isinstance(node_name, str):
            return None
        return self._bindings.get(node_name)

    def status_for_claim(self, node_name: object, node_id: object) -> BindingStatus:
        if not isinstance(node_name, str) or not isinstance(node_id, str):
            return "unknown"
        binding = self.get(node_name)
        if binding is None:
            return "unbound"
        return "bound" if binding.node_id == node_id else "name_conflict"

    def observe_claim(
        self,
        node_name: object,
        node_id: object,
        *,
        fingerprint: object = None,
        public_key_id: object = None,
        now: int | None = None,
        save: bool = True,
    ) -> BindingStatus:
        if not isinstance(node_name, str) or not isinstance(node_id, str):
            return "unknown"
        binding = self.get(node_name)
        if binding is None:
            return "unbound"
        current_time = int(time.time() if now is None else now)
        if binding.node_id == node_id:
            self._bindings[node_name] = replace(
                binding,
                fingerprint=(
                    fingerprint if isinstance(fingerprint, str) else binding.fingerprint
                ),
                public_key_id=(
                    public_key_id
                    if isinstance(public_key_id, str)
                    else binding.public_key_id
                ),
                last_confirmed=current_time,
            )
            if save:
                self.save()
            return "bound"
        key = (node_name, node_id)
        existing = self._conflicts.get(key)
        self._conflicts[key] = NameConflict(
            node_name=node_name,
            bound_node_id=binding.node_id,
            claimant_node_id=node_id,
            claimant_fingerprint=(
                fingerprint if isinstance(fingerprint, str) else None
            ),
            claimant_public_key_id=(
                public_key_id if isinstance(public_key_id, str) else None
            ),
            first_seen=existing.first_seen if existing is not None else current_time,
            last_seen=current_time,
        )
        if save:
            self.save()
        return "name_conflict"

    def list_bindings(self) -> list[NameBinding]:
        return sorted(self._bindings.values(), key=lambda item: item.node_name)

    def list_conflicts(self) -> list[NameConflict]:
        return sorted(
            self._conflicts.values(),
            key=lambda item: (item.node_name, item.claimant_node_id),
        )

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("w", encoding="utf-8") as binding_file:
                json.dump(
                    {
                        "bindings": [asdict(item) for item in self.list_bindings()],
                        "conflicts": [asdict(item) for item in self.list_conflicts()],
                    },
                    binding_file,
                    indent=2,
                    sort_keys=True,
                )
                binding_file.write("\n")
        except OSError as exc:
            raise NameBindingError(
                f"could not write name binding registry: {exc}"
            ) from exc


def _required_string(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NameBindingError(f"{field} must be a non-empty string")
    return value


def _optional_string(field: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise NameBindingError(f"{field} must be a non-empty string or null")
    return value


def _epoch(field: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise NameBindingError(f"{field} must be Unix epoch seconds")
    return value


def _binding_state(value: object) -> BindingState:
    if not isinstance(value, str) or value not in BINDING_STATES:
        raise NameBindingError(f"invalid binding_state: {value!r}")
    return value


def _binding_source(value: object) -> BindingSource:
    if not isinstance(value, str) or value not in BINDING_SOURCES:
        raise NameBindingError(f"invalid binding source: {value!r}")
    return value
