# Milestone 11: CLI Inspection Tools

StreetMesh can inspect persisted local state without starting UDP networking or
the daemon loop. Run commands from the repository root and select the same data
directory used by the daemon.

## Status

~~~powershell
python streetmeshd.py --data-dir .\data --status
~~~

The output includes the local node ID and name, configured UDP port, policy
mode, and counts for persisted nodes, services, and trust entries.

## Nodes

~~~powershell
python streetmeshd.py --data-dir .\data --list-nodes
~~~

Each row shows node name, node ID, trust state, signature status, first and last
observation times, expiry, and whether the persisted claim is current or
expired.

## Services

~~~powershell
python streetmeshd.py --data-dir .\data --list-services
~~~

Each row shows service name, provider ID, trust state, limited-acceptance marker
when applicable, signature status, endpoint, protocol, expiry, and current or
expired status.

## Trust

~~~powershell
python streetmeshd.py --data-dir .\data --list-trust
~~~

Trust entries are displayed with node name when bound, node ID, trust state,
fingerprint when available, binding status, and trust timestamps. Existing raw
node-ID administration commands remain available:

~~~powershell
python streetmeshd.py --data-dir .\data --trust-node <NODE_ID>
python streetmeshd.py --data-dir .\data --block-node <NODE_ID>
~~~

Milestone 17 also supports resolved-name administration and binding detail:

~~~powershell
python streetmeshd.py --data-dir .\data --trust-node-name <NODE_NAME>
python streetmeshd.py --data-dir .\data --block-node-name <NODE_NAME>
python streetmeshd.py --data-dir .\data --show-trust <NODE_NAME_OR_ID>
~~~

Inspection reads identity.json, awareness.json, and trust.json from the selected
data directory. Awareness already persists both nodes and services, so these
commands continue to work after a clean daemon shutdown.
