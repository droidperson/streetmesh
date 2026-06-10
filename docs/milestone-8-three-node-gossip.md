# Milestone 8: Three-Node Gossip Manual Test

This acceptance test verifies that Node B forwards Node A's accepted NODE
Knowledge Object with a reduced TTL, allowing Node C to learn about Node A
without receiving Node A's original broadcast directly.

Services, trust, and quarantine are outside this test.

## Topology

Use two UDP broadcast segments:

```text
Segment 1: Node A ---- Node B
                         |
Segment 2:               +---- Node C
```

Node B needs interfaces on both segments. Node A must not have a route or
interface that receives Segment 2 broadcasts, and Node C must not receive
Segment 1 broadcasts. This isolation is what proves Node C's awareness arrived
through gossip.

In the examples below, replace:

- `<SEGMENT_1_BROADCAST>` with the broadcast address shared by A and B.
- `<SEGMENT_2_BROADCAST>` with the broadcast address shared by B and C.
- `<NODE_A_BIND>`, `<NODE_B_BIND>`, and `<NODE_C_BIND>` with suitable local
  addresses, or use `0.0.0.0` where appropriate.

All nodes use UDP port `40404` and fresh, separate data directories.

## Configuration

Create `m8-node-a.json`:

```json
{
  "node": {
    "node_name": "node-a@local@mesh",
    "data_dir": "m8-data/node-a",
    "announce_interval": 30,
    "udp_port": 40404,
    "bind_host": "<NODE_A_BIND>",
    "broadcast_host": "<SEGMENT_1_BROADCAST>"
  }
}
```

Create `m8-node-b.json`. Its outgoing broadcasts target Segment 2:

```json
{
  "node": {
    "node_name": "node-b@local@mesh",
    "data_dir": "m8-data/node-b",
    "announce_interval": 30,
    "udp_port": 40404,
    "bind_host": "<NODE_B_BIND>",
    "broadcast_host": "<SEGMENT_2_BROADCAST>"
  }
}
```

Create `m8-node-c.json`:

```json
{
  "node": {
    "node_name": "node-c@local@mesh",
    "data_dir": "m8-data/node-c",
    "announce_interval": 30,
    "udp_port": 40404,
    "bind_host": "<NODE_C_BIND>",
    "broadcast_host": "<SEGMENT_2_BROADCAST>"
  }
}
```

## Procedure

1. Start Node C on Segment 2 and capture its log:

   ```powershell
   python -m streetmesh --config .\m8-node-c.json 2>&1 | Tee-Object .\m8-node-c.log
   ```

2. Start Node B, connected to both segments:

   ```powershell
   python -m streetmesh --config .\m8-node-b.json 2>&1 | Tee-Object .\m8-node-b.log
   ```

3. Start Node A on Segment 1:

   ```powershell
   python -m streetmesh --config .\m8-node-a.json 2>&1 | Tee-Object .\m8-node-a.log
   ```

4. In Node A's log, record its announcement `ko_id` and confirm its initial
   TTL is 3:

   ```text
   INFO streetmesh.daemon: NODE announcement broadcast: node_name=node-a@local@mesh ko_id=<KO_ID> seq=1 ttl=3 expires=<EPOCH_SECONDS>
   ```

5. Confirm Node B accepts Node A and forwards the same Knowledge Object with a
   reduced TTL:

   ```text
   INFO streetmesh.directory: Node discovered: node_name=node-a@local@mesh node_id=<NODE_A_ID> seq=1 expires=<EPOCH_SECONDS>
   INFO streetmesh.gossip: Gossip forwarded: ko_id=<KO_ID> origin=<NODE_A_ID> ttl=3 forwarded_ttl=2
   ```

6. Confirm Node C discovers Node A. The node ID and Knowledge Object ID must
   correspond to Node A's original announcement:

   ```text
   INFO streetmesh.directory: Node discovered: node_name=node-a@local@mesh node_id=<NODE_A_ID> seq=1 expires=<EPOCH_SECONDS>
   INFO streetmesh.gossip: Gossip forwarded: ko_id=<KO_ID> origin=<NODE_A_ID> ttl=2 forwarded_ttl=1
   ```

7. Inspect `m8-data/node-c/awareness.json` and confirm it contains an entry for
   `<NODE_A_ID>` with `node_name` equal to `node-a@local@mesh`.

8. Leave the nodes running for several announcement intervals. Each `ko_id`
   should be forwarded at most once by each node. Looping copies should produce
   duplicate-suppression logs rather than additional forwarding:

   ```text
   INFO streetmesh.directory: Duplicate Knowledge Object suppressed: ko_id=<KO_ID>
   ```

The test passes when Node B logs forwarding of Node A's object with TTL reduced
from 3 to 2 and isolated Node C persists awareness of Node A.
