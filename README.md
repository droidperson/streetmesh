# StreetMesh

Distributed awareness mesh for autonomous edge systems.

StreetMesh is a mycelial-inspired distributed awareness network that enables autonomous edge nodes to discover each other, exchange knowledge, advertise services, and establish trust without central coordination.

## Current Status

**Version:** v0.1.0

Milestone 18 Complete

### Implemented Features

* Node identity management
* Knowledge Object protocol
* UDP node discovery
* Awareness directory
* Gossip propagation
* Service advertisement
* Trust and quarantine framework
* Command-line inspection tools
* Raspberry Pi deployment support
* Formal three-node cross-platform mesh validation
* HMAC-SHA256 signed Knowledge Objects
* Signature-aware trust policy and inspection
* Read-only node-name and service-provider resolution
* Trust promotion and stable node-name binding
* Public-key-ready identity metadata and signer/verifier abstraction

### Validated Platforms

* Windows 11
* Raspberry Pi OS
* Cross-platform mesh operation validated

### Validation Completed

* Cross-platform node discovery
* Node expiry and re-discovery
* Gossip forwarding
* Service propagation
* Trust management
* Persistent identities
* Persistent per-node signing secrets
* Signed local NODE and SERVICE claims
* Persisted signature status for node and service awareness
* Ranked resolution with ambiguity, expiry, and limited-trust reporting
* Trusted-name conflict detection and continuity protection
* Safe public identity awareness without secret or private-key disclosure

## Vision

StreetMesh aims to provide distributed awareness for autonomous edge systems operating in dynamic, unreliable, and infrastructure-constrained environments.

Examples include:

* Raspberry Pi clusters
* Mobile devices
* Vehicles
* Motorcycles
* Drones
* Sensors
* Edge computing platforms

StreetMesh is inspired by biological mycelial networks, where awareness propagates organically through a mesh of interconnected nodes.




StreetMesh v0.1 has completed Milestone 18. Nodes broadcast signed NODE and SERVICE
Knowledge Objects over UDP, maintain a persistent Awareness Store, suppress
duplicate objects, refresh and expire known nodes and services, and gossip
policy-approved remote objects with a decreasing hop TTL. Local review-mode
trust keeps unknown awareness visible without treating it as automatically
trusted, while signature-aware policy distinguishes locally verified,
remotely unverified, unsigned, invalid, and unsupported claims.
Persisted awareness can now resolve node names and rank service providers while
reporting limited trust, ambiguity, rejection, expiry, or missing results.
Users can now trust or block a resolved node name, binding it to a stable node
ID so conflicting claims remain visible without replacing user intent.
Identity version 2 adds safe public-key metadata and pluggable signing and
verification interfaces while HMAC-SHA256 remains the only active algorithm.
No public-key signature is generated or accepted as verified yet.

Persisted state can be inspected without starting the daemon:

```sh
python streetmeshd.py --status
python streetmeshd.py --list-nodes
python streetmeshd.py --list-services
python streetmeshd.py --list-trust
python streetmeshd.py --resolve-node pi01@local@mesh
python streetmeshd.py --resolve-service temperature
python streetmeshd.py --trust-node-name pi01@local@mesh
python streetmeshd.py --block-node-name pi01@local@mesh
python streetmeshd.py --show-trust pi01@local@mesh
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
  signing.py                   Signer and verifier abstractions
  inspection.py                Persisted-state CLI formatting
  protocol.py                  Knowledge Object creation and validation
  policy.py                    Review-mode claim decisions
  quarantine.py                Quarantined claim persistence
  resolver.py                  Read-only name and service resolution
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
  three_node_mesh_validation.py
                               Milestone 13 mesh artifact verifier
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
  milestone-12-raspberry-pi-deployment.md
                               Raspberry Pi OS deployment guide
  milestone-13-multi-node-mesh-validation.md
                               Cross-platform three-node validation procedure
  milestone-14-signed-knowledge-objects.md
                               HMAC signing design and limitations
  milestone-15-signature-aware-trust-policy.md
                               Signature status, policy, and inspection
  milestone-16-name-service-resolution.md
                               Node and service resolution and ranking
  milestone-17-trust-promotion-name-binding.md
                               Trust-by-name workflow and conflict handling
  milestone-18-public-key-identity-model.md
                               Public-key-ready identity and signing model
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

## Milestone 12 Raspberry Pi Deployment

See the [Raspberry Pi deployment guide](docs/milestone-12-raspberry-pi-deployment.md)
for Raspberry Pi OS setup, three-node LAN testing, inspection commands,
systemd configuration, and network troubleshooting.

## Milestone 13 Multi-Node Validation

Follow the [multi-node mesh validation procedure](docs/milestone-13-multi-node-mesh-validation.md)
for the formal Windows, Raspberry Pi, and third-node acceptance test. Saved
artifacts can be checked with:

```sh
python tools/three_node_mesh_validation.py
```

## Milestone 14 Signed Knowledge Objects

See [Signed Knowledge Objects](docs/milestone-14-signed-knowledge-objects.md)
for the canonical HMAC-SHA256 design, automatic identity migration, verification
scope, limitations, and planned evolution toward public-key node identities.

## Milestone 15 Signature-Aware Trust Policy

See the [signature-aware trust policy guide](docs/milestone-15-signature-aware-trust-policy.md)
for signature status meanings, interim HMAC verification behavior, policy and
inspection integration, limitations, and the public-key evolution path.

## Milestone 16 Name And Service Resolution

See the [name and service resolution guide](docs/milestone-16-name-service-resolution.md)
for read-only node lookup, provider ranking, ambiguity and expiry handling,
CLI examples, and the future path toward service-access preflight.

## Milestone 17 Trust Promotion And Name Binding

See the [trust promotion and name binding guide](docs/milestone-17-trust-promotion-name-binding.md)
for trusting and blocking resolved node names, enriched trust records, binding
conflict behavior, and the relationship between user trust and signature state.

## Milestone 18 Public-Key Identity Model

See the [public-key identity model](docs/milestone-18-public-key-identity-model.md)
for identity version 2, signer and verifier extension points, safe NODE identity
metadata, HMAC compatibility, and the planned migration to real public-key
signatures.

## Development Notes

StreetMesh v0.1 remains dependency-free. Milestone 18 prepares identities and
signature handling for a reviewed public-key backend without treating remote
HMACs as public proof or implementing homemade cryptography. Public-key
cryptography, certificates, invite tokens, service adapters, service
invocation, and a full administration UI are not implemented.
