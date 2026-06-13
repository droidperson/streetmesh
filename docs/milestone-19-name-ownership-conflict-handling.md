# Milestone 19: Name Ownership And Conflict Handling

Milestone 19 gives StreetMesh persistent local memory of which stable node
identity owns a node name. It prevents a newer claimant from silently replacing
an identity that the local operator has already bound.

This is local ownership memory, not global cryptographic ownership.

## Awareness Versus Ownership

Awareness answers: "Which nodes currently claim this name?"

Name binding answers: "Which node identity has this installation accepted as
the stable owner of this name?"

StreetMesh keeps conflicting claims visible in awareness. It does not treat
visibility as permission to replace an established binding.

Bindings and conflicts are persisted in the node data directory as
`name_bindings.json`. A missing file is valid and loads as an empty registry.

## Binding Records

A binding records:

- `node_name`
- `node_id`
- optional fingerprint and `public_key_id`
- `binding_state` (`local` or `bound`)
- `first_bound` and `last_confirmed`
- source (`local`, `trusted`, `manual`, or `observed`)
- optional notes

The local node creates a `local` binding for its persistent identity when the
daemon starts. Existing bound Milestone 17 trust entries are imported without
changing their node IDs, trust states, or identity metadata.

## Trusted Bindings

Trusting a resolved node name updates both `trust.json` and
`name_bindings.json`:

```sh
python streetmeshd.py --data-dir ./m19-data/laptop \
  --trust-node-name pi01@local@mesh
```

The resolved node ID becomes the locally remembered owner. Reconfirming the
same identity updates `last_confirmed`. It does not create a conflict.

## Conflict Detection

Suppose `pi01@local@mesh` is bound to node ID A. If node ID B later announces
the same name:

- A remains the bound owner.
- B remains visible in awareness.
- B receives `binding_status=name_conflict`.
- The conflict is persisted with first/last observation times.
- Services from B inherit the provider conflict status.
- B cannot become the preferred result merely by announcing more recently.

This avoids unsafe last-writer-wins behavior. Unknown observed claims do not
automatically create ownership bindings.

## Resolver Behavior

`--resolve-node` applies these rules:

1. A current bound identity is preferred.
2. Other current claimants are reported in the candidate list and reason.
3. If the bound identity is unavailable and another node claims its name, the
   result is `conflict`; the claimant is not silently substituted.
4. Multiple unbound node IDs claiming one name produce `conflict`.
5. A name with no awareness entry produces `not_found`.

Service names remain provider-oriented. Multiple providers for a simple name
such as `temperature` are normal. Service ranking inherits each provider's
node binding status, so a `name_conflict` provider is not usable or preferred
over a bound provider.

A future naming model may support fully qualified service ownership such as
`temperature@local@mesh`. Milestone 19 does not require that migration and does
not change existing service definitions.

## Inspection Commands

```sh
python streetmeshd.py --data-dir ./m19-data/laptop --list-name-bindings
python streetmeshd.py --data-dir ./m19-data/laptop \
  --show-name-binding pi01@local@mesh
python streetmeshd.py --data-dir ./m19-data/laptop --list-name-conflicts
```

The output includes identity metadata, binding source and timestamps, current
local trust state, and conflicting claimant details. Existing `--list-nodes`,
`--resolve-node`, `--resolve-service`, and `--list-trust` commands remain
compatible.

## Security Scope And Future Direction

The registry expresses one installation's local decision. It does not prove
that a node owns a name globally, and it cannot turn a remote HMAC into public
proof. Milestone 19 does not implement public-key cryptography, certificates,
service invocation, or automatic rebinding.

Future signed ownership can build on this model by adding reviewed real
public/private key signatures, public-key-bound names, signed name transfer,
trust chains, and invitation-based establishment. Until then, stable local
identity continuity takes precedence over the newest claim.
