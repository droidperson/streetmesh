# StreetMesh

A distributed awareness layer for autonomous edge systems.

## Status

StreetMesh v0.1 has completed Milestone 11. Nodes broadcast NODE and SERVICE
Knowledge Objects over UDP, maintain a persistent Awareness Store, suppress
duplicate objects, refresh and expire known nodes and services, and gossip
policy-approved remote objects with a decreasing hop TTL. Local review-mode
trust keeps unknown awareness visible without treating it as automatically
trusted.

Persisted state can be inspected without starting the daemon:

```sh
python streetmeshd.py --status
python streetmeshd.py --list-nodes
python streetmeshd.py --list-services
python streetmeshd.py --list-trust
```

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
with Ctrl+C. When `services_file` is configured, local services are announced
at `service_announce_interval`, which defaults to 60 seconds. Received NODE and
SERVICE announcements are persisted to `data/awareness.json`. Duplicate
Knowledge Objects are suppressed for 300 seconds, and stale remote awareness is
expired when its announced expiry time passes.

## Repository Layout

```text
streetmeshd.py                 Daemon entry point
streetmesh/                    StreetMesh package
  cli.py                       Command-line interface
  config.py                    Configuration loading and validation
  daemon.py                    Daemon lifecycle and announcements
  directory.py                 Awareness Store for nodes and services
  gossip.py                    Gossip forwarding policy
  identity.py                  Node identity loading and creation
  inspection.py                Persisted-state CLI formatting
  protocol.py                  Knowledge Object creation and validation
  policy.py                    Review-mode claim decisions
  quarantine.py                Quarantined claim persistence
  routing.py                   Routing table placeholder
  services.py                  Local service definitions and announcements
  storage.py                   Local state placeholder
  transport.py                 Null transport placeholder
  transport_udp.py             UDP byte transport
  trust.py                     Persistent local node trust states
examples/
  config.example.json          Example daemon configuration
  node.example.json            Example node metadata
  services.example.json        Example local service definitions
tests/                         unittest suite
tools/
  two_node_discovery.py        Milestone 7 acceptance artifact verifier
docs/
  milestone-7-two-node-discovery.md
                               Manual two-node acceptance procedure
  milestone-8-three-node-gossip.md
                               Manual three-node gossip procedure
  milestone-9-service-advertisement.md
                               Manual service advertisement procedure
  milestone-10-trust-and-quarantine.md
                               Manual trust and quarantine procedure
  milestone-11-cli-inspection.md
                               CLI inspection reference
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

## Milestone 8 Acceptance Test

Follow the documented
[three-node gossip manual test](docs/milestone-8-three-node-gossip.md) to verify
that an isolated Node C learns about Node A through Node B with TTL reduction.

## Milestone 9 Acceptance Test

Follow the documented
[service advertisement manual test](docs/milestone-9-service-advertisement.md)
to verify SERVICE announcement, discovery, refresh, persistence, gossip, and
expiry.

## Milestone 10 Acceptance Test

Follow the documented
[trust and quarantine manual test](docs/milestone-10-trust-and-quarantine.md)
to verify unknown awareness, limited services, trusted providers, blocked
origins, and quarantined sensitive claims.

## Milestone 11 Inspection

See the [CLI inspection reference](docs/milestone-11-cli-inspection.md) for
status, node, service, and trust listing commands.

## Development Notes

StreetMesh v0.1 remains dependency-free. Cryptographic signatures, invite
tokens, service invocation, and a full administration UI are not implemented
in Milestone 11.
