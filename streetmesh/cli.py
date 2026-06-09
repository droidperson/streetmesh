"""Command-line interface for the StreetMesh daemon."""

from __future__ import annotations

import argparse
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
        default=Path("streetmeshd.ini"),
        help="path to daemon configuration file (default: %(default)s)",
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

    if args.check_config:
        try:
            config = load_config(args.config)
        except ConfigError as exc:
            parser.error(str(exc))
        print(f"Configuration OK: {config.path}")
        return 0

    daemon = StreetMeshDaemon(config_path=args.config)
    return daemon.run()
