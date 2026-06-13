"""Read-only node-name and service-provider resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Literal

from .directory import AwarenessStore, NodeEntry, ServiceEntry
from .name_bindings import NameBindingRegistry
from .protocol import SignatureStatus
from .trust import BindingStatus, TrustState


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
    "signed_self_verified": 8,
    "signed_unverified_remote": 7,
    "unsigned": 6,
    "signature_not_checked": 5,
    "public_key_planned": 4,
    "public_key_missing": 3,
    "public_key_unsupported": 2,
    "signature_unsupported": 1,
    "signature_invalid": 0,
}


@dataclass(frozen=True)
class NodeCandidate:
    node_name: str
    node_id: str
    trust_state: TrustState
    signature_status: SignatureStatus
    fingerprint: str | None
    public_key_id: str | None
    binding_status: BindingStatus
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
    def fingerprint(self) -> str | None:
        return self.chosen.fingerprint if self.chosen is not None else None

    @property
    def public_key_id(self) -> str | None:
        return self.chosen.public_key_id if self.chosen is not None else None

    @property
    def binding_status(self) -> BindingStatus | None:
        return self.chosen.binding_status if self.chosen is not None else None

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
    binding_status: BindingStatus
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
    def binding_status(self) -> BindingStatus | None:
        return self.chosen.binding_status if self.chosen is not None else None

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
    name_bindings: NameBindingRegistry | None = None,
) -> NodeResolution:
    """Resolve a node name without mutating awareness."""

    current_time = _epoch(now)
    matches = [
        entry for entry in awareness.list_nodes() if entry.node_name == node_name
    ]
    binding = name_bindings.get(node_name) if name_bindings is not None else None
    if name_bindings is not None:
        matches = [
            replace(
                entry,
                binding_status=name_bindings.status_for_claim(
                    entry.node_name,
                    entry.node_id,
                ),
            )
            for entry in matches
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

    bound_current = [
        candidate
        for candidate in ranked
        if candidate.binding_status == "bound"
        and candidate.usable
        and candidate.status == "current"
    ]
    conflicting = [
        candidate
        for candidate in ranked
        if candidate.binding_status == "name_conflict"
    ]
    if bound_current:
        return NodeResolution(
            "resolved",
            node_name,
            bound_current[0],
            tuple(ranked),
            (
                "The current bound identity is preferred; conflicting claimants are present."
                if conflicting
                else "The current bound identity owns this local name binding."
            ),
        )
    if binding is not None and any(
        candidate.node_id != binding.node_id for candidate in ranked
    ):
        bound_candidate = next(
            (
                candidate
                for candidate in ranked
                if candidate.node_id == binding.node_id
            ),
            None,
        )
        return NodeResolution(
            "conflict",
            node_name,
            bound_candidate or ranked[0],
            tuple(ranked),
            "The name is bound to a different identity that is not currently available.",
        )

    unbound_current = [
        candidate
        for candidate in ranked
        if candidate.status == "current"
        and candidate.binding_status in {"unbound", "unknown"}
    ]
    if binding is None and len(unbound_current) > 1:
        return NodeResolution(
            "conflict",
            node_name,
            unbound_current[0],
            tuple(ranked),
            "Multiple current unbound node IDs claim this node name.",
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
            fingerprint=entry.fingerprint,
            public_key_id=entry.public_key_id,
            binding_status=entry.binding_status,
            first_seen=entry.first_seen,
            last_seen=entry.last_seen,
            expires=entry.expires,
            status=_currentness(entry.expires, now),
            usable=_is_usable(
                entry.trust_state,
                entry.signature_status,
                entry.binding_status,
            ),
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
            binding_status=entry.binding_status,
            accepted_limited=entry.accepted_limited,
            first_seen=entry.first_seen,
            last_seen=entry.last_seen,
            expires=entry.expires,
            status=_currentness(entry.expires, now),
            usable=_is_usable(
                entry.trust_state,
                entry.signature_status,
                entry.binding_status,
            ),
            rank=index,
        )
        for index, entry in enumerate(ordered, start=1)
    ]


def _node_sort_key(entry: NodeEntry, now: int) -> tuple[object, ...]:
    return (
        -int(entry.expires >= now),
        -int(
            _is_usable(
                entry.trust_state,
                entry.signature_status,
                entry.binding_status,
            )
        ),
        -_TRUST_RANK[entry.trust_state],
        -_SIGNATURE_RANK[entry.signature_status],
        -_binding_rank(entry.binding_status),
        -entry.last_seen,
        -entry.expires,
        entry.node_id,
    )


def _service_sort_key(entry: ServiceEntry, now: int) -> tuple[object, ...]:
    return (
        -int(entry.expires >= now),
        -int(
            _is_usable(
                entry.trust_state,
                entry.signature_status,
                entry.binding_status,
            )
        ),
        -_TRUST_RANK[entry.trust_state],
        -_SIGNATURE_RANK[entry.signature_status],
        -_binding_rank(entry.binding_status),
        -entry.last_seen,
        -entry.expires,
        entry.provider,
    )


def _currentness(expires: int, now: int) -> Currentness:
    return "current" if expires >= now else "expired"


def _is_usable(
    trust_state: TrustState,
    signature_status: SignatureStatus,
    binding_status: BindingStatus,
) -> bool:
    return (
        trust_state not in _REJECTED_TRUST
        and signature_status != "signature_invalid"
        and binding_status not in {"name_conflict", "stale_binding"}
    )


def _binding_rank(binding_status: BindingStatus) -> int:
    return {
        "bound": 4,
        "unbound": 3,
        "unknown": 2,
        "stale_binding": 1,
        "name_conflict": 0,
    }[binding_status]


def _epoch(value: int | None) -> int:
    return int(time.time() if value is None else value)
