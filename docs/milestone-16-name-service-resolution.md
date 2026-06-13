# Milestone 16: Name and Service Resolution

Milestone 16 adds a read-only resolution layer above StreetMesh awareness.
Awareness remains the raw set of discovered NODE and SERVICE claims. Resolution
interprets those claims, ranks candidates, chooses a preferred current result
when possible, and explains uncertainty without invoking any service.

## Awareness And Resolution

The Awareness Store answers: "What claims have this node observed?"

The resolver answers:

- Which node ID currently corresponds to this node name?
- Which provider is the best candidate for this service name?
- Is the preferred result trusted, signed, limited, expired, rejected, or
  ambiguous?
- Which alternative candidates were considered and how were they ranked?

Resolution reads persisted awareness and trust state. It does not remove
expired entries, write JSON, broadcast Knowledge Objects, or require a running
daemon.

## Node Resolution

Resolve an exact node name:

```sh
python -m streetmesh --data-dir ./data --resolve-node pi01@local@mesh
```

The result includes:

- `resolution_status`
- node name and node ID
- trust and signature status
- first and last observation times
- expiry and currentness
- candidate count and explanatory reason

If multiple current usable node IDs claim the same name, resolution reports
`conflict`, selects the highest-ranked candidate for inspection, and displays
all candidates. It does not claim that the conflict has been resolved.

## Service Resolution

Resolve an exact service name:

```sh
python -m streetmesh --data-dir ./data --resolve-service temperature
```

Existing short service names remain supported. Future fully qualified names,
such as `temperature@local@mesh`, are also accepted as exact names without
forcing a migration of current service definitions.

The result includes the preferred provider node ID and name when known,
endpoint, protocol, trust state, signature status, expiry, currentness, and the
ranked candidate list when more than one provider advertises the service.

An unknown or otherwise limited provider can still resolve with status
`limited`. This makes awareness usable for inspection without presenting the
provider as fully trusted.

## Provider Ranking

Candidates are ranked deterministically in this order:

1. Current entries before expired entries.
2. Usable entries before blocked, revoked, quarantined, or invalid-signature
   entries.
3. Privileged and trusted providers before lower trust states.
4. `signed_self_verified` before `signed_unverified_remote`, and remotely
   signed entries before unsigned or unchecked entries.
5. More recently seen entries and later expiry times before stale entries.
6. Node ID as a stable final tie-breaker.

When multiple current usable service providers remain, the result is
`ambiguous`. The resolver still exposes the preferred candidate, but also
returns and prints every ranked candidate so uncertainty is not hidden.

## Resolution Statuses

- `resolved`: One current usable node or trusted service provider was selected.
- `limited`: One current service provider was selected with limited trust.
- `ambiguous`: Multiple current usable service providers exist.
- `conflict`: Multiple current usable node IDs claim the same node name.
- `expired`: Only expired matching awareness exists.
- `rejected`: Current matches exist, but none are usable under trust/signature
  policy.
- `not_found`: No matching node or service awareness exists.

## Example Node Output

```text
resolution_status : resolved
node_name          : pi01@local@mesh
node_id            : 550e8400-e29b-41d4-a716-446655440000
trust_state        : trusted
signature_status   : signed_unverified_remote
status             : current
candidate_count    : 1
```

## Example Service Output

```text
resolution_status  : limited
service_name       : temperature
provider_node_id   : pi01-id
provider_node_name : pi01@local@mesh
endpoint           : /temperature
protocol           : http
trust_state        : unknown
signature_status   : signed_unverified_remote
status             : current
candidate_count    : 1
```

## Backward Compatibility

Awareness written before Milestone 15 may omit `signature_status` or
`trust_state`. Existing loaders supply `signature_not_checked` and `unknown`,
so those entries remain resolvable without rewriting the file. Existing short
service names and Milestone 13-15 discovery, gossip, expiry, signing, trust,
and inspection behavior are unchanged.

## Why Invocation Is Deferred

Resolution selects and explains a candidate; it does not authorize or contact
that candidate. StreetMesh does not perform HTTP requests, SSH, SFTP, remote
shell commands, file transfer, or any other service access in this milestone.

Future service access should begin with a preflight stage that checks resolution
status, trust, signature evidence, protocol support, endpoint policy, and user
authorization. Protocol-specific adapters can be added only after those rules
are explicit and testable.

## Verification

```sh
python -m unittest discover
python streetmeshd.py --help
```
