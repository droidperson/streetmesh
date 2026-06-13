# Milestone 18: Public-Key Identity Model

Milestone 18 prepares StreetMesh identities and signature handling for a future
public-key backend while preserving the HMAC-SHA256 behavior introduced in
Milestone 14.

## Why Public-Key Identity Is Needed

The current HMAC model proves that a Knowledge Object was created with a
persistent local secret. It is useful for canonical signing, tamper detection,
and self-verification. It cannot provide independent remote verification
without sharing that secret, which StreetMesh deliberately does not do.

A future public-key identity will let a node distribute a public verification
key while retaining its private signing key locally. That is required for
verifiable remote claims, stronger name ownership, and trust chains.

## Security Boundary

Python's standard library does not provide a complete modern public-key signing
API suitable for StreetMesh. This milestone therefore does not implement
homemade cryptography, fake key pairs, fake public-key signatures, certificates,
or signing-secret exchange.

StreetMesh continues to emit only real HMAC-SHA256 signatures. Public-key
algorithm names and statuses are model states and extension points, not claims
that public-key verification occurred.

## Identity Version 2

New and upgraded `identity.json` files include:

```json
{
  "identity_version": 2,
  "node_id": "persistent-node-id",
  "node_name": "node@local@mesh",
  "created": "2026-06-13T00:00:00+00:00",
  "fingerprint": "...",
  "signing_algorithm": "HMAC-SHA256",
  "signing_secret": "local-secret-not-for-display",
  "public_identity": {
    "public_key_id": null,
    "public_key_algorithm": null,
    "public_key_material": null,
    "public_key_created": null,
    "public_key_status": "not_configured"
  }
}
```

Legacy identities upgrade automatically. Their `node_id`, `node_name`,
fingerprint, and existing signing secret are preserved. An older identity that
lacks a signing secret still receives the secure Milestone 14 upgrade.

## Public And Private Material

Safe NODE awareness may include the fingerprint, `public_key_id`,
`public_key_algorithm`, and `public_key_status`. These fields are optional and
currently normally report `not_configured`.

The HMAC `signing_secret` is private local state. It is never placed in a NODE
payload, awareness record, trust listing, status output, or gossip object.
`public_key_material` is reserved for a future real public key and is not
advertised by this milestone.

## Signing And Verification Model

`streetmesh.signing` defines small signer and verifier interfaces plus these
current implementations:

- `HmacSigner` produces the existing canonical HMAC-SHA256 signatures.
- `HmacVerifier` verifies when the HMAC secret is locally available.
- `UnsupportedPublicKeyVerifier` reports planned, missing-key, or unsupported
  states and never reports successful verification.

Existing `signing_secret` protocol APIs remain supported. New callers may
inject a signer, allowing a later crypto backend without changing Knowledge
Object canonicalization, gossip, policy, or storage behavior.

Signature inspection can distinguish:

- `signed_self_verified`
- `signed_unverified_remote`
- `unsigned`
- `signature_invalid`
- `signature_unsupported`
- `public_key_unsupported`
- `public_key_missing`
- `public_key_planned`

Remote HMAC claims remain `signed_unverified_remote`; StreetMesh does not infer
trust from a signature it cannot verify.

## Trust And Inspection

Awareness and trust records can retain an optional `public_key_id` alongside the
existing fingerprint and name binding. Old awareness and trust files continue
to load with absent public-key fields.

`--status` reports the local signing algorithm and public-key status without
showing secrets. `--list-nodes`, `--list-trust`, and trust detail output show a
public-key identifier when one is available.

## Future Migration

A later milestone can supply a reviewed public-key backend and migrate in
stages:

1. Generate and securely persist real public/private node key pairs.
2. Advertise public keys and stable key identifiers.
3. Sign and remotely verify Knowledge Objects with the public-key algorithm.
4. Bind node names and service claims to verifiable keys.
5. Add trust chains and invitation-based trust establishment.
6. Support an optional cryptography dependency or pluggable crypto backend.

Until then, HMAC remains the only active signing algorithm and all public-key
states are explicitly non-verifying.
