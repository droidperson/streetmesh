"""Awareness Store for known StreetMesh nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Literal

from .protocol import SIGNATURE_STATUSES, SignatureStatus
from .trust import TRUST_STATES, TrustState


LOGGER = logging.getLogger(__name__)
UpdateStatus = Literal["discovered", "refreshed", "ignored"]
DEFAULT_DUPLICATE_RETENTION = 300


@dataclass(frozen=True)
class AwarenessUpdate:
    status: UpdateStatus
    entry: "NodeEntry | ServiceEntry | None"


@dataclass
class NodeEntry:
    node_id: str
    node_name: str
    first_seen: int
    last_seen: int
    expires: int
    is_local: bool
    seq: int
    trust_state: TrustState = "unknown"
    signature_status: SignatureStatus = "signature_not_checked"

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
            trust_state = value.get("trust_state", "unknown")
            signature_status = value.get(
                "signature_status",
                "signature_not_checked",
            )
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
        if not isinstance(trust_state, str) or trust_state not in TRUST_STATES:
            return None
        if (
            not isinstance(signature_status, str)
            or signature_status not in SIGNATURE_STATUSES
        ):
            return None

        return cls(
            node_id=node_id,
            node_name=node_name,
            first_seen=first_seen,
            last_seen=last_seen,
            expires=expires,
            is_local=is_local,
            seq=seq,
            trust_state=trust_state,
            signature_status=signature_status,
        )


@dataclass
class ServiceEntry:
    service_name: str
    provider: str
    provider_name: str | None
    capabilities: list[str]
    endpoint: str | None
    protocol: str | None
    service_version: str | None
    first_seen: int
    last_seen: int
    expires: int
    is_local: bool
    seq: int
    trust_state: TrustState = "unknown"
    accepted_limited: bool = False
    signature_status: SignatureStatus = "signature_not_checked"

    @classmethod
    def from_json(cls, value: object) -> "ServiceEntry | None":
        if not isinstance(value, dict):
            return None
        try:
            service_name = value["service_name"]
            provider = value["provider"]
            provider_name = value.get("provider_name")
            capabilities = value.get("capabilities", [])
            endpoint = value.get("endpoint")
            protocol = value.get("protocol")
            service_version = value.get("service_version")
            first_seen = value["first_seen"]
            last_seen = value["last_seen"]
            expires = value["expires"]
            is_local = value["is_local"]
            seq = value["seq"]
            trust_state = value.get("trust_state", "unknown")
            accepted_limited = value.get("accepted_limited", False)
            signature_status = value.get(
                "signature_status",
                "signature_not_checked",
            )
        except KeyError:
            return None

        if not isinstance(service_name, str) or not service_name.strip():
            return None
        if not isinstance(provider, str) or not provider.strip():
            return None
        if provider_name is not None and not isinstance(provider_name, str):
            return None
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            return None
        if any(
            item is not None and not isinstance(item, str)
            for item in (endpoint, protocol, service_version)
        ):
            return None
        if any(
            not isinstance(item, int) or isinstance(item, bool)
            for item in (first_seen, last_seen, expires, seq)
        ):
            return None
        if not isinstance(is_local, bool):
            return None
        if (
            not isinstance(trust_state, str)
            or trust_state not in TRUST_STATES
            or not isinstance(accepted_limited, bool)
        ):
            return None
        if (
            not isinstance(signature_status, str)
            or signature_status not in SIGNATURE_STATUSES
        ):
            return None
        return cls(
            service_name=service_name,
            provider=provider,
            provider_name=provider_name,
            capabilities=list(capabilities),
            endpoint=endpoint,
            protocol=protocol,
            service_version=service_version,
            first_seen=first_seen,
            last_seen=last_seen,
            expires=expires,
            is_local=is_local,
            seq=seq,
            trust_state=trust_state,
            accepted_limited=accepted_limited,
            signature_status=signature_status,
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
        self._services: dict[tuple[str, str], ServiceEntry] = {}

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
            trust_state="privileged",
        )
        self._store_entry(entry)
        return entry

    def update_from_knowledge_object(
        self,
        knowledge_object: dict[str, Any],
        *,
        now: int | None = None,
        trust_state: TrustState = "unknown",
        accepted_limited: bool = False,
        signature_status: SignatureStatus = "signature_not_checked",
    ) -> AwarenessUpdate:
        if knowledge_object.get("type") == "SERVICE":
            return self._update_service(
                knowledge_object,
                now=now,
                trust_state=trust_state,
                accepted_limited=accepted_limited,
                signature_status=signature_status,
            )

        node_data = _node_data_from_knowledge_object(knowledge_object)
        if node_data is None:
            return AwarenessUpdate("ignored", None)

        node_id, node_name, expires, seq = node_data
        seen_at = _epoch(now)
        if seen_at > expires:
            return AwarenessUpdate("ignored", None)

        is_local = self.local_node_id == node_id
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
            existing.trust_state = trust_state
            existing.signature_status = signature_status
            if old_name != node_name:
                self._node_names.pop(old_name, None)
            self._node_names[node_name] = node_id
            self._set_service_provider_name(node_id, node_name)
            LOGGER.info(
                "Node refreshed: node_name=%s node_id=%s seq=%s expires=%s signature_status=%s",
                node_name,
                node_id,
                seq,
                expires,
                signature_status,
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
            trust_state=trust_state,
            signature_status=signature_status,
        )
        self._store_entry(entry)
        LOGGER.info(
            "Node discovered: node_name=%s node_id=%s seq=%s expires=%s signature_status=%s",
            node_name,
            node_id,
            seq,
            expires,
            signature_status,
        )
        return AwarenessUpdate("discovered", entry)

    def get_by_node_id(self, node_id: str) -> NodeEntry | None:
        return self._nodes_by_id.get(node_id)

    def get_by_node_name(self, node_name: str) -> NodeEntry | None:
        node_id = self._node_names.get(node_name)
        if node_id is None:
            return None
        return self._nodes_by_id.get(node_id)

    def list_nodes(self, *, now: int | None = None) -> list[NodeEntry]:
        if now is not None:
            self.expire_stale(now=now)
        return sorted(self._nodes_by_id.values(), key=lambda entry: entry.node_name)

    def get_service(self, provider: str, service_name: str) -> ServiceEntry | None:
        return self._services.get((provider, service_name))

    def list_services(
        self,
        *,
        service_name: str | None = None,
        provider: str | None = None,
        now: int | None = None,
    ) -> list[ServiceEntry]:
        if now is not None:
            self.expire_stale(now=now)
        services = self._services.values()
        if service_name is not None:
            services = (
                entry for entry in services if entry.service_name == service_name
            )
        if provider is not None:
            services = (entry for entry in services if entry.provider == provider)
        return sorted(
            services,
            key=lambda entry: (entry.service_name, entry.provider),
        )

    def expire_stale(
        self,
        *,
        now: int | None = None,
    ) -> list[NodeEntry | ServiceEntry]:
        current_time = _epoch(now)
        expired: list[NodeEntry | ServiceEntry] = []
        for entry in list(self._nodes_by_id.values()):
            if entry.is_local:
                continue
            if current_time > entry.expires:
                expired.append(entry)
                self._nodes_by_id.pop(entry.node_id, None)
                self._node_names.pop(entry.node_name, None)
                LOGGER.info(
                    "NODE_EXPIRED node_name=%s node_id=%s expires=%s",
                    entry.node_name,
                    entry.node_id,
                    entry.expires,
                )
        for key, entry in list(self._services.items()):
            if entry.is_local:
                continue
            if current_time > entry.expires:
                expired.append(entry)
                self._services.pop(key, None)
                LOGGER.info(
                    "SERVICE expired: service_name=%s provider=%s expires=%s",
                    entry.service_name,
                    entry.provider,
                    entry.expires,
                )
        return expired

    def save(self) -> None:
        if self.path is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as directory_file:
            json.dump(
                {
                    "nodes": [asdict(entry) for entry in self.list_nodes()],
                    "services": [asdict(entry) for entry in self.list_services()],
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

        if not isinstance(raw, dict):
            return store
        nodes = raw.get("nodes", [])
        services = raw.get("services", [])
        if not isinstance(nodes, list) or not isinstance(services, list):
            return store

        for raw_entry in nodes:
            entry = NodeEntry.from_json(raw_entry)
            if entry is not None:
                if local_node_id is not None:
                    entry.is_local = entry.node_id == local_node_id
                store._store_entry(entry)
        for raw_entry in services:
            entry = ServiceEntry.from_json(raw_entry)
            if entry is not None:
                if local_node_id is not None:
                    entry.is_local = entry.provider == local_node_id
                provider_entry = store._nodes_by_id.get(entry.provider)
                if provider_entry is not None:
                    entry.provider_name = provider_entry.node_name
                store._services[(entry.provider, entry.service_name)] = entry
        return store

    def _store_entry(self, entry: NodeEntry) -> None:
        existing = self._nodes_by_id.get(entry.node_id)
        if existing is not None and existing.node_name != entry.node_name:
            self._node_names.pop(existing.node_name, None)
        self._nodes_by_id[entry.node_id] = entry
        self._node_names[entry.node_name] = entry.node_id
        self._set_service_provider_name(entry.node_id, entry.node_name)

    def _set_service_provider_name(self, node_id: str, node_name: str) -> None:
        for service in self._services.values():
            if service.provider == node_id:
                service.provider_name = node_name

    def _update_service(
        self,
        knowledge_object: dict[str, Any],
        *,
        now: int | None = None,
        trust_state: TrustState = "unknown",
        accepted_limited: bool = False,
        signature_status: SignatureStatus = "signature_not_checked",
    ) -> AwarenessUpdate:
        service_data = _service_data_from_knowledge_object(knowledge_object)
        if service_data is None:
            return AwarenessUpdate("ignored", None)
        service_name, provider, capabilities, endpoint, protocol, version, expires, seq = (
            service_data
        )
        seen_at = _epoch(now)
        if seen_at > expires:
            return AwarenessUpdate("ignored", None)

        key = (provider, service_name)
        existing = self._services.get(key)
        provider_entry = self._nodes_by_id.get(provider)
        provider_name = provider_entry.node_name if provider_entry is not None else None
        if existing is not None:
            if seq < existing.seq:
                return AwarenessUpdate("ignored", existing)
            existing.provider_name = provider_name or existing.provider_name
            existing.capabilities = capabilities
            existing.endpoint = endpoint
            existing.protocol = protocol
            existing.service_version = version
            existing.last_seen = seen_at
            existing.expires = expires
            existing.is_local = provider == self.local_node_id
            existing.seq = seq
            existing.trust_state = trust_state
            existing.accepted_limited = accepted_limited
            existing.signature_status = signature_status
            LOGGER.info(
                "SERVICE refreshed: service_name=%s provider=%s seq=%s expires=%s signature_status=%s",
                service_name,
                provider,
                seq,
                expires,
                signature_status,
            )
            return AwarenessUpdate("refreshed", existing)

        entry = ServiceEntry(
            service_name=service_name,
            provider=provider,
            provider_name=provider_name,
            capabilities=capabilities,
            endpoint=endpoint,
            protocol=protocol,
            service_version=version,
            first_seen=seen_at,
            last_seen=seen_at,
            expires=expires,
            is_local=provider == self.local_node_id,
            seq=seq,
            trust_state=trust_state,
            accepted_limited=accepted_limited,
            signature_status=signature_status,
        )
        self._services[key] = entry
        LOGGER.info(
            "SERVICE discovered: service_name=%s provider=%s seq=%s expires=%s signature_status=%s",
            service_name,
            provider,
            seq,
            expires,
            signature_status,
        )
        return AwarenessUpdate("discovered", entry)


class DuplicateCache:
    """Recently processed Knowledge Object IDs."""

    def __init__(self, *, retention_seconds: int = DEFAULT_DUPLICATE_RETENTION) -> None:
        if (
            not isinstance(retention_seconds, int)
            or isinstance(retention_seconds, bool)
            or retention_seconds <= 0
        ):
            raise ValueError("retention_seconds must be a positive integer")
        self.retention_seconds = retention_seconds
        self._seen: dict[str, int] = {}

    def remember(self, ko_id: object, *, now: int | None = None) -> bool:
        """Return True for a new ko_id, False for a duplicate."""

        if not isinstance(ko_id, str) or not ko_id.strip():
            return False

        current_time = _epoch(now)
        self.expire_old(now=current_time)
        if ko_id in self._seen:
            LOGGER.info("Duplicate Knowledge Object suppressed: ko_id=%s", ko_id)
            return False

        self._seen[ko_id] = current_time
        return True

    def expire_old(self, *, now: int | None = None) -> None:
        current_time = _epoch(now)
        cutoff = current_time - self.retention_seconds
        for ko_id, seen_at in list(self._seen.items()):
            if seen_at <= cutoff:
                self._seen.pop(ko_id, None)

    def __contains__(self, ko_id: object) -> bool:
        return isinstance(ko_id, str) and ko_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)


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


def _service_data_from_knowledge_object(
    knowledge_object: dict[str, Any],
) -> tuple[str, str, list[str], str | None, str | None, str | None, int, int] | None:
    if knowledge_object.get("type") != "SERVICE":
        return None
    origin = knowledge_object.get("origin")
    subject = knowledge_object.get("subject")
    expires = knowledge_object.get("expires")
    seq = knowledge_object.get("seq")
    payload = knowledge_object.get("payload")
    if not isinstance(origin, str) or not isinstance(subject, str):
        return None
    if not isinstance(expires, int) or isinstance(expires, bool):
        return None
    if not isinstance(seq, int) or isinstance(seq, bool):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("provider") != origin or payload.get("service_name") != subject:
        return None
    capabilities = payload.get("capabilities", [])
    endpoint = payload.get("endpoint")
    protocol = payload.get("protocol")
    version = payload.get("service_version")
    if not isinstance(capabilities, list):
        return None
    return subject, origin, list(capabilities), endpoint, protocol, version, expires, seq


def _epoch(now: int | None) -> int:
    return int(time.time() if now is None else now)
