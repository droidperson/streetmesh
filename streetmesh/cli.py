"""Command-line interface for the StreetMesh daemon."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import ConfigError, load_config
from .daemon import StreetMeshDaemon
from .identity import IdentityError
from .inspection import (
    format_nodes,
    format_node_resolution,
    format_services,
    format_service_resolution,
    format_status,
    format_trust,
    format_trust_change,
    format_trust_detail,
    load_inspection_state,
)
from .resolver import resolve_node, resolve_service
from .trust import TrustStore, TrustStoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="streetmeshd.py",
        description="StreetMesh daemon for autonomous edge awareness.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="path to JSON daemon configuration file",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="directory for daemon state and identity",
    )
    parser.add_argument(
        "--node-name",
        default=None,
        help="local node name",
    )
    parser.add_argument(
        "--announce-interval",
        type=int,
        default=None,
        help="seconds between NODE announcements",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=None,
        help="UDP port to bind and broadcast announcements on",
    )
    parser.add_argument(
        "--service-announce-interval",
        type=int,
        default=None,
        help="seconds between SERVICE announcements",
    )
    parser.add_argument(
        "--services-file",
        type=Path,
        default=None,
        help="path to JSON local service definitions",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="load and validate configuration, then exit",
    )
    state_actions = parser.add_mutually_exclusive_group()
    state_actions.add_argument(
        "--status",
        action="store_true",
        help="show persisted local StreetMesh status and exit",
    )
    state_actions.add_argument(
        "--list-nodes",
        action="store_true",
        help="list persisted node awareness and exit",
    )
    state_actions.add_argument(
        "--list-services",
        action="store_true",
        help="list persisted service awareness and exit",
    )
    state_actions.add_argument(
        "--list-trust",
        action="store_true",
        help="list local trust entries and exit",
    )
    state_actions.add_argument(
        "--resolve-node",
        metavar="NODE_NAME",
        help="resolve a persisted node name and exit",
    )
    state_actions.add_argument(
        "--resolve-service",
        metavar="SERVICE_NAME",
        help="resolve and rank persisted service providers and exit",
    )
    state_actions.add_argument(
        "--trust-node",
        metavar="NODE_ID",
        help="mark a node ID trusted and exit",
    )
    state_actions.add_argument(
        "--block-node",
        metavar="NODE_ID",
        help="mark a node ID blocked and exit",
    )
    state_actions.add_argument(
        "--trust-node-name",
        metavar="NODE_NAME",
        help="resolve, bind, and trust a node name, then exit",
    )
    state_actions.add_argument(
        "--block-node-name",
        metavar="NODE_NAME",
        help="resolve, bind, and block a node name, then exit",
    )
    state_actions.add_argument(
        "--show-trust",
        metavar="NODE_NAME_OR_ID",
        help="show one persisted trust binding and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"StreetMesh {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(
            args.config,
            data_dir=args.data_dir,
            node_name=args.node_name,
            announce_interval=args.announce_interval,
            service_announce_interval=args.service_announce_interval,
            services_file=args.services_file,
            udp_port=args.udp_port,
        )
    except ConfigError as exc:
        parser.error(str(exc))

    if args.check_config:
        source = config.path if config.path is not None else "defaults"
        print(f"Configuration OK: {source}")
        return 0

    if (
        args.status
        or args.list_nodes
        or args.list_services
        or args.list_trust
        or args.resolve_node
        or args.resolve_service
        or args.trust_node
        or args.block_node
        or args.trust_node_name
        or args.block_node_name
        or args.show_trust
    ):
        try:
            if args.trust_node:
                trust_store = TrustStore.load(config.node.data_dir / "trust.json")
                trust_store.add_trusted(args.trust_node)
                print(f"Trusted node: {args.trust_node}")
            elif args.block_node:
                trust_store = TrustStore.load(config.node.data_dir / "trust.json")
                trust_store.add_blocked(args.block_node)
                print(f"Blocked node: {args.block_node}")
            elif args.trust_node_name or args.block_node_name:
                node_name = args.trust_node_name or args.block_node_name
                state = load_inspection_state(config.node.data_dir)
                result = resolve_node(state.awareness, node_name)
                if result.resolution_status != "resolved" or result.chosen is None:
                    action = "Trust" if args.trust_node_name else "Block"
                    print(
                        f"{action} by name failed: node_name={node_name} "
                        f"resolution_status={result.resolution_status} "
                        f"reason={result.reason}"
                    )
                    return 1
                trust_store = TrustStore.load(
                    config.node.data_dir / "trust.json"
                )
                previous_state = trust_store.get_state(result.node_id)
                new_state = "trusted" if args.trust_node_name else "blocked"
                entry = trust_store.bind_name(
                    result.node_id,
                    node_name,
                    new_state,
                    fingerprint=result.fingerprint,
                )
                print(
                    format_trust_change(
                        entry,
                        previous_state=previous_state,
                        signature_status=result.signature_status
                        or "signature_not_checked",
                    )
                )
            elif args.show_trust:
                trust_store = TrustStore.load(
                    config.node.data_dir / "trust.json",
                    create_if_missing=False,
                )
                entry = trust_store.get_entry(args.show_trust)
                if entry is None:
                    entry = trust_store.get_by_name(args.show_trust)
                if entry is None:
                    print(f"Trust entry not found: {args.show_trust}")
                    return 1
                print(format_trust_detail(entry))
            elif args.list_trust:
                trust_store = TrustStore.load(
                    config.node.data_dir / "trust.json",
                    create_if_missing=False,
                )
                print(format_trust(trust_store.list_entries()))
            else:
                state = load_inspection_state(config.node.data_dir)
                if args.status:
                    print(format_status(state, config))
                elif args.list_nodes:
                    print(format_nodes(state.awareness.list_nodes()))
                elif args.list_services:
                    print(format_services(state.awareness.list_services()))
                elif args.resolve_node:
                    print(
                        format_node_resolution(
                            resolve_node(state.awareness, args.resolve_node)
                        )
                    )
                else:
                    print(
                        format_service_resolution(
                            resolve_service(
                                state.awareness,
                                args.resolve_service,
                            )
                        )
                    )
        except (IdentityError, TrustStoreError) as exc:
            parser.error(str(exc))
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    daemon = StreetMeshDaemon(config=config)
    return daemon.run()
