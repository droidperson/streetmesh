"""Command-line interface for the StreetMesh daemon."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import ConfigError, load_config
from .daemon import StreetMeshDaemon
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
    trust_actions = parser.add_mutually_exclusive_group()
    trust_actions.add_argument(
        "--list-trust",
        action="store_true",
        help="list local trust entries and exit",
    )
    trust_actions.add_argument(
        "--trust-node",
        metavar="NODE_ID",
        help="mark a node ID trusted and exit",
    )
    trust_actions.add_argument(
        "--block-node",
        metavar="NODE_ID",
        help="mark a node ID blocked and exit",
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

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

    if args.list_trust or args.trust_node or args.block_node:
        try:
            trust_store = TrustStore.load(config.node.data_dir / "trust.json")
            if args.trust_node:
                trust_store.add_trusted(args.trust_node)
                print(f"Trusted node: {args.trust_node}")
            elif args.block_node:
                trust_store.add_blocked(args.block_node)
                print(f"Blocked node: {args.block_node}")
            else:
                print(
                    json.dumps(
                        {
                            "nodes": [
                                {
                                    "node_id": entry.node_id,
                                    "state": entry.state,
                                }
                                for entry in trust_store.list_entries()
                            ]
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
        except TrustStoreError as exc:
            parser.error(str(exc))
        return 0

    daemon = StreetMeshDaemon(config=config)
    return daemon.run()
