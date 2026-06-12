# Milestone 15: Signature-Aware Trust Policy

Milestone 15 connects Knowledge Object signatures to StreetMesh awareness,
policy decisions, logs, persistence, and CLI inspection. It preserves the
review-mode trust model while making the limits of the interim HMAC design
visible instead of treating every signature as equally verifiable.

## Purpose

Milestone 14 proved that a node can persist a signing secret and create stable
HMAC-SHA256 signatures for its local NODE and SERVICE claims. Milestone 15 adds
the next layer: each processed claim receives a signature status that travels
with the policy decision and persisted awareness entry.

Signature status and trust state remain separate. A signature describes what
StreetMesh could verify about the KO. Trust state describes the local policy
relationship with its origin. A signed claim is not automatically trusted.

## Signature Statuses

- `unsigned`: The KO has no signature or signature algorithm.
- `signed_self_verified`: The KO originated from the local node and its HMAC
  verifies with the local identity's signing secret.
- `signed_unverified_remote`: The KO carries an HMAC signature from another
  origin, but this node does not possess that origin's secret.
- `signature_invalid`: Verification was possible with the local signing secret
  and the HMAC did not match the KO content.
- `signature_unsupported`: The KO names a signature algorithm this version of
  StreetMesh does not implement.
- `signature_not_checked`: Signature history is unavailable or verification
  could not be attempted, including awareness loaded from older files.

## Interim HMAC Verification

The Milestone 14 canonical format remains unchanged. StreetMesh signs compact,
key-sorted JSON for the KO with the `signature` field excluded. The algorithm
is `HMAC-SHA256` and each node's 256-bit secret stays in its local
`identity.json`.

At runtime, a node verifies a signed KO only when all of the following are
true:

1. The KO origin is the local node ID.
2. The local identity signing secret is available.
3. The KO uses `HMAC-SHA256`.

Remote HMAC signatures are classified as `signed_unverified_remote`. StreetMesh
does not exchange signing secrets, so a remote node cannot safely reproduce the
verification performed by the origin. A trusted remote origin still receives
this status; trust does not manufacture cryptographic verification.

## Policy Behaviour

Existing review-mode behavior remains in effect:

- unknown NODE claims remain visible as awareness;
- unknown SERVICE claims remain accepted-limited;
- trusted SERVICE claims remain accepted normally;
- sensitive GATEWAY, FEDERATION, and INTRODUCTION claims remain quarantined;
- blocked and revoked origins remain rejected; and
- signed-but-unverified remote claims are not rejected merely because HMAC
  verification is unavailable.

When a local-origin HMAC can be checked and fails, policy rejects the claim and
does not store or gossip it. Policy logs include `signature_status` for accepted,
accepted-limited, quarantined, and rejected decisions.

## Awareness And Inspection

Node and service entries persist `signature_status` in `awareness.json`.
Awareness files from Milestone 13 or 14 that lack the field load normally and
use `signature_not_checked` until a newer claim refreshes the entry.

Inspect persisted status with:

```sh
python streetmeshd.py --list-nodes
python streetmeshd.py --list-services
```

Both tables include a `signature_status` column. Raw signatures and signing
secrets are not printed.

## Gossip

Gossip continues to preserve `origin`, `signature_algorithm`, and `signature`
unchanged and does not re-sign another node's KO. Only the gossip TTL changes.
With the current wire format, TTL is part of the original signed content, so a
forwarded copy cannot be end-to-end verified against that HMAC. Remote copies
therefore remain signed-but-unverified under this milestone.

## What Is Protected Now

- Local software can verify its own newly originated KOs.
- Changes to locally verifiable signed fields are detected.
- Invalid self-origin HMAC claims are rejected by policy.
- Operators can distinguish unsigned, locally verified, remotely unverified,
  unsupported, invalid, and historical unchecked awareness.
- Signature state survives daemon shutdown through awareness persistence.

## What Is Not Protected Yet

- Remote nodes cannot verify one another without sharing HMAC secrets.
- A remote signature does not prove public node identity or node-name ownership.
- Trust entries do not contain public verification keys.
- Gossip TTL mutation prevents end-to-end verification of the current signed KO.
- There is no key rotation, revocation proof, certificate, or delegation model.
- Signatures do not authorize service invocation.

## Why Public-Key Signatures Are Deferred

Public-key signing requires more than replacing one cryptographic primitive.
StreetMesh must define how node keys bind to names, how keys rotate, how trust
is introduced, and which claim fields remain immutable through gossip. Those
protocol and policy decisions are deferred so they can be designed together.

## Future Evolution

The intended path includes:

- public/private key node identities;
- signed node-name ownership;
- remotely verifiable trusted service claims;
- immutable signed claim bodies with mutable gossip envelopes;
- trust chains and certificate-like delegation; and
- invitation-based trust establishment.

## Verification

Run the standard-library suite and CLI smoke test:

```sh
python -m unittest discover
python streetmeshd.py --help
```
