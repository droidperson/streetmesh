# Milestone 20: Service Access Preflight

Milestone 20 adds a read-only safety decision before any future StreetMesh
service adapter may attempt access.

Preflight answers:

> Given this service name and current local mesh state, would an access attempt
> be valid under current trust, binding, conflict, expiry, and metadata policy?

It does not perform the access attempt.

## Preflight Is Not Invocation

Service preflight reads persisted awareness, trust, name bindings, and resolver
results. It does not:

- call HTTP or HTTPS endpoints
- open service sockets or probe ports
- invoke SSH, SFTP, or SMB
- mount file shares
- execute commands
- ping providers
- contact advertised endpoints in any way

Every result reports:

```text
access_action : no network access performed
```

Existing UDP discovery and gossip behavior is unchanged. The preflight path
itself performs no network operation.

## CLI

```sh
python streetmeshd.py --data-dir ./m20-data/laptop \
  --preflight-service temperature
```

Example allowed result:

```text
service_name         : temperature
decision             : allowed
reason               : Service resolved to a current trusted bound provider.
provider_node_name   : pi01@local@mesh
provider_node_id     : 550e8400-e29b-41d4-a716-446655440000
trust_state          : trusted
binding_status       : bound
provider_status      : current
service_status       : current
protocol             : http
endpoint             : /temperature
provider_usable      : yes
service_limited      : no
candidate_count      : 1
access_action        : no network access performed
```

The result also includes provider fingerprint, optional `public_key_id`,
signature status, and warnings.

## Decisions

- `allowed`: a current local/privileged or trusted bound provider is clearly
  preferred and the service has recognized protocol and endpoint metadata.
- `limited`: the service is visible through an unknown, observed, candidate,
  or otherwise incompletely bound provider. No access is performed.
- `denied`: policy rejects the provider or required provider/endpoint state is
  missing.
- `ambiguous`: multiple current usable providers exist without a clear trusted
  bound winner.
- `not_found`: no service advertisement matches the requested name.
- `conflict`: the selected provider has a conflicting or stale node-name
  binding.
- `expired`: the service advertisement or provider awareness is expired.
- `unsupported`: protocol metadata is missing or not recognized.

Recognized protocol labels currently include HTTP, HTTPS, file, SSH, SFTP,
SMB, TCP, and UDP. Recognition only means the metadata can be described. It
does not mean an adapter exists or that StreetMesh will contact the endpoint.

## Decision Inputs

Preflight builds on the existing service resolver and then checks:

1. Service and provider currentness.
2. Provider node awareness availability.
3. Trust state, including blocked, revoked, and quarantined origins.
4. Node-name binding and conflict status.
5. Signature status.
6. Protocol and endpoint presence.
7. Candidate ambiguity and whether a trusted bound provider clearly outranks
   lower-trust or conflicting alternatives.

Multiple ordinary providers remain valid awareness. If no clear safe winner
exists, preflight returns `ambiguous`. If one trusted bound provider clearly
outranks unknown or conflicting alternatives, it may return `allowed` with
warnings describing the other candidates and name conflicts.

Preflight never creates trust, changes a name binding, replaces an owner, or
promotes a provider.

## Safe Failure

Older awareness files and services missing optional fields continue to load.
Missing provider awareness, protocol, or endpoint data produces a conservative
decision instead of an exception or access attempt.

## Future Direction

This result model is the policy gate for future adapters, which may include:

- HTTP service adapters
- file service adapters
- shell or command adapters
- policy-controlled access scopes
- explicit user confirmation
- access audit logging
- signed service ownership

Those adapters are not implemented in Milestone 20. A future caller must first
receive an appropriate preflight result and still apply its own authorization,
confirmation, and auditing rules before performing any access.
