# Milestone 7: Two-Node Discovery Manual Test

This acceptance test verifies direct UDP discovery, refresh, and expiry between
two StreetMesh v0.1 nodes. It does not test or require gossip, services,
trust, or quarantine.

## Preconditions

- Run both nodes on hosts in the same UDP broadcast domain.
- Allow inbound and outbound UDP port `40404` through the local firewall.
- Use Python 3.10 or newer and only the repository's standard-library code.
- Use fresh, separate data directories so old identities or awareness entries
  cannot affect the result.

The examples below use PowerShell from the repository root. On systems that do
not deliver a broadcast to two sockets sharing one port, run Node A and Node B
on separate hosts and use the same commands and port.

## Procedure

1. In terminal A, start Node A:

   ```powershell
   python -m streetmesh --data-dir .\m7-data\node-a --node-name node-a@local@mesh --announce-interval 2 --udp-port 40404 2>&1 | Tee-Object .\m7-node-a.log
   ```

2. In terminal B, start Node B with a different data directory:

   ```powershell
   python -m streetmesh --data-dir .\m7-data\node-b --node-name node-b@local@mesh --announce-interval 2 --udp-port 40404 2>&1 | Tee-Object .\m7-node-b.log
   ```

3. Confirm terminal A reports discovery of Node B:

   ```text
   INFO streetmesh.directory: Node discovered: node_name=node-b@local@mesh node_id=<NODE_B_ID> seq=1 expires=<EPOCH_SECONDS>
   ```

4. Confirm terminal B reports discovery of Node A. Node B may first see a
   sequence number greater than 1 because Node A started earlier:

   ```text
   INFO streetmesh.directory: Node discovered: node_name=node-a@local@mesh node_id=<NODE_A_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
   ```

5. Leave both nodes running for at least one more announcement interval and
   confirm refresh logs appear on both nodes:

   ```text
   INFO streetmesh.directory: Node refreshed: node_name=node-b@local@mesh node_id=<NODE_B_ID> seq=2 expires=<EPOCH_SECONDS>
   INFO streetmesh.directory: Node refreshed: node_name=node-a@local@mesh node_id=<NODE_A_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
   ```

6. Stop Node A with `Ctrl+C`. Its terminal should end cleanly:

   ```text
   INFO streetmesh.daemon: StreetMesh shutdown requested; stopping cleanly.
   ```

7. Keep Node B running. A NODE announcement expires 120 seconds after it was
   created. Within roughly 122 seconds of Node A's final announcement, confirm
   Node B logs:

   ```text
   INFO streetmesh.directory: NODE_EXPIRED node_name=node-a@local@mesh node_id=<NODE_A_ID> expires=<EPOCH_SECONDS>
   ```

8. Inspect `m7-data/node-b/awareness.json` and confirm it contains Node B but
   no longer contains `<NODE_A_ID>`. Stop Node B with `Ctrl+C`.

The test passes only when discovery is observed in both directions and Node B
logs `NODE_EXPIRED` for Node A after Node A stops.

## Verification Helper

After completing the procedure, run the standard-library-only artifact checker:

```powershell
python tools\two_node_discovery.py
```

The defaults match the paths in this procedure. The checker loads both
identities, confirms bidirectional `Node discovered` lines, confirms Node B's
`NODE_EXPIRED` line names Node A's identity, and confirms Node A is absent from
Node B's final Awareness Store. Alternate artifact paths can be supplied with
the four path options shown by `--help`.

The live network procedure remains manual because UDP broadcast and shared-port
behavior depend on the host network and firewall. Unit tests for the artifact
checker are included in `python -m unittest discover`.
