# Milestone 9: Service Advertisement Manual Test

This acceptance test verifies local SERVICE announcements, remote service
discovery and refresh, gossip compatibility, persistence, and expiry. It does
not invoke services or apply trust or quarantine decisions.

## Setup

Use two nodes on the same UDP broadcast domain with separate data directories.
Create `m9-services-a.json`:

```json
{
  "services": [
    {
      "service_name": "temperature",
      "capabilities": ["current_temperature", "humidity"],
      "endpoint": "/temperature",
      "protocol": "http",
      "service_version": "0.1"
    }
  ]
}
```

Create `m9-node-a.json`:

```json
{
  "node": {
    "node_name": "node-a@local@mesh",
    "data_dir": "m9-data/node-a",
    "announce_interval": 30,
    "service_announce_interval": 60,
    "services_file": "m9-services-a.json",
    "udp_port": 40404,
    "bind_host": "0.0.0.0",
    "broadcast_host": "255.255.255.255"
  }
}
```

Create `m9-node-b.json` with a separate data directory and no `services_file`:

```json
{
  "node": {
    "node_name": "node-b@local@mesh",
    "data_dir": "m9-data/node-b",
    "announce_interval": 30,
    "service_announce_interval": 60,
    "udp_port": 40404,
    "bind_host": "0.0.0.0",
    "broadcast_host": "255.255.255.255"
  }
}
```

## Procedure

1. Start Node B and capture its log:

   ```powershell
   python -m streetmesh --config .\m9-node-b.json 2>&1 | Tee-Object .\m9-node-b.log
   ```

2. Start Node A and capture its log:

   ```powershell
   python -m streetmesh --config .\m9-node-a.json 2>&1 | Tee-Object .\m9-node-a.log
   ```

3. Confirm Node A broadcasts the local service:

   ```text
   INFO streetmesh.daemon: SERVICE announced: service_name=temperature provider=<NODE_A_ID> ko_id=<KO_ID> seq=1 ttl=3 expires=<EPOCH_SECONDS>
   ```

4. Confirm Node B stores the service and forwards it through the existing
   gossip path:

   ```text
   INFO streetmesh.directory: SERVICE discovered: service_name=temperature provider=<NODE_A_ID> seq=1 expires=<EPOCH_SECONDS>
   INFO streetmesh.gossip: Gossip forwarded: ko_id=<KO_ID> origin=<NODE_A_ID> ttl=3 forwarded_ttl=2
   ```

5. After the next 60-second service interval, confirm refresh logs appear:

   ```text
   INFO streetmesh.daemon: SERVICE announced: service_name=temperature provider=<NODE_A_ID> ko_id=<NEW_KO_ID> seq=2 ttl=3 expires=<EPOCH_SECONDS>
   INFO streetmesh.directory: SERVICE refreshed: service_name=temperature provider=<NODE_A_ID> seq=2 expires=<EPOCH_SECONDS>
   ```

6. Inspect `m9-data/node-b/awareness.json`. Its `services` array should contain
   the advertised metadata, provider ID, and Node A's name when Node A awareness
   is available:

   ```json
   {
     "service_name": "temperature",
     "provider": "<NODE_A_ID>",
     "provider_name": "node-a@local@mesh",
     "capabilities": ["current_temperature", "humidity"],
     "endpoint": "/temperature",
     "protocol": "http",
     "service_version": "0.1"
   }
   ```

7. Stop Node A. SERVICE claims expire 300 seconds after creation. Within about
   301 seconds of Node A's last SERVICE announcement, confirm Node B logs:

   ```text
   INFO streetmesh.directory: SERVICE expired: service_name=temperature provider=<NODE_A_ID> expires=<EPOCH_SECONDS>
   ```

8. Confirm the `temperature` entry has been removed from Node B's persisted
   `services` array, then stop Node B.

The test passes when Node A announces the service, Node B discovers and
refreshes it, the metadata is persisted, and the stale service expires.
