"""Command-line interface for the StreetMesh daemon."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import ConfigError, load_config
from .daemon import StreetMeshDaemon


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
        "--check-config",
        action="store_true",
        help="load and validate configuration, then exit",
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
            udp_port=args.udp_port,
        )
    except ConfigError as exc:
        parser.error(str(exc))

    if args.check_config:
        source = config.path if config.path is not None else "defaults"
        print(f"Configuration OK: {source}")
        return 0

    daemon = StreetMeshDaemon(config=config)
    return daemon.run()
