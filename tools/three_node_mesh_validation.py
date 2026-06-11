#!/usr/bin/env python3
"""Verify artifacts from the Milestone 13 three-node mesh test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


EXPECTED_NAMES = {
    "laptop": "laptop@local@mesh",
    "pi": "pi01@local@mesh",
    "test": "laptop-test@local@mesh",
}


class VerificationError(ValueError):
    """Raised when a Milestone 13 acceptance condition is not met."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify three-node mesh logs and persisted state.",
    )
    for key, label in (
        ("laptop", "Windows laptop"),
        ("pi", "Raspberry Pi"),
        ("test", "second laptop test node"),
    ):
        parser.add_argument(
            f"--{key}-data",
            type=Path,
            default=Path(f"m13-artifacts/{key}/data"),
            help=f"{label} copied data directory",
        )
        parser.add_argument(
            f"--{key}-log",
            type=Path,
            default=Path(f"m13-artifacts/{key}/streetmesh.log"),
            help=f"{label} combined test log",
        )
    parser.add_argument(
        "--service-name",
        default="temperature",
        help="service expected from the Raspberry Pi",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        messages = verify_artifacts(
            laptop_data=args.laptop_data,
            pi_data=args.pi_data,
            test_data=args.test_data,
            laptop_log=args.laptop_log,
            pi_log=args.pi_log,
            test_log=args.test_log,
            service_name=args.service_name,
        )
    except (OSError, json.JSONDecodeError, KeyError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(f"PASS: {message}")
    print("Milestone 13 three-node mesh artifacts PASSED")
    return 0


def verify_artifacts(
    *,
    laptop_data: Path,
    pi_data: Path,
    test_data: Path,
    laptop_log: Path,
    pi_log: Path,
    test_log: Path,
    service_name: str = "temperature",
) -> list[str]:
    """Validate final state, discovery, gossip, trust, expiry, and restart."""

    data_paths = {
        "laptop": laptop_data,
        "pi": pi_data,
        "test": test_data,
    }
    log_paths = {
        "laptop": laptop_log,
        "pi": pi_log,
        "test": test_log,
    }
    identities = {
        key: _read_identity(path / "identity.json")
        for key, path in data_paths.items()
    }
    for key, (_node_id, node_name) in identities.items():
        if node_name != EXPECTED_NAMES[key]:
            raise VerificationError(
                f"expected {EXPECTED_NAMES[key]!r} in {data_paths[key] / 'identity.json'}"
            )
    node_ids = {node_id for node_id, _node_name in identities.values()}
    if len(node_ids) != 3:
        raise VerificationError("the three nodes must use distinct identities")

    awareness = {
        key: _read_awareness(path / "awareness.json")
        for key, path in data_paths.items()
    }
    for key, state in awareness.items():
        known_ids = {
            node.get("node_id")
            for node in state["nodes"]
            if isinstance(node, dict)
        }
        missing = node_ids - known_ids
        if missing:
            raise VerificationError(
                f"{key} final awareness is missing node ID(s): {', '.join(sorted(missing))}"
            )

    pi_id = identities["pi"][0]
    services_by_observer = {}
    for key in ("laptop", "test"):
        service = _find_service(awareness[key]["services"], pi_id, service_name)
        if service is None:
            raise VerificationError(
                f"{key} awareness is missing {service_name!r} from the Pi"
            )
        services_by_observer[key] = service

    laptop_service = services_by_observer["laptop"]
    if laptop_service.get("trust_state") != "trusted":
        raise VerificationError("Windows laptop Pi service is not marked trusted")
    if laptop_service.get("accepted_limited") is not False:
        raise VerificationError("Windows laptop Pi service remains accepted-limited")

    trust = _read_trust(laptop_data / "trust.json")
    if trust.get(pi_id) != "trusted":
        raise VerificationError("Windows laptop does not mark the Pi trusted")

    logs = {
        key: path.read_text(encoding="utf-8") for key, path in log_paths.items()
    }
    for observer in ("laptop", "pi", "test"):
        for subject in ("laptop", "pi", "test"):
            if observer == subject:
                continue
            subject_id, subject_name = identities[subject]
            _require_log(
                logs[observer],
                f"Node discovered: node_name={subject_name} node_id={subject_id}",
                log_paths[observer],
            )

    _require_log(
        logs["laptop"],
        f"SERVICE discovered: service_name={service_name} provider={pi_id}",
        laptop_log,
    )
    _require_log(
        logs["test"],
        f"SERVICE discovered: service_name={service_name} provider={pi_id}",
        test_log,
    )
    _require_regex(
        "\n".join(logs.values()),
        rf"Gossip forwarded: ko_id=[^ ]+ origin={re.escape(pi_id)} ttl=3 forwarded_ttl=2",
        "combined node logs",
    )
    _require_log(
        "\n".join(logs.values()),
        "Duplicate Knowledge Object suppressed: ko_id=",
        Path("combined node logs"),
    )
    for observer in ("laptop", "test"):
        _require_log_order(
            logs[observer],
            f"NODE_EXPIRED node_name={identities['pi'][1]} node_id={pi_id}",
            f"Node discovered: node_name={identities['pi'][1]} node_id={pi_id}",
            log_paths[observer],
        )
    _require_log(
        logs["laptop"],
        f"trust_state=trusted reason=service-trusted",
        laptop_log,
    )

    return [
        "three distinct expected node identities were used",
        "all nodes finished with three-node awareness",
        f"{service_name} from the Pi is visible on both laptops",
        "the Windows laptop trust store marks the Pi trusted",
        "all nodes logged discovery of both peers",
        "gossip forwarded a Pi claim with reduced TTL",
        "both laptop observers logged Pi expiry followed by re-discovery",
        "the Windows laptop accepted the trusted Pi service normally",
    ]


def _read_identity(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8") as identity_file:
        value = json.load(identity_file)
    node_id = value["node_id"]
    node_name = value["node_name"]
    if not isinstance(node_id, str) or not node_id:
        raise VerificationError(f"invalid node_id in {path}")
    if not isinstance(node_name, str) or not node_name:
        raise VerificationError(f"invalid node_name in {path}")
    return node_id, node_name


def _read_awareness(path: Path) -> dict[str, list[object]]:
    with path.open("r", encoding="utf-8") as awareness_file:
        value = json.load(awareness_file)
    nodes = value.get("nodes") if isinstance(value, dict) else None
    services = value.get("services") if isinstance(value, dict) else None
    if not isinstance(nodes, list) or not isinstance(services, list):
        raise VerificationError(f"invalid awareness state in {path}")
    return {"nodes": nodes, "services": services}


def _read_trust(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as trust_file:
        value = json.load(trust_file)
    entries = value.get("nodes") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise VerificationError(f"invalid trust state in {path}")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerificationError(f"invalid trust entry in {path}")
        node_id = entry.get("node_id")
        state = entry.get("state")
        if not isinstance(node_id, str) or not isinstance(state, str):
            raise VerificationError(f"invalid trust entry in {path}")
        result[node_id] = state
    return result


def _find_service(
    services: list[object],
    provider: str,
    service_name: str,
) -> dict[str, object] | None:
    for service in services:
        if (
            isinstance(service, dict)
            and service.get("provider") == provider
            and service.get("service_name") == service_name
        ):
            return service
    return None


def _require_log(contents: str, expected: str, path: Path) -> None:
    if expected not in contents:
        raise VerificationError(f"missing {expected!r} in {path}")


def _require_regex(contents: str, pattern: str, source: str) -> None:
    if re.search(pattern, contents) is None:
        raise VerificationError(f"missing log pattern {pattern!r} in {source}")


def _require_log_order(
    contents: str,
    earlier: str,
    later: str,
    path: Path,
) -> None:
    earlier_index = contents.find(earlier)
    later_index = contents.find(later, earlier_index + len(earlier))
    if earlier_index < 0 or later_index < 0:
        raise VerificationError(
            f"missing ordered expiry/re-discovery evidence in {path}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
