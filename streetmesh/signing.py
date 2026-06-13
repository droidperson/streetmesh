"""Signing and verification abstractions for StreetMesh identities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import string
from typing import Literal, Protocol


HMAC_SHA256 = "HMAC-SHA256"
ED25519_PLANNED = "ED25519-PLANNED"
PUBLIC_KEY_UNSUPPORTED = "PUBLIC-KEY-UNSUPPORTED"

VerificationStatus = Literal[
    "verified",
    "invalid",
    "unsupported",
    "missing_key",
    "planned",
]


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    algorithm: str | None
    verified: bool
    reason: str


class Signer(Protocol):
    algorithm: str

    def sign(self, message: bytes) -> str:
        """Return a signature for canonical message bytes."""


class SignatureVerifier(Protocol):
    algorithm: str

    def verify(self, message: bytes, signature: str) -> VerificationResult:
        """Verify a signature over canonical message bytes."""


class HmacSigner:
    """Standard-library HMAC-SHA256 signer used by current local identities."""

    algorithm = HMAC_SHA256

    def __init__(self, signing_secret: str) -> None:
        self._secret = _decode_secret(signing_secret)

    def sign(self, message: bytes) -> str:
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()


class HmacVerifier:
    """Verifier for HMAC signatures when the shared secret is available."""

    algorithm = HMAC_SHA256

    def __init__(self, signing_secret: str) -> None:
        self._signer = HmacSigner(signing_secret)

    def verify(self, message: bytes, signature: str) -> VerificationResult:
        if not isinstance(signature, str):
            return VerificationResult(
                "invalid",
                self.algorithm,
                False,
                "Signature must be text.",
            )
        expected = self._signer.sign(message)
        verified = hmac.compare_digest(signature, expected)
        return VerificationResult(
            "verified" if verified else "invalid",
            self.algorithm,
            verified,
            "HMAC verified." if verified else "HMAC did not match.",
        )


class UnsupportedPublicKeyVerifier:
    """Explicit placeholder that never pretends to verify public-key signatures."""

    def __init__(
        self,
        algorithm: str,
        *,
        public_key_material: str | None = None,
    ) -> None:
        self.algorithm = algorithm
        self.public_key_material = public_key_material

    def verify(self, message: bytes, signature: str) -> VerificationResult:
        del message, signature
        if self.algorithm == ED25519_PLANNED:
            return VerificationResult(
                "planned",
                self.algorithm,
                False,
                "Ed25519 support is planned but not implemented.",
            )
        if self.public_key_material is None:
            return VerificationResult(
                "missing_key",
                self.algorithm,
                False,
                "No public key material is configured.",
            )
        return VerificationResult(
            "unsupported",
            self.algorithm,
            False,
            "No standard-library verifier is available for this algorithm.",
        )


def _decode_secret(signing_secret: object) -> bytes:
    if (
        not isinstance(signing_secret, str)
        or len(signing_secret) != 64
        or any(character not in string.hexdigits for character in signing_secret)
    ):
        raise ValueError("signing_secret must be 64 hexadecimal characters")
    return bytes.fromhex(signing_secret)
