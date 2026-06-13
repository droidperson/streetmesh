"""Read-only loading and formatting for StreetMesh CLI inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterable

from .config import StreetMeshConfig
from .directory import AwarenessStore, NodeEntry, ServiceEntry
from .identity import NodeIdentity, load_identity
from .policy import ReviewPolicy
from .resolver import NodeResolution, ServiceResolution
from .trust import TrustEntry, TrustStore


@dataclass(frozen=True)
class InspectionState:
    identity: NodeIdentity | None
    awareness: AwarenessStore
    trust: TrustStore


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
    explicit_trust = {
        entry.node_id: entry.state for entry in trust.list_entries()
    }
    for node in awareness.list_nodes():
        if node.node_id == local_node_id:
            node.trust_state = "privileged"
        elif node.node_id in explicit_trust:
            node.trust_state = explicit_trust[node.node_id]
    for service in awareness.list_services():
        if service.provider in explicit_trust:
            service.trust_state = explicit_trust[service.provider]
            service.accepted_limited = service.trust_state in {
                "unknown",
                "observed",
                "candidate",
            }
    return InspectionState(
        identity=identity,
        awareness=awareness,
        trust=trust,
    )


def format_status(state: InspectionState, config: StreetMeshConfig) -> str:
    identity = state.identity
    values = [
        ("local node_id", identity.node_id if identity is not None else "(not created)"),
        (
            "local node_name",
            identity.node_name if identity is not None else config.node.node_name,
        ),
        ("UDP port", str(config.node.udp_port)),
        ("policy mode", ReviewPolicy.mode),
        ("known nodes", str(len(state.awareness.list_nodes()))),
        ("known services", str(len(state.awareness.list_services()))),
        ("trust entries", str(len(state.trust.list_entries()))),
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
            "endpoint",
            "protocol",
            "expires",
            "status",
        ],
        rows,
        empty_message="No known services.",
    )


def format_trust(entries: Iterable[TrustEntry]) -> str:
    rows = [[entry.node_id, entry.state] for entry in entries]
    return _format_table(
        ["node_id", "state"],
        rows,
        empty_message="No trust entries.",
    )


def format_node_resolution(result: NodeResolution) -> str:
    values = [
        ("resolution_status", result.resolution_status),
        ("node_name", result.node_name),
        ("node_id", result.node_id or "-"),
        ("trust_state", result.trust_state or "-"),
        ("signature_status", result.signature_status or "-"),
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
                candidate.status,
                "yes" if candidate.usable else "no",
            ]
            for candidate in result.candidates
        ]
        output += "\n\ncandidates\n" + _format_table(
            ["rank", "node_id", "trust_state", "signature_status", "status", "usable"],
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
