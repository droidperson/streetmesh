"""Read-only loading and formatting for StreetMesh CLI inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Iterable

from .config import StreetMeshConfig
from .directory import AwarenessStore, NodeEntry, ServiceEntry
from .identity import NodeIdentity, load_identity
from .name_bindings import NameBinding, NameBindingRegistry, NameConflict
from .policy import ReviewPolicy
from .preflight import ServicePreflightResult
from .resolver import NodeResolution, ServiceResolution
from .trust import TrustEntry, TrustStore


@dataclass(frozen=True)
class InspectionState:
    identity: NodeIdentity | None
    awareness: AwarenessStore
    trust: TrustStore
    name_bindings: NameBindingRegistry = field(default_factory=NameBindingRegistry)

    def list_name_conflicts(self, *, now: int | None = None) -> list[NameConflict]:
        """Return recorded conflicts plus active claimants from awareness."""

        current_time = int(time.time() if now is None else now)
        conflicts = {
            (entry.node_name, entry.claimant_node_id): entry
            for entry in self.name_bindings.list_conflicts()
        }
        for node in self.awareness.list_nodes():
            binding = self.name_bindings.get(node.node_name)
            if (
                binding is None
                or binding.node_id == node.node_id
                or node.expires < current_time
            ):
                continue
            key = (node.node_name, node.node_id)
            recorded = conflicts.get(key)
            conflicts[key] = NameConflict(
                node_name=node.node_name,
                bound_node_id=binding.node_id,
                claimant_node_id=node.node_id,
                claimant_fingerprint=node.fingerprint,
                claimant_public_key_id=node.public_key_id,
                first_seen=(
                    recorded.first_seen if recorded is not None else node.first_seen
                ),
                last_seen=max(
                    node.last_seen,
                    recorded.last_seen if recorded is not None else 0,
                ),
                reason="active-name-claim-conflicts-with-binding",
            )
        return sorted(
            conflicts.values(),
            key=lambda entry: (entry.node_name, entry.claimant_node_id),
        )


def load_inspection_state(data_dir: Path) -> InspectionState:
    """Load persisted local state without creating an identity or daemon."""

    identity_path = data_dir / "identity.json"
    identity = load_identity(identity_path) if identity_path.exists() else None
    local_node_id = identity.node_id if identity is not None else None
    awareness = AwarenessStore.load(
        data_dir / "awareness.json",
        local_node_id=local_node_id,
    )
    trust = TrustStore.load(
        data_dir / "trust.json",
        create_if_missing=False,
    )
    name_bindings = NameBindingRegistry.load(data_dir / "name_bindings.json")
    if identity is not None and name_bindings.get(identity.node_name) is None:
        name_bindings.bind_local(
            identity.node_name,
            identity.node_id,
            fingerprint=identity.fingerprint,
            public_key_id=identity.public_key_id,
            save=False,
        )
    for entry in trust.list_entries():
        if (
            entry.node_name is not None
            and entry.binding_status == "bound"
            and name_bindings.get(entry.node_name) is None
        ):
            name_bindings.bind(
                entry.node_name,
                entry.node_id,
                fingerprint=entry.fingerprint,
                public_key_id=entry.public_key_id,
                source="trusted" if entry.state == "trusted" else "manual",
                notes="legacy trust binding",
                save=False,
            )
    explicit_trust = {
        entry.node_id: entry.state for entry in trust.list_entries()
    }
    for node in awareness.list_nodes():
        if node.node_id == local_node_id:
            node.trust_state = "privileged"
            node.binding_status = "bound"
        elif node.node_id in explicit_trust:
            node.trust_state = explicit_trust[node.node_id]
        if node.node_id != local_node_id:
            node.binding_status = name_bindings.status_for_claim(
                node.node_name,
                node.node_id,
            )
            if node.binding_status in {"unknown", "unbound"}:
                node.binding_status = trust.binding_status_for_claim(
                    node.node_id,
                    node.node_name,
                )
    for service in awareness.list_services():
        if service.provider in explicit_trust:
            service.trust_state = explicit_trust[service.provider]
            service.accepted_limited = service.trust_state in {
                "unknown",
                "observed",
                "candidate",
            }
        provider = awareness.get_by_node_id(service.provider)
        if provider is not None:
            service.provider_name = provider.node_name
            service.binding_status = provider.binding_status
        else:
            trust_entry = trust.get_entry(service.provider)
            if trust_entry is not None:
                service.provider_name = (
                    trust_entry.node_name or service.provider_name
                )
                service.binding_status = trust_entry.binding_status
    return InspectionState(
        identity=identity,
        awareness=awareness,
        trust=trust,
        name_bindings=name_bindings,
    )


def format_status(state: InspectionState, config: StreetMeshConfig) -> str:
    identity = state.identity
    values = [
        ("local node_id", identity.node_id if identity is not None else "(not created)"),
        (
            "local node_name",
            identity.node_name if identity is not None else config.node.node_name,
        ),
        (
            "signing algorithm",
            identity.signing_algorithm if identity is not None else "(not created)",
        ),
        (
            "public key status",
            identity.public_key_status if identity is not None else "(not created)",
        ),
        ("UDP port", str(config.node.udp_port)),
        ("policy mode", ReviewPolicy.mode),
        ("known nodes", str(len(state.awareness.list_nodes()))),
        ("known services", str(len(state.awareness.list_services()))),
        ("trust entries", str(len(state.trust.list_entries()))),
        ("name bindings", str(len(state.name_bindings.list_bindings()))),
        ("name conflicts", str(len(state.name_bindings.list_conflicts()))),
    ]
    width = max(len(label) for label, _value in values)
    return "\n".join(f"{label:<{width}} : {value}" for label, value in values)


def format_nodes(nodes: Iterable[NodeEntry], *, now: int | None = None) -> str:
    current_time = int(time.time() if now is None else now)
    rows = [
        [
            entry.node_name,
            entry.node_id,
            entry.trust_state,
            entry.signature_status,
            entry.binding_status,
            entry.fingerprint or "-",
            entry.public_key_id or "-",
            str(entry.first_seen),
            str(entry.last_seen),
            str(entry.expires),
            _expiry_status(entry.expires, current_time),
        ]
        for entry in nodes
    ]
    return _format_table(
        [
            "node_name",
            "node_id",
            "trust_state",
            "signature_status",
            "binding_status",
            "fingerprint",
            "public_key_id",
            "first_seen",
            "last_seen",
            "expires",
            "status",
        ],
        rows,
        empty_message="No known nodes.",
    )


def format_services(
    services: Iterable[ServiceEntry],
    *,
    now: int | None = None,
) -> str:
    current_time = int(time.time() if now is None else now)
    rows = []
    for entry in services:
        trust = (
            f"{entry.trust_state} (limited)"
            if entry.accepted_limited
            else entry.trust_state
        )
        rows.append(
            [
                entry.service_name,
                entry.provider,
                trust,
                entry.signature_status,
                entry.binding_status,
                entry.endpoint or "-",
                entry.protocol or "-",
                str(entry.expires),
                _expiry_status(entry.expires, current_time),
            ]
        )
    return _format_table(
        [
            "service_name",
            "provider",
            "trust",
            "signature_status",
            "binding_status",
            "endpoint",
            "protocol",
            "expires",
            "status",
        ],
        rows,
        empty_message="No known services.",
    )


def format_trust(entries: Iterable[TrustEntry]) -> str:
    rows = [
        [
            entry.node_name or "-",
            entry.node_id,
            entry.state,
            entry.fingerprint or "-",
            entry.public_key_id or "-",
            entry.binding_status,
            _optional_number(entry.first_trusted),
            _optional_number(entry.last_confirmed),
        ]
        for entry in entries
    ]
    return _format_table(
        [
            "node_name",
            "node_id",
            "trust_state",
            "fingerprint",
            "public_key_id",
            "binding_status",
            "first_trusted",
            "last_confirmed",
        ],
        rows,
        empty_message="No trust entries.",
    )


def format_trust_detail(entry: TrustEntry) -> str:
    return _format_values(
        [
            ("node_name", entry.node_name or "-"),
            ("node_id", entry.node_id),
            ("trust_state", entry.state),
            ("fingerprint", entry.fingerprint or "-"),
            ("public_key_id", entry.public_key_id or "-"),
            ("binding_status", entry.binding_status),
            ("first_trusted", _optional_number(entry.first_trusted)),
            ("last_confirmed", _optional_number(entry.last_confirmed)),
        ]
    )


def format_trust_change(
    entry: TrustEntry,
    *,
    previous_state: str,
    signature_status: str,
) -> str:
    return _format_values(
        [
            ("node_name", entry.node_name or "-"),
            ("node_id", entry.node_id),
            ("previous_trust_state", previous_state),
            ("new_trust_state", entry.state),
            ("signature_status", signature_status),
            ("binding_status", entry.binding_status),
            ("fingerprint", entry.fingerprint or "-"),
            ("public_key_id", entry.public_key_id or "-"),
            ("first_trusted", _optional_number(entry.first_trusted)),
            ("last_confirmed", _optional_number(entry.last_confirmed)),
        ]
    )


def format_name_bindings(
    bindings: Iterable[NameBinding],
    trust: TrustStore,
) -> str:
    rows = [
        [
            entry.node_name,
            entry.node_id,
            entry.fingerprint or "-",
            entry.public_key_id or "-",
            entry.binding_state,
            trust.get_state(entry.node_id),
            str(entry.first_bound),
            str(entry.last_confirmed),
            entry.source,
        ]
        for entry in bindings
    ]
    return _format_table(
        [
            "node_name",
            "node_id",
            "fingerprint",
            "public_key_id",
            "binding_state",
            "trust_state",
            "first_bound",
            "last_confirmed",
            "source",
        ],
        rows,
        empty_message="No name bindings.",
    )


def format_name_binding_detail(
    binding: NameBinding,
    trust: TrustStore,
    conflicts: Iterable[NameConflict] = (),
) -> str:
    matching_conflicts = [
        conflict for conflict in conflicts if conflict.node_name == binding.node_name
    ]
    return _format_values(
        [
            ("node_name", binding.node_name),
            ("node_id", binding.node_id),
            ("fingerprint", binding.fingerprint or "-"),
            ("public_key_id", binding.public_key_id or "-"),
            ("binding_state", binding.binding_state),
            ("trust_state", trust.get_state(binding.node_id)),
            ("first_bound", str(binding.first_bound)),
            ("last_confirmed", str(binding.last_confirmed)),
            ("source", binding.source),
            ("notes", binding.notes or "-"),
            ("conflict_count", str(len(matching_conflicts))),
        ]
    )


def format_name_conflicts(
    conflicts: Iterable[NameConflict],
    trust: TrustStore,
) -> str:
    rows = [
        [
            conflict.node_name,
            conflict.bound_node_id,
            conflict.claimant_node_id,
            conflict.claimant_fingerprint or "-",
            conflict.claimant_public_key_id or "-",
            trust.get_state(conflict.claimant_node_id),
            str(conflict.first_seen),
            str(conflict.last_seen),
            conflict.reason,
        ]
        for conflict in conflicts
    ]
    return _format_table(
        [
            "node_name",
            "bound_node_id",
            "claimant_node_id",
            "fingerprint",
            "public_key_id",
            "claimant_trust",
            "first_seen",
            "last_seen",
            "reason",
        ],
        rows,
        empty_message="No name conflicts.",
    )


def format_service_preflight(result: ServicePreflightResult) -> str:
    return _format_values(
        [
            ("service_name", result.service_name),
            ("decision", result.decision),
            ("reason", result.reason),
            ("provider_node_name", result.provider_node_name or "-"),
            ("provider_node_id", result.provider_node_id or "-"),
            ("provider_fingerprint", result.provider_fingerprint or "-"),
            ("public_key_id", result.public_key_id or "-"),
            ("trust_state", result.trust_state or "-"),
            ("signature_status", result.signature_status or "-"),
            ("binding_status", result.binding_status or "-"),
            ("provider_status", result.provider_status),
            ("service_status", result.service_status or "-"),
            ("protocol", result.protocol or "-"),
            ("endpoint", result.endpoint or "-"),
            ("provider_usable", "yes" if result.provider_usable else "no"),
            ("service_limited", "yes" if result.service_limited else "no"),
            (
                "warnings",
                "; ".join(result.warnings) if result.warnings else "none",
            ),
            ("candidate_count", str(result.candidate_count)),
            ("access_action", result.access_action),
        ]
    )


def format_node_resolution(result: NodeResolution) -> str:
    values = [
        ("resolution_status", result.resolution_status),
        ("node_name", result.node_name),
        ("node_id", result.node_id or "-"),
        ("trust_state", result.trust_state or "-"),
        ("signature_status", result.signature_status or "-"),
        ("public_key_id", result.public_key_id or "-"),
        ("binding_status", result.binding_status or "-"),
        ("first_seen", _optional_number(result.first_seen)),
        ("last_seen", _optional_number(result.last_seen)),
        ("expires", _optional_number(result.expires)),
        ("status", result.status or "-"),
        ("candidate_count", str(len(result.candidates))),
        ("reason", result.reason),
    ]
    output = _format_values(values)
    if len(result.candidates) > 1:
        rows = [
            [
                str(candidate.rank),
                candidate.node_id,
                candidate.trust_state,
                candidate.signature_status,
                candidate.binding_status,
                candidate.status,
                "yes" if candidate.usable else "no",
            ]
            for candidate in result.candidates
        ]
        output += "\n\ncandidates\n" + _format_table(
            [
                "rank",
                "node_id",
                "trust_state",
                "signature_status",
                "binding_status",
                "status",
                "usable",
            ],
            rows,
            empty_message="No candidates.",
        )
    return output


def format_service_resolution(result: ServiceResolution) -> str:
    values = [
        ("resolution_status", result.resolution_status),
        ("service_name", result.service_name),
        ("provider_node_id", result.provider_node_id or "-"),
        ("provider_node_name", result.provider_node_name or "-"),
        ("endpoint", result.endpoint or "-"),
        ("protocol", result.protocol or "-"),
        ("trust_state", result.trust_state or "-"),
        ("signature_status", result.signature_status or "-"),
        ("binding_status", result.binding_status or "-"),
        ("expires", _optional_number(result.expires)),
        ("status", result.status or "-"),
        ("candidate_count", str(len(result.candidates))),
        ("reason", result.reason),
    ]
    output = _format_values(values)
    if len(result.candidates) > 1:
        rows = [
            [
                str(candidate.rank),
                candidate.provider_node_id,
                candidate.provider_node_name or "-",
                candidate.trust_state,
                candidate.signature_status,
                candidate.binding_status,
                candidate.status,
                "yes" if candidate.usable else "no",
                "yes" if candidate.accepted_limited else "no",
                candidate.endpoint or "-",
                candidate.protocol or "-",
            ]
            for candidate in result.candidates
        ]
        output += "\n\ncandidates\n" + _format_table(
            [
                "rank",
                "provider",
                "provider_name",
                "trust_state",
                "signature_status",
                "binding_status",
                "status",
                "usable",
                "limited",
                "endpoint",
                "protocol",
            ],
            rows,
            empty_message="No candidates.",
        )
    return output


def _expiry_status(expires: int, now: int) -> str:
    return "expired" if now > expires else "current"


def _optional_number(value: int | None) -> str:
    return str(value) if value is not None else "-"


def _format_values(values: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _value in values)
    return "\n".join(f"{label:<{width}} : {value}" for label, value in values)


def _format_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    empty_message: str,
) -> str:
    if not rows:
        return empty_message
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    header = _format_row(headers, widths)
    divider = "  ".join("-" * width for width in widths)
    body = [_format_row(row, widths) for row in rows]
    return "\n".join([header, divider, *body])


def _format_row(values: list[str], widths: list[int]) -> str:
    return "  ".join(
        value if index == len(values) - 1 else value.ljust(widths[index])
        for index, value in enumerate(values)
    )
