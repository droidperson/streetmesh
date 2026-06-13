# Milestone 17: Trust Promotion and Name Binding

Milestone 17 lets an operator grant trust or blocking policy through a resolved
StreetMesh node name. The resulting trust record binds that human-readable name
to a stable node ID so a later claimant cannot silently take over the name.

## Purpose

Earlier milestones separated awareness, trust, signatures, and resolution.
Milestone 17 connects them in an explicit user workflow:

1. Awareness discovers a node claim.
2. Resolution identifies the current usable node ID for its name.
3. The user chooses to trust or block that resolved identity.
4. StreetMesh stores the node name, node ID, fingerprint when available,
   timestamps, and binding status in `trust.json`.
5. Future inspection, policy, and service resolution apply that user-granted
   trust to the bound node ID.

Trust promotion never exchanges or exposes a signing secret.

## Trusting By Node Name

Resolve and trust a node in one command:

```sh
python -m streetmesh --data-dir ./data --trust-node-name pi01@local@mesh
```

StreetMesh creates a binding only when resolution finds exactly one current,
usable node. The output reports:

- node name and node ID;
- previous and new trust state;
- signature status;
- binding status;
- fingerprint when awareness contains one; and
- first-trusted and last-confirmed timestamps.

Missing, expired, rejected, or ambiguous names are refused without creating a
trust record.

Raw node-ID administration remains available:

```sh
python -m streetmesh --data-dir ./data --trust-node NODE_ID
```

Raw ID trust does not invent a name binding when no resolved name was supplied.

## Blocking By Node Name

Resolve and block a node identity with:

```sh
python -m streetmesh --data-dir ./data --block-node-name pi01@local@mesh
```

The command uses the same exact-current-resolution requirement and stores the
resolved name binding with trust state `blocked`. Ambiguous names are not
blocked. Existing raw ID blocking continues to work with `--block-node`.

## Trust Records

Enriched trust entries can contain:

- `node_id`
- `state`
- `node_name`
- `fingerprint`
- `first_trusted`
- `last_confirmed`
- `binding_status`

Older `trust.json` entries containing only `node_id` and `state` still load and
are treated as `unbound`.

Inspect all entries or one binding:

```sh
python -m streetmesh --data-dir ./data --list-trust
python -m streetmesh --data-dir ./data --show-trust pi01@local@mesh
python -m streetmesh --data-dir ./data --show-trust NODE_ID
```

## Name Binding Status

- `unbound`: The identity has trust state but no user-bound node name.
- `bound`: The claim's node name and node ID match the stored binding.
- `name_conflict`: A different node ID claims a name already bound elsewhere.
- `stale_binding`: A bound node ID claims a different name from its stored
  binding.
- `unknown`: Binding evidence was unavailable in older awareness or other
  incomplete state.

## Binding Conflicts

Suppose `pi01@local@mesh` is bound to node ID A. If node ID B later announces
the same name, StreetMesh:

- keeps the binding to A unchanged;
- stores B as visible awareness with `name_conflict`;
- logs the trusted-name conflict;
- does not promote B to trusted merely because it used the name; and
- excludes B and B's services from preferred resolution candidates.

This is deliberately not last-writer-wins. Changing the trusted owner requires
an explicit future administrative workflow; incoming network traffic cannot do
it automatically.

If node ID A later announces a different name, that claim is marked
`stale_binding`. Trust in A's identity remains recorded, but the new name does
not inherit the old trusted-name binding.

## Why Stable Identity Matters

Names are convenient for people but are easy for another node to repeat. The
node ID is the stable local trust key. Binding the familiar name to that ID lets
StreetMesh preserve user intent across refreshed announcements and detect
identity continuity problems instead of silently following the newest claim.

## Relationship To Signatures

`signature_status` and trust remain separate:

- `signed_unverified_remote` means the remote HMAC is present but cannot be
  verified without the remote secret.
- `trusted` means the local user explicitly granted policy trust to the resolved
  node ID.
- A name binding does not turn an unverified HMAC into cryptographic proof.

Milestone 17 is therefore user-granted local trust, not public-key identity or
certificate trust.

## Example Workflow

1. Discover and inspect the Pi:

   ```sh
   python -m streetmesh --data-dir ./data --resolve-node pi01@local@mesh
   ```

2. Before promotion, resolve its service:

   ```sh
   python -m streetmesh --data-dir ./data --resolve-service temperature
   ```

   An unknown provider normally resolves as `limited`.

3. Trust the resolved node name:

   ```sh
   python -m streetmesh --data-dir ./data --trust-node-name pi01@local@mesh
   ```

4. Resolve the service again:

   ```sh
   python -m streetmesh --data-dir ./data --resolve-service temperature
   ```

   The Pi provider now carries trust state `trusted` and is no longer presented
   as unknown-limited.

## Deferred Work

This milestone does not implement public/private key identities, certificates,
name registries, service invocation, adapters, or automatic binding transfer.
Future public-key work can make remote identity and name ownership
cryptographically verifiable while preserving this explicit local trust model.

## Verification

```sh
python -m unittest discover
python streetmeshd.py --help
```
