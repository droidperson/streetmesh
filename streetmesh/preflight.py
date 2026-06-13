"""Read-only service access preflight decisions."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable, Literal

from .directory import AwarenessStore, NodeEntry
from .name_bindings import NameConflict
from .protocol import SignatureStatus
from .resolver import Currentness, ServiceCandidate, resolve_service
from .trust import BindingStatus, TrustState


ServiceAccessDecision = Literal[
    "allowed",
    "denied",
    "limited",
    "ambiguous",
    "not_found",
    "conflict",
    "expired",
    "unsupported",
]
ProviderStatus = Literal["current", "expired", "missing"]
RECOGNIZED_PROTOCOLS = frozenset(
    {"http", "https", "file", "ssh", "sftp", "smb", "tcp", "udp"}
)
NO_NETWORK_ACCESS = "no network access performed"
_LIMITED_TRUST = {"unknown", "observed", "candidate"}
_REJECTED_TRUST = {"blocked", "revoked", "quarantined"}


@dataclass(frozen=True)
class ServicePreflightResult:
    service_name: str
    decision: ServiceAccessDecision
    reason: str
    provider_node_id: str | None
    provider_node_name: str | None
    provider_fingerprint: str | None
    public_key_id: str | None
    trust_state: TrustState | None
    signature_status: SignatureStatus | None
    binding_status: BindingStatus | None
    provider_status: ProviderStatus
    service_status: Currentness | None
    protocol: str | None
    endpoint: str | None
    provider_usable: bool
    service_limited: bool
    warnings: tuple[str, ...]
    candidate_count: int
    access_action: str = NO_NETWORK_ACCESS


def preflight_service(
    awareness: AwarenessStore,
    service_name: str,
    *,
    now: int | None = None,
    name_conflicts: Iterable[NameConflict] = (),
) -> ServicePreflightResult:
    """Build an access decision without contacting any advertised endpoint."""

    current_time = int(time.time() if now is None else now)
    resolution = resolve_service(awareness, service_name, now=current_time)
    chosen = resolution.chosen
    if chosen is None:
        return _result(
            service_name,
            "not_found",
            "No awareness entry advertises this service.",
            candidate_count=0,
        )

    provider = awareness.get_by_node_id(chosen.provider_node_id)
    provider_status = _provider_status(provider, current_time)
    binding_status = _effective_binding_status(chosen, provider)
    trust_state = _effective_trust_state(chosen, provider)
    provider_usable = _provider_is_usable(
        chosen,
        provider,
        provider_status,
        binding_status,
        trust_state,
    )
    service_limited = chosen.accepted_limited or trust_state in _LIMITED_TRUST
    warnings = _warnings(
        chosen,
        resolution.candidates,
        provider,
        name_conflicts,
    )
    common = {
        "provider": provider,
        "chosen": chosen,
        "provider_status": provider_status,
        "binding_status": binding_status,
        "trust_state": trust_state,
        "provider_usable": provider_usable,
        "service_limited": service_limited,
        "warnings": warnings,
        "candidate_count": len(resolution.candidates),
    }

    if chosen.status == "expired":
        return _result(
            service_name,
            "expired",
            "The selected service advertisement is expired.",
            **common,
        )
    if provider is None:
        return _result(
            service_name,
            "denied",
            "The service provider has no node awareness entry.",
            **common,
        )
    if provider_status == "expired":
        return _result(
            service_name,
            "expired",
            "The selected provider node awareness is expired.",
            **common,
        )
    if binding_status in {"name_conflict", "stale_binding"}:
        return _result(
            service_name,
            "conflict",
            "The selected provider identity conflicts with its node-name binding.",
            **common,
        )
    if trust_state in _REJECTED_TRUST:
        return _result(
            service_name,
            "denied",
            f"The provider trust state is {trust_state}.",
            **common,
        )
    if chosen.signature_status == "signature_invalid":
        return _result(
            service_name,
            "denied",
            "The service claim has an invalid verifiable signature.",
            **common,
        )
    if not chosen.protocol:
        return _result(
            service_name,
            "unsupported",
            "The service does not advertise a protocol.",
            **common,
        )
    if chosen.protocol.lower() not in RECOGNIZED_PROTOCOLS:
        return _result(
            service_name,
            "unsupported",
            f"The advertised protocol {chosen.protocol!r} is not recognized.",
            **common,
        )
    if not chosen.endpoint:
        return _result(
            service_name,
            "denied",
            "The service does not advertise an endpoint.",
            **common,
        )
    if resolution.resolution_status == "ambiguous" and not _clearly_preferred(
        chosen,
        resolution.candidates,
    ):
        return _result(
            service_name,
            "ambiguous",
            "Multiple current usable providers exist without a clear trusted bound winner.",
            **common,
        )
    if not provider_usable:
        return _result(
            service_name,
            "denied",
            "The selected provider is not usable under current trust and binding policy.",
            **common,
        )
    if trust_state == "privileged" and binding_status == "bound":
        return _result(
            service_name,
            "allowed",
            "Service resolved to a current local privileged provider.",
            **common,
        )
    if trust_state == "trusted" and binding_status == "bound":
        return _result(
            service_name,
            "allowed",
            "Service resolved to a current trusted bound provider.",
            **common,
        )
    return _result(
        service_name,
        "limited",
        "Service is visible, but provider trust or name binding is limited.",
        **common,
    )


def _result(
    service_name: str,
    decision: ServiceAccessDecision,
    reason: str,
    *,
    provider: NodeEntry | None = None,
    chosen: ServiceCandidate | None = None,
    provider_status: ProviderStatus = "missing",
    binding_status: BindingStatus | None = None,
    trust_state: TrustState | None = None,
    provider_usable: bool = False,
    service_limited: bool = False,
    warnings: tuple[str, ...] = (),
    candidate_count: int = 0,
) -> ServicePreflightResult:
    return ServicePreflightResult(
        service_name=service_name,
        decision=decision,
        reason=reason,
        provider_node_id=(chosen.provider_node_id if chosen is not None else None),
        provider_node_name=(
            provider.node_name
            if provider is not None
            else chosen.provider_node_name if chosen is not None else None
        ),
        provider_fingerprint=(provider.fingerprint if provider is not None else None),
        public_key_id=(provider.public_key_id if provider is not None else None),
        trust_state=trust_state,
        signature_status=(chosen.signature_status if chosen is not None else None),
        binding_status=binding_status,
        provider_status=provider_status,
        service_status=(chosen.status if chosen is not None else None),
        protocol=(chosen.protocol if chosen is not None else None),
        endpoint=(chosen.endpoint if chosen is not None else None),
        provider_usable=provider_usable,
        service_limited=service_limited,
        warnings=warnings,
        candidate_count=candidate_count,
    )


def _provider_status(provider: NodeEntry | None, now: int) -> ProviderStatus:
    if provider is None:
        return "missing"
    return "current" if provider.expires >= now else "expired"


def _effective_binding_status(
    chosen: ServiceCandidate,
    provider: NodeEntry | None,
) -> BindingStatus:
    if provider is not None and provider.binding_status in {
        "name_conflict",
        "stale_binding",
    }:
        return provider.binding_status
    if chosen.binding_status != "unknown":
        return chosen.binding_status
    return provider.binding_status if provider is not None else "unknown"


def _effective_trust_state(
    chosen: ServiceCandidate,
    provider: NodeEntry | None,
) -> TrustState:
    return provider.trust_state if provider is not None else chosen.trust_state


def _provider_is_usable(
    chosen: ServiceCandidate,
    provider: NodeEntry | None,
    provider_status: ProviderStatus,
    binding_status: BindingStatus,
    trust_state: TrustState,
) -> bool:
    return (
        chosen.usable
        and provider is not None
        and provider_status == "current"
        and trust_state not in _REJECTED_TRUST
        and binding_status not in {"name_conflict", "stale_binding"}
        and chosen.signature_status != "signature_invalid"
    )


def _clearly_preferred(
    chosen: ServiceCandidate,
    candidates: tuple[ServiceCandidate, ...],
) -> bool:
    if chosen.trust_state not in {"privileged", "trusted"}:
        return False
    if chosen.binding_status != "bound":
        return False
    return not any(
        candidate.provider_node_id != chosen.provider_node_id
        and candidate.status == "current"
        and candidate.usable
        and candidate.trust_state in {"privileged", "trusted"}
        and candidate.binding_status == "bound"
        for candidate in candidates
    )


def _warnings(
    chosen: ServiceCandidate,
    candidates: tuple[ServiceCandidate, ...],
    provider: NodeEntry | None,
    name_conflicts: Iterable[NameConflict],
) -> tuple[str, ...]:
    warnings: list[str] = []
    other_candidates = [
        candidate
        for candidate in candidates
        if candidate.provider_node_id != chosen.provider_node_id
    ]
    if other_candidates:
        warnings.append(
            f"{len(other_candidates)} other provider candidate(s) advertise this service."
        )
    if any(candidate.binding_status == "name_conflict" for candidate in candidates):
        warnings.append("At least one provider candidate has a node-name conflict.")
    if provider is not None and any(
        conflict.node_name == provider.node_name for conflict in name_conflicts
    ):
        warnings.append("Conflicting identities also claim the selected provider name.")
    return tuple(warnings)
