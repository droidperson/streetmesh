# Milestone 13: Multi-Node Mesh Validation

This procedure validates StreetMesh v0.1 with three cross-platform nodes:

- Windows laptop: `laptop@local@mesh`
- Raspberry Pi: `pi01@local@mesh`
- Second laptop or other available node: `laptop-test@local@mesh`

The test covers NODE discovery, SERVICE advertisement, gossip forwarding,
trust, expiry, restart, re-discovery, duplicate suppression, and offline CLI
inspection. It does not test cryptographic signatures or service execution.

## Preconditions

- All three devices run the same StreetMesh revision.
- `python -m unittest discover` passes on Windows.
- `python3 -m unittest discover` passes on Raspberry Pi OS or Linux.
- All devices are on the same IPv4 LAN and UDP port `40404` is allowed.
- Wi-Fi client isolation is disabled.
- Each node starts with a fresh, unique data directory.
- Logs are appended across restarts so expiry and re-discovery remain in one
  file per node.

A separate physical device for `laptop-test@local@mesh` is preferred. Multiple
processes bound to the same UDP port on one host may receive broadcasts
differently depending on the operating system.

## Prepare the Service

The Raspberry Pi advertises the repository's example `temperature` service:

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

This definition is already available as `examples/services.example.json`.

## Start the Three Nodes

### Windows Laptop

Run from PowerShell in the repository root:

```powershell
python -m streetmesh `
  --data-dir .\m13-data\laptop `
  --node-name laptop@local@mesh `
  --udp-port 40404 2>&1 |
  Tee-Object -FilePath .\m13-laptop.log -Append
```

### Raspberry Pi

Run from the repository root:

```sh
python3 -m streetmesh \
  --data-dir ./m13-data/pi01 \
  --node-name pi01@local@mesh \
  --services-file ./examples/services.example.json \
  --udp-port 40404 2>&1 | tee -a ./m13-pi01.log
```

### Second Laptop or Available Node

On Windows PowerShell:

```powershell
python -m streetmesh `
  --data-dir .\m13-data\laptop-test `
  --node-name laptop-test@local@mesh `
  --udp-port 40404 2>&1 |
  Tee-Object -FilePath .\m13-laptop-test.log -Append
```

On Linux, use the equivalent command:

```sh
python3 -m streetmesh \
  --data-dir ./m13-data/laptop-test \
  --node-name laptop-test@local@mesh \
  --udp-port 40404 2>&1 | tee -a ./m13-laptop-test.log
```

## Validate Node Discovery

Every node must discover both peers. Expected patterns include:

```text
INFO streetmesh.directory: Node discovered: node_name=pi01@local@mesh node_id=<PI_NODE_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
INFO streetmesh.directory: Node discovered: node_name=laptop@local@mesh node_id=<LAPTOP_NODE_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
INFO streetmesh.directory: Node discovered: node_name=laptop-test@local@mesh node_id=<TEST_NODE_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
```

Later announcements should produce `Node refreshed` lines. Self-broadcasts are
suppressed rather than added as remote awareness:

```text
INFO streetmesh.daemon: Suppressed received self-announcement: node_id=<LOCAL_NODE_ID> ko_id=<KO_ID>
```

## Validate Service Discovery

The Pi should announce `temperature`:

```text
INFO streetmesh.daemon: SERVICE announced: service_name=temperature provider=<PI_NODE_ID> ko_id=<KO_ID> seq=1 ttl=3 expires=<EPOCH_SECONDS>
```

Both laptop nodes should store it initially as limited awareness while the Pi
is unknown:

```text
INFO streetmesh.daemon: Policy accepted-limited: type=SERVICE origin=<PI_NODE_ID> trust_state=unknown reason=service-unknown ko_id=<KO_ID>
INFO streetmesh.directory: SERVICE discovered: service_name=temperature provider=<PI_NODE_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
```

## Validate Gossip and Duplicate Suppression

Record a Pi NODE or SERVICE `ko_id`. At least one receiving node must log the
same object being forwarded with a reduced TTL:

```text
INFO streetmesh.gossip: Gossip forwarded: ko_id=<KO_ID> origin=<PI_NODE_ID> ttl=3 forwarded_ttl=2
```

When a forwarded copy returns to a node that already processed it, the node
must suppress the duplicate instead of forwarding indefinitely:

```text
INFO streetmesh.directory: Duplicate Knowledge Object suppressed: ko_id=<KO_ID>
```

On a single shared LAN, direct receipt and gossip receipt can both occur. The
forwarding and duplicate logs validate gossip behavior; a routed two-segment
topology is required to prove that awareness arrived only through gossip.

## Validate Trust

1. On the Pi, inspect its identity and record `<PI_NODE_ID>`:

   ```sh
   python3 streetmeshd.py --data-dir ./m13-data/pi01 --status
   ```

2. Stop the Windows laptop node with `Ctrl+C`.
3. Mark the Pi trusted in the laptop's data directory:

   ```powershell
   python streetmeshd.py `
     --data-dir .\m13-data\laptop `
     --trust-node <PI_NODE_ID>
   ```

4. Restart `laptop@local@mesh` using the original command with `-Append`.
5. Wait for the Pi's next SERVICE announcement. The laptop must log normal
   trusted acceptance:

   ```text
   INFO streetmesh.daemon: Policy accepted: type=SERVICE origin=<PI_NODE_ID> trust_state=trusted reason=service-trusted ko_id=<KO_ID>
   INFO streetmesh.directory: SERVICE refreshed: service_name=temperature provider=<PI_NODE_ID> seq=<SEQUENCE> expires=<EPOCH_SECONDS>
   ```

6. Confirm the trust entry:

   ```powershell
   python streetmeshd.py --data-dir .\m13-data\laptop --list-trust
   ```

## Validate Stop and Expiry

1. Stop `pi01@local@mesh` with `Ctrl+C`. Leave both laptop nodes running.
2. NODE claims expire 120 seconds after creation. Within roughly 122 seconds of
   the Pi's final NODE announcement, both laptop nodes should log:

   ```text
   INFO streetmesh.directory: NODE_EXPIRED node_name=pi01@local@mesh node_id=<PI_NODE_ID> expires=<EPOCH_SECONDS>
   ```

3. SERVICE claims expire 300 seconds after creation. If the test waits for full
   service expiry, expect:

   ```text
   INFO streetmesh.directory: SERVICE expired: service_name=temperature provider=<PI_NODE_ID> expires=<EPOCH_SECONDS>
   ```

NODE expiry is required for this milestone. Waiting for SERVICE expiry is a
recommended additional check.

## Validate Restart and Re-Discovery

Restart the Pi with the same data directory and append to the same log:

```sh
python3 -m streetmesh \
  --data-dir ./m13-data/pi01 \
  --node-name pi01@local@mesh \
  --services-file ./examples/services.example.json \
  --udp-port 40404 2>&1 | tee -a ./m13-pi01.log
```

Using the same data directory preserves `<PI_NODE_ID>`. After the prior expiry,
the laptop logs must show a new discovery line after the `NODE_EXPIRED` line:

```text
INFO streetmesh.directory: Node discovered: node_name=pi01@local@mesh node_id=<PI_NODE_ID> seq=1 expires=<EPOCH_SECONDS>
```

The Pi's service should also be discovered or refreshed again. Leave all three
nodes running long enough for final awareness files to contain all three node
IDs and the Pi service.

## CLI Inspection

Run these commands for each node's data directory. Examples for the Windows
laptop are:

```powershell
python streetmeshd.py --data-dir .\m13-data\laptop --status
python streetmeshd.py --data-dir .\m13-data\laptop --list-nodes
python streetmeshd.py --data-dir .\m13-data\laptop --list-services
python streetmeshd.py --data-dir .\m13-data\laptop --list-trust
```

Pi equivalents use `python3` and `./m13-data/pi01`:

```sh
python3 streetmeshd.py --data-dir ./m13-data/pi01 --status
python3 streetmeshd.py --data-dir ./m13-data/pi01 --list-nodes
python3 streetmeshd.py --data-dir ./m13-data/pi01 --list-services
python3 streetmeshd.py --data-dir ./m13-data/pi01 --list-trust
```

Final inspection should show three known nodes on every participant. Both
laptops should show `temperature` from `<PI_NODE_ID>`. The Windows laptop trust
listing should show the Pi as `trusted`.

## Saved-State Helper

After the final checks, stop all nodes and collect artifacts on the Windows
laptop in this layout:

```text
m13-artifacts/
  laptop/
    data/
    streetmesh.log
  pi/
    data/
    streetmesh.log
  test/
    data/
    streetmesh.log
```

Copy the Pi artifacts, for example:

```powershell
New-Item -ItemType Directory -Force .\m13-artifacts\pi | Out-Null
scp -r <PI_USER>@<PI_ADDRESS>:~/streetmesh/m13-data/pi01 .\m13-artifacts\pi\data
scp <PI_USER>@<PI_ADDRESS>:~/streetmesh/m13-pi01.log .\m13-artifacts\pi\streetmesh.log
```

Copy the laptop data directories and combined logs into the matching folders,
then run:

```powershell
python tools\three_node_mesh_validation.py
```

Use `--help` to override artifact paths or the expected service name. The
standard-library helper checks unique identities, final three-node awareness,
Pi service visibility, laptop trust, peer discovery logs, gossip TTL reduction,
and ordered Pi expiry followed by re-discovery.

## Pass/Fail Acceptance Criteria

The test passes only when all required conditions are true:

1. Three distinct identities use the exact requested node names.
2. Every node discovers both peers.
3. Both laptop nodes discover the Pi's `temperature` service.
4. At least one Pi-originated claim is forwarded with TTL reduced from 3 to 2.
5. Duplicate copies are suppressed and do not create forwarding loops.
6. The Windows laptop marks the Pi trusted and later accepts its SERVICE claim
   normally rather than accepted-limited.
7. After the Pi stops, the laptop logs contain `NODE_EXPIRED` for the Pi.
8. After restart with the same data directory, the same Pi identity is
   discovered again after the expiry event.
9. Final persisted awareness on every node contains all three identities.
10. CLI inspection commands complete successfully and report the expected
    nodes, services, and trust state.
11. `python -m unittest discover` passes and `python streetmeshd.py --help`
    works on the validation revision.

Any missing condition is a failure. Preserve logs and data directories before
retrying so the cause can be compared.

## Troubleshooting

### UDP Broadcast

- Confirm all nodes use UDP port `40404` and are in the same IPv4 broadcast
  domain.
- Compare `ip address` and `ip route` on Linux with `ipconfig` on Windows.
- If `255.255.255.255` is filtered, configure the subnet broadcast address,
  such as `192.168.1.255`.
- Broadcast does not cross routers or VLANs without additional network design.
- Same-host shared-port delivery is platform-dependent; prefer three devices.

### Firewall

- Permit inbound and outbound UDP `40404` in Windows Defender Firewall.
- On Linux with UFW, run `sudo ufw allow 40404/udp`.
- Check router, access point, VLAN, and managed-switch filtering as well.

### Wi-Fi Isolation

Guest networks commonly enable AP/client isolation. Internet access can work
while peer-to-peer broadcasts are blocked. Disable isolation, use the main LAN
SSID, or connect nodes through Ethernet.

### Expired State

`--list-nodes` and `--list-services` label persisted entries as current or
expired. Confirm the remote daemon is running and clocks are synchronized.
NODE expiry is 120 seconds; SERVICE expiry is 300 seconds. Restarting a node
with a different data directory creates a new identity rather than re-discovering
the old one.

### Duplicate Suppression

Seeing `Duplicate Knowledge Object suppressed` is expected on a gossip mesh.
It means a node received an already processed `ko_id` and prevented a loop. A
problem exists if the same `ko_id` is repeatedly logged as `Gossip forwarded`
by the same node, or if unique new announcements are incorrectly suppressed.

### Artifact Helper Fails

- Make sure logs were appended across restarts rather than overwritten.
- Copy the final data directories only after re-discovery completed.
- Verify `trust.json` under the laptop artifact marks the Pi node ID trusted.
- Confirm filenames and directories match the documented layout, or pass
  explicit paths shown by `python tools\three_node_mesh_validation.py --help`.
