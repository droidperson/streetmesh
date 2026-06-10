# Milestone 12: Raspberry Pi Deployment

This guide deploys StreetMesh v0.1 on Raspberry Pi OS or a similar Debian-based
Linux system. StreetMesh uses only the Python 3 standard library and does not
require a virtual environment or third-party Python packages.

## Prerequisites

- Raspberry Pi running Raspberry Pi OS
- Python 3.10 or newer
- Git, or another way to copy the repository to the Pi
- Ethernet or Wi-Fi network connectivity
- Two or more devices on the same LAN for discovery and gossip testing
- UDP port `40404` permitted between the devices

Check the installed tools:

```sh
python3 --version
git --version
ip address
```

Install Python and Git if needed:

```sh
sudo apt update
sudo apt install -y python3 git
```

## Get StreetMesh

Clone the repository:

```sh
cd ~
git clone <REPOSITORY_URL> streetmesh
cd streetmesh
```

Alternatively, copy an existing checkout from another computer:

```sh
scp -r ./streetmesh <PI_USER>@<PI_ADDRESS>:/home/<PI_USER>/streetmesh
```

Run all following commands from the repository root unless an absolute path is
shown.

## Verify the Installation

Run the complete unit test suite:

```sh
python3 -m unittest discover
```

Check the command-line interface:

```sh
python3 streetmeshd.py --help
python3 streetmeshd.py --config examples/config.example.json --check-config
```

## Start One Node

Start a node with a dedicated data directory:

```sh
python3 streetmeshd.py \
  --data-dir data-node-a \
  --node-name node-a@pi@mesh \
  --udp-port 40404
```

StreetMesh creates `identity.json`, `awareness.json`, and `trust.json` beneath
the selected data directory. Stop the foreground daemon with `Ctrl+C`.

To advertise the example service as well:

```sh
python3 streetmeshd.py \
  --data-dir data-node-a \
  --node-name node-a@pi@mesh \
  --services-file examples/services.example.json \
  --udp-port 40404
```

## Start Three Nodes on One LAN

For the most reliable test, run one node per Raspberry Pi. All devices should
use the same UDP port and be connected to the same Ethernet or Wi-Fi broadcast
network. Running several processes on one Pi is not a substitute for this test:
shared-port UDP broadcast delivery varies by operating system.

On Raspberry Pi A:

```sh
cd ~/streetmesh
python3 streetmeshd.py \
  --data-dir data-node-a \
  --node-name node-a@pi@mesh \
  --services-file examples/services.example.json \
  --udp-port 40404
```

On Raspberry Pi B:

```sh
cd ~/streetmesh
python3 streetmeshd.py \
  --data-dir data-node-b \
  --node-name node-b@pi@mesh \
  --udp-port 40404
```

On Raspberry Pi C:

```sh
cd ~/streetmesh
python3 streetmeshd.py \
  --data-dir data-node-c \
  --node-name node-c@pi@mesh \
  --udp-port 40404
```

Each node should log NODE discovery and refresh events. Nodes receiving Node
A's service should also log SERVICE discovery or refresh according to local
trust policy. Gossip forwarding logs show the same Knowledge Object ID with a
decreased TTL.

Use a unique data directory for every node. Reusing a directory also reuses its
identity and persisted state.

## Inspect Persisted State

Inspection commands do not start networking. Run them with the same data
directory as the node being inspected.

Node A status:

```sh
python3 streetmeshd.py --data-dir data-node-a --status
```

Known nodes:

```sh
python3 streetmeshd.py --data-dir data-node-a --list-nodes
```

Known services:

```sh
python3 streetmeshd.py --data-dir data-node-a --list-services
```

Local trust decisions:

```sh
python3 streetmeshd.py --data-dir data-node-a --list-trust
```

The inspection output labels persisted claims as `current` or `expired`. An
expired row can remain visible after daemon shutdown because expiry cleanup runs
while the daemon is active; it will be removed and persisted during a later run.

## Optional systemd Service

The following example runs one StreetMesh node at boot. Replace `<PI_USER>` and
paths with values for the target Pi.

Create a persistent data directory:

```sh
sudo mkdir -p /var/lib/streetmesh
sudo mkdir -p /etc/streetmesh
sudo chown <PI_USER>:<PI_USER> /var/lib/streetmesh
```

Create `/etc/streetmesh/node.json`:

```json
{
  "node": {
    "node_name": "node-a@pi@mesh",
    "data_dir": "/var/lib/streetmesh",
    "announce_interval": 30,
    "service_announce_interval": 60,
    "services_file": "/home/<PI_USER>/streetmesh/examples/services.example.json",
    "udp_port": 40404,
    "bind_host": "0.0.0.0",
    "broadcast_host": "255.255.255.255"
  }
}
```

Create `/etc/systemd/system/streetmesh.service`:

```ini
[Unit]
Description=StreetMesh v0.1 node
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=<PI_USER>
Group=<PI_USER>
WorkingDirectory=/home/<PI_USER>/streetmesh
ExecStart=/usr/bin/python3 /home/<PI_USER>/streetmesh/streetmeshd.py --config /etc/streetmesh/node.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Load and start the service:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now streetmesh.service
sudo systemctl status streetmesh.service
```

Follow logs and stop or restart the node:

```sh
sudo journalctl -u streetmesh.service -f
sudo systemctl restart streetmesh.service
sudo systemctl stop streetmesh.service
```

After changing the trust store with `--trust-node` or `--block-node`, restart a
running systemd node so it reloads the local trust decisions.

## Troubleshooting

### UDP Broadcast Does Not Work

- Confirm every node uses the same `--udp-port`, normally `40404`.
- Confirm the Pis are in the same IPv4 subnet and broadcast domain with
  `ip address` and `ip route`.
- Check that the daemon is bound to UDP port `40404`:

  ```sh
  sudo ss -lunp | grep 40404
  ```

- The default limited broadcast address is `255.255.255.255`. If the network
  does not pass limited broadcasts, set `broadcast_host` in a configuration file
  to the subnet broadcast address shown by `ip address`, such as
  `192.168.1.255`.
- Do not expect UDP broadcast to cross routers or VLAN boundaries.

### Firewall

Raspberry Pi OS may have no host firewall enabled, but a configured firewall
must permit inbound and outbound UDP port `40404`. For systems using UFW:

```sh
sudo ufw allow 40404/udp
sudo ufw status
```

Also check router, access point, VLAN, and managed-switch rules.

### Wi-Fi Client Isolation

Many guest Wi-Fi networks and some access points enable AP isolation, client
isolation, or wireless isolation. This prevents wireless clients from reaching
each other even though internet access works. Disable isolation, use the main
LAN SSID, or connect the Pis through Ethernet.

### Wrong Data Directory

Inspection and trust commands must use the exact data directory used by the
daemon. Check the daemon command or `data_dir` in its JSON configuration:

```sh
python3 streetmeshd.py --data-dir data-node-a --status
ls -la data-node-a
```

If a node unexpectedly has a different ID, it was probably started with a new
or empty data directory.

### Stale or Expired Awareness

NODE claims normally expire after 120 seconds and SERVICE claims after 300
seconds if they are not refreshed. Check the `expires` and `status` columns:

```sh
python3 streetmeshd.py --data-dir data-node-a --list-nodes
python3 streetmeshd.py --data-dir data-node-a --list-services
```

Verify the remote daemon is still running, the system clocks are reasonably
synchronized, and UDP broadcasts are still being received. Raspberry Pi OS
normally synchronizes time through systemd-timesyncd; inspect it with:

```sh
timedatectl status
```

Restarting StreetMesh reloads persisted awareness and resumes normal expiry
cleanup. Do not delete a data directory unless intentionally resetting that
node's identity, trust decisions, and awareness.
