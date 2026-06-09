# StreetMesh

A distributed awareness layer for autonomous edge systems.

## Status

StreetMesh v0.1 is in Milestone 0. This repository currently contains the
project skeleton, placeholder modules, example configuration files, and a
standard-library-only command-line entry point.

Networking is not implemented yet.

## Requirements

- Python 3.10 or newer
- No third-party Python dependencies

## Quick Start

Show the daemon help:

```sh
python3 streetmeshd.py --help
```

Validate an example configuration file:

```sh
python3 streetmeshd.py --config examples/streetmeshd.example.ini --check-config
```

## Repository Layout

```text
streetmeshd.py                 Daemon entry point
streetmesh/                    StreetMesh package
  cli.py                       Command-line interface
  config.py                    Configuration loading and validation
  daemon.py                    Daemon lifecycle placeholder
  identity.py                  Node identity placeholder
  protocol.py                  Protocol constants placeholder
  routing.py                   Routing table placeholder
  storage.py                   Local state placeholder
  transport.py                 Transport placeholder, no networking yet
examples/
  streetmeshd.example.ini      Example daemon configuration
  node.example.json            Example node metadata
```

## Development Notes

Keep Milestone 0 dependency-free. Use only the Python standard library until a
later milestone explicitly introduces external dependencies.
