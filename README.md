# StreetMesh

A distributed awareness layer for autonomous edge systems.

## Status

StreetMesh v0.1 is in Milestone 1. This repository currently contains the
project skeleton, JSON configuration loading, persistent local identity, example
configuration files, and a standard-library-only command-line entry point.

Networking is not implemented yet.

## Requirements

- Python 3.10 or newer
- No third-party Python dependencies

## Quick Start

Show the daemon help:

```sh
python streetmeshd.py --help
```

Validate an example configuration file:

```sh
python streetmeshd.py --config examples/config.example.json --check-config
```

Run with defaults:

```sh
python streetmeshd.py
```

StreetMesh will create or load `data/identity.json`, broadcast NODE
announcements over UDP, and continue announcing every 30 seconds until stopped
with Ctrl+C.

## Repository Layout

```text
streetmeshd.py                 Daemon entry point
streetmesh/                    StreetMesh package
  cli.py                       Command-line interface
  config.py                    Configuration loading and validation
  daemon.py                    Daemon lifecycle and NODE announcements
  identity.py                  Node identity loading and creation
  protocol.py                  Protocol constants placeholder
  routing.py                   Routing table placeholder
  storage.py                   Local state placeholder
  transport.py                 Null transport placeholder
  transport_udp.py             UDP byte transport
examples/
  config.example.json          Example daemon configuration
  node.example.json            Example node metadata
tests/                         unittest suite
```

## Development Notes

Keep Milestone 1 dependency-free. Use only the Python standard library until a
later milestone explicitly introduces external dependencies.
