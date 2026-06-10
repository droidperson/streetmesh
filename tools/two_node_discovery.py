#!/usr/bin/env python3
"""Verify artifacts from the Milestone 7 two-node discovery manual test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


class VerificationError(ValueError):
    """Raised when a Milestone 7 acceptance condition is not met."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify two-node discovery logs and persisted awareness.",
    )
    parser.add_argument(
        "--node-a-data",
        type=Path,
        default=Path("m7-data/node-a"),
        help="Node A data directory",
    )
    parser.add_argument(
        "--node-b-data",
        type=Path,
        default=Path("m7-data/node-b"),
        help="Node B data directory",
    )
    parser.add_argument(
        "--node-a-log",
        type=Path,
        default=Path("m7-node-a.log"),
        help="captured Node A log",
    )
    parser.add_argument(
        "--node-b-log",
        type=Path,
        default=Path("m7-node-b.log"),
        help="captured Node B log",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        messages = verify_artifacts(
            node_a_data=args.node_a_data,
            node_b_data=args.node_b_data,
            node_a_log=args.node_a_log,
            node_b_log=args.node_b_log,
        )
    except (OSError, json.JSONDecodeError, KeyError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(f"PASS: {message}")
    print("Milestone 7 two-node discovery artifacts PASSED")
    return 0


def verify_artifacts(
    *,
    node_a_data: Path,
    node_b_data: Path,
    node_a_log: Path,
    node_b_log: Path,
) -> list[str]:
    """Validate identities, bidirectional discovery, expiry, and final state."""

    node_a_id, node_a_name = _read_identity(node_a_data / "identity.json")
    node_b_id, node_b_name = _read_identity(node_b_data / "identity.json")
    if node_a_id == node_b_id:
        raise VerificationError("Node A and Node B must have different identities")

    log_a = node_a_log.read_text(encoding="utf-8")
    log_b = node_b_log.read_text(encoding="utf-8")
    _require_log(
        log_a,
        f"Node discovered: node_name={node_b_name} node_id={node_b_id}",
        node_a_log,
    )
    _require_log(
        log_b,
        f"Node discovered: node_name={node_a_name} node_id={node_a_id}",
        node_b_log,
    )
    _require_log(
        log_b,
        f"NODE_EXPIRED node_name={node_a_name} node_id={node_a_id}",
        node_b_log,
    )

    awareness_ids = _read_awareness_ids(node_b_data / "awareness.json")
    if node_a_id in awareness_ids:
        raise VerificationError("Node A remains in Node B awareness after expiry")
    if node_b_id not in awareness_ids:
        raise VerificationError("Node B is missing from its own awareness store")

    return [
        "Node A and Node B use separate identities",
        "Node A discovered Node B",
        "Node B discovered Node A",
        "Node B logged NODE_EXPIRED for Node A",
        "Node A was removed from Node B awareness",
    ]


def _read_identity(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8") as identity_file:
        identity = json.load(identity_file)
    node_id = identity["node_id"]
    node_name = identity["node_name"]
    if not isinstance(node_id, str) or not node_id:
        raise VerificationError(f"invalid node_id in {path}")
    if not isinstance(node_name, str) or not node_name:
        raise VerificationError(f"invalid node_name in {path}")
    return node_id, node_name


def _read_awareness_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as awareness_file:
        nodes = json.load(awareness_file)["nodes"]
    if not isinstance(nodes, list):
        raise VerificationError(f"nodes must be a list in {path}")

    node_ids = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
            raise VerificationError(f"invalid node entry in {path}")
        node_ids.add(node["node_id"])
    return node_ids


def _require_log(contents: str, expected: str, path: Path) -> None:
    if expected not in contents:
        raise VerificationError(f"missing {expected!r} in {path}")


if __name__ == "__main__":
    raise SystemExit(main())
