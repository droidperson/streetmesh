# StreetMesh

A distributed awareness layer for autonomous edge systems.

## Status

StreetMesh v0.1 has completed Milestone 7. Nodes broadcast NODE Knowledge
Objects over UDP, maintain a persistent Awareness Store, suppress duplicate
objects, refresh known nodes, and expire stale remote nodes.

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
with Ctrl+C. Received NODE announcements are tracked in the Awareness Store and
persisted to `data/awareness.json`. Duplicate Knowledge Objects are suppressed
for 300 seconds, and stale remote node awareness is expired when its announced
expiry time passes.

## Repository Layout

```text
streetmeshd.py                 Daemon entry point
streetmesh/                    StreetMesh package
  cli.py                       Command-line interface
  config.py                    Configuration loading and validation
  daemon.py                    Daemon lifecycle and NODE announcements
  directory.py                 Awareness Store for known nodes
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
tools/
  two_node_discovery.py        Milestone 7 acceptance artifact verifier
docs/
  milestone-7-two-node-discovery.md
                               Manual two-node acceptance procedure
```

## Milestone 7 Acceptance Test

Follow the documented
[two-node discovery manual test](docs/milestone-7-two-node-discovery.md), then
verify its saved logs and state with the standard-library helper:

```sh
python tools/two_node_discovery.py
```

The live network steps remain manual because UDP broadcast behavior depends on
the host network and firewall. The helper's artifact checks are unit tested.

## Development Notes

StreetMesh v0.1 remains dependency-free. Gossip, services, trust, and
quarantine are not implemented in Milestone 7.
