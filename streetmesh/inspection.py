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
            str(entry.first_seen),
            str(entry.last_seen),
            str(entry.expires),
            _expiry_status(entry.expires, current_time),
        ]
        for entry in nodes
    ]
    return _format_table(
        ["node_name", "node_id", "trust_state", "first_seen", "last_seen", "expires", "status"],
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
                entry.endpoint or "-",
                entry.protocol or "-",
                str(entry.expires),
                _expiry_status(entry.expires, current_time),
            ]
        )
    return _format_table(
        ["service_name", "provider", "trust", "endpoint", "protocol", "expires", "status"],
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


def _expiry_status(expires: int, now: int) -> str:
    return "expired" if now > expires else "current"


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
