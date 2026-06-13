"""Read-only node-name and service-provider resolution."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal

from .directory import AwarenessStore, NodeEntry, ServiceEntry
from .protocol import SignatureStatus
from .trust import TrustState


Currentness = Literal["current", "expired"]
ResolutionStatus = Literal[
    "resolved",
    "limited",
    "expired",
    "not_found",
    "ambiguous",
    "rejected",
    "conflict",
]

_REJECTED_TRUST = {"blocked", "revoked", "quarantined"}
_TRUST_RANK = {
    "privileged": 7,
    "trusted": 6,
    "candidate": 5,
    "observed": 4,
    "unknown": 3,
    "quarantined": 2,
    "blocked": 1,
    "revoked": 0,
}
_SIGNATURE_RANK = {
    "signed_self_verified": 5,
    "signed_unverified_remote": 4,
    "unsigned": 3,
    "signature_not_checked": 2,
    "signature_unsupported": 1,
    "signature_invalid": 0,
}


@dataclass(frozen=True)
class NodeCandidate:
    node_name: str
    node_id: str
    trust_state: TrustState
    signature_status: SignatureStatus
    first_seen: int
    last_seen: int
    expires: int
    status: Currentness
    usable: bool
    rank: int


@dataclass(frozen=True)
class NodeResolution:
    resolution_status: ResolutionStatus
    node_name: str
    chosen: NodeCandidate | None
    candidates: tuple[NodeCandidate, ...]
    reason: str

    @property
    def node_id(self) -> str | None:
        return self.chosen.node_id if self.chosen is not None else None

    @property
    def trust_state(self) -> TrustState | None:
        return self.chosen.trust_state if self.chosen is not None else None

    @property
    def signature_status(self) -> SignatureStatus | None:
        return self.chosen.signature_status if self.chosen is not None else None

    @property
    def first_seen(self) -> int | None:
        return self.chosen.first_seen if self.chosen is not None else None

    @property
    def last_seen(self) -> int | None:
        return self.chosen.last_seen if self.chosen is not None else None

    @property
    def expires(self) -> int | None:
        return self.chosen.expires if self.chosen is not None else None

    @property
    def status(self) -> Currentness | None:
        return self.chosen.status if self.chosen is not None else None


@dataclass(frozen=True)
class ServiceCandidate:
    service_name: str
    provider_node_id: str
    provider_node_name: str | None
    endpoint: str | None
    protocol: str | None
    trust_state: TrustState
    signature_status: SignatureStatus
    accepted_limited: bool
    first_seen: int
    last_seen: int
    expires: int
    status: Currentness
    usable: bool
    rank: int


@dataclass(frozen=True)
class ServiceResolution:
    resolution_status: ResolutionStatus
    service_name: str
    chosen: ServiceCandidate | None
    candidates: tuple[ServiceCandidate, ...]
    reason: str

    @property
    def provider_node_id(self) -> str | None:
        return (
            self.chosen.provider_node_id if self.chosen is not None else None
        )

    @property
    def provider_node_name(self) -> str | None:
        return (
            self.chosen.provider_node_name if self.chosen is not None else None
        )

    @property
    def endpoint(self) -> str | None:
        return self.chosen.endpoint if self.chosen is not None else None

    @property
    def protocol(self) -> str | None:
        return self.chosen.protocol if self.chosen is not None else None

    @property
    def trust_state(self) -> TrustState | None:
        return self.chosen.trust_state if self.chosen is not None else None

    @property
    def signature_status(self) -> SignatureStatus | None:
        return self.chosen.signature_status if self.chosen is not None else None

    @property
    def expires(self) -> int | None:
        return self.chosen.expires if self.chosen is not None else None

    @property
    def status(self) -> Currentness | None:
        return self.chosen.status if self.chosen is not None else None


def resolve_node(
    awareness: AwarenessStore,
    node_name: str,
    *,
    now: int | None = None,
) -> NodeResolution:
    """Resolve a node name without mutating awareness."""

    current_time = _epoch(now)
    matches = [
        entry for entry in awareness.list_nodes() if entry.node_name == node_name
    ]
    ranked = _rank_nodes(matches, current_time)
    if not ranked:
        return NodeResolution(
            "not_found",
            node_name,
            None,
            (),
            "No awareness entry matches this node name.",
        )

    usable_current = [
        candidate
        for candidate in ranked
        if candidate.usable and candidate.status == "current"
    ]
    if len(usable_current) > 1:
        return NodeResolution(
            "conflict",
            node_name,
            usable_current[0],
            tuple(ranked),
            "Multiple current usable node IDs claim this node name.",
        )
    if usable_current:
        return NodeResolution(
            "resolved",
            node_name,
            usable_current[0],
            tuple(ranked),
            "One current usable node matches this name.",
        )

    current = [candidate for candidate in ranked if candidate.status == "current"]
    if current:
        return NodeResolution(
            "rejected",
            node_name,
            current[0],
            tuple(ranked),
            "Current matches exist, but their trust state is not usable.",
        )
    return NodeResolution(
        "expired",
        node_name,
        ranked[0],
        tuple(ranked),
        "Only expired awareness matches this node name.",
    )


def resolve_service(
    awareness: AwarenessStore,
    service_name: str,
    *,
    now: int | None = None,
) -> ServiceResolution:
    """Resolve and rank providers for an exact service name."""

    current_time = _epoch(now)
    matches = [
        entry
        for entry in awareness.list_services()
        if entry.service_name == service_name
    ]
    ranked = _rank_services(matches, current_time)
    if not ranked:
        return ServiceResolution(
            "not_found",
            service_name,
            None,
            (),
            "No awareness entry advertises this service name.",
        )

    usable_current = [
        candidate
        for candidate in ranked
        if candidate.usable and candidate.status == "current"
    ]
    if len(usable_current) > 1:
        return ServiceResolution(
            "ambiguous",
            service_name,
            usable_current[0],
            tuple(ranked),
            "Multiple current usable providers exist; the highest-ranked candidate is preferred.",
        )
    if usable_current:
        chosen = usable_current[0]
        limited = chosen.accepted_limited or chosen.trust_state in {
            "unknown",
            "observed",
            "candidate",
        }
        return ServiceResolution(
            "limited" if limited else "resolved",
            service_name,
            chosen,
            tuple(ranked),
            (
                "The preferred provider is visible with limited trust."
                if limited
                else "One current trusted provider matches this service."
            ),
        )

    current = [candidate for candidate in ranked if candidate.status == "current"]
    if current:
        return ServiceResolution(
            "rejected",
            service_name,
            current[0],
            tuple(ranked),
            "Current providers exist, but their trust state is not usable.",
        )
    return ServiceResolution(
        "expired",
        service_name,
        ranked[0],
        tuple(ranked),
        "Only expired providers advertise this service.",
    )


def _rank_nodes(entries: list[NodeEntry], now: int) -> list[NodeCandidate]:
    ordered = sorted(entries, key=lambda entry: _node_sort_key(entry, now))
    return [
        NodeCandidate(
            node_name=entry.node_name,
            node_id=entry.node_id,
            trust_state=entry.trust_state,
            signature_status=entry.signature_status,
            first_seen=entry.first_seen,
            last_seen=entry.last_seen,
            expires=entry.expires,
            status=_currentness(entry.expires, now),
            usable=_is_usable(entry.trust_state, entry.signature_status),
            rank=index,
        )
        for index, entry in enumerate(ordered, start=1)
    ]


def _rank_services(
    entries: list[ServiceEntry],
    now: int,
) -> list[ServiceCandidate]:
    ordered = sorted(entries, key=lambda entry: _service_sort_key(entry, now))
    return [
        ServiceCandidate(
            service_name=entry.service_name,
            provider_node_id=entry.provider,
            provider_node_name=entry.provider_name,
            endpoint=entry.endpoint,
            protocol=entry.protocol,
            trust_state=entry.trust_state,
            signature_status=entry.signature_status,
            accepted_limited=entry.accepted_limited,
            first_seen=entry.first_seen,
            last_seen=entry.last_seen,
            expires=entry.expires,
            status=_currentness(entry.expires, now),
            usable=_is_usable(entry.trust_state, entry.signature_status),
            rank=index,
        )
        for index, entry in enumerate(ordered, start=1)
    ]


def _node_sort_key(entry: NodeEntry, now: int) -> tuple[object, ...]:
    return (
        -int(entry.expires >= now),
        -int(_is_usable(entry.trust_state, entry.signature_status)),
        -_TRUST_RANK[entry.trust_state],
        -_SIGNATURE_RANK[entry.signature_status],
        -entry.last_seen,
        -entry.expires,
        entry.node_id,
    )


def _service_sort_key(entry: ServiceEntry, now: int) -> tuple[object, ...]:
    return (
        -int(entry.expires >= now),
        -int(_is_usable(entry.trust_state, entry.signature_status)),
        -_TRUST_RANK[entry.trust_state],
        -_SIGNATURE_RANK[entry.signature_status],
        -entry.last_seen,
        -entry.expires,
        entry.provider,
    )


def _currentness(expires: int, now: int) -> Currentness:
    return "current" if expires >= now else "expired"


def _is_usable(
    trust_state: TrustState,
    signature_status: SignatureStatus,
) -> bool:
    return (
        trust_state not in _REJECTED_TRUST
        and signature_status != "signature_invalid"
    )


def _epoch(value: int | None) -> int:
    return int(time.time() if value is None else value)
