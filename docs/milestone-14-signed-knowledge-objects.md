# Milestone 14: Signed Knowledge Objects

Milestone 14 adds origin signing to locally created StreetMesh NODE and SERVICE
Knowledge Objects. It establishes deterministic signed objects without adding a
third-party dependency or claiming that HMAC provides public identity proof.

## Purpose

Each persistent node identity now owns a 256-bit signing secret. The daemon uses
that secret to sign every NODE and SERVICE KO it originates. Given the same
secret, StreetMesh can verify that the signed fields have not changed since the
KO was created.

This milestone proves that StreetMesh can:

- persist signing material with a stable node identity;
- upgrade existing identities without changing `node_id` or `node_name`;
- serialize a KO deterministically for signing;
- detect changes to signed content;
- sign local NODE and SERVICE claims; and
- preserve an origin signature while gossiping a claim.

## Identity Upgrade

New `identity.json` files include a `signing_secret` generated with
`secrets.token_hex(32)`. When the daemon loads an older identity without that
field, it creates a secret and rewrites the identity file in place. Existing
identity fields remain unchanged.

The signing secret is local private state. Normal status and inspection output
does not print it. Protect and back up the data directory as you would any other
credential store.

## Interim HMAC Design

The algorithm name on the wire is `HMAC-SHA256`. Signed KOs include:

```json
{
  "signature_algorithm": "HMAC-SHA256",
  "signature": "<64-character SHA-256 HMAC digest>"
}
```

StreetMesh computes the HMAC over UTF-8 JSON with:

- the `signature` field excluded;
- `sort_keys=True`; and
- compact separators `(',', ':')`.

The `signature_algorithm` field is included in the signed representation.
Unsigned legacy KOs with a null signature remain structurally valid for
Milestone 13 compatibility.

## Verification Scope

Verification is available when the verifier has the origin node's signing
secret. In this milestone that means local/self verification and unit tests.
Secrets are not exchanged over StreetMesh and remote HMAC signatures are not
treated as public proof of identity.

Gossip forwarding preserves the original signature and changes only `ttl`, as
required by the existing forwarding protocol. Because `ttl` is part of the
signed KO, the forwarded copy does not verify against the original HMAC after
its hop count changes. A future protocol should separate immutable signed claim
content from a mutable gossip envelope rather than re-signing another node's
claim.

## Limitations

- HMAC uses a shared secret and does not provide public verification.
- No signing secrets, public keys, or certificates are exchanged.
- Signatures do not establish name ownership or trust by themselves.
- A valid signature does not make a claim trusted; policy remains separate.
- Forwarded KOs need a future immutable-body design for end-to-end validation.
- Key rotation and recovery are not implemented yet.

## Future Evolution

The intended next design replaces the interim HMAC model with public/private
key node identities. That will support:

- verification using public node keys;
- cryptographic node-name ownership;
- trust chains and signed introductions;
- signed service claims that remain verifiable through gossip; and
- key rotation, revocation, and recovery mechanisms.

Public-key signatures and certificates are deliberately deferred until those
identity and trust semantics can be designed together.

## Verification

Run the standard-library test suite:

```sh
python -m unittest discover
```

The tests cover identity creation and migration, deterministic signing, tamper
detection, signed NODE and SERVICE creation, and gossip signature preservation.
