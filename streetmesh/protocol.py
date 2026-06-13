"""StreetMesh Knowledge Object protocol primitives."""

from __future__ import annotations

import json
import string
import time
import uuid
from typing import Any, Literal, get_args

from .signing import (
    ED25519_PLANNED,
    HMAC_SHA256,
    PUBLIC_KEY_UNSUPPORTED,
    HmacSigner,
    HmacVerifier,
    Signer,
    UnsupportedPublicKeyVerifier,
)

PROTOCOL_NAME = "streetmesh"
PROTOCOL_VERSION = 1
SIGNATURE_ALGORITHM = HMAC_SHA256
SignatureStatus = Literal[
    "unsigned",
    "signed_self_verified",
    "signed_unverified_remote",
    "signature_invalid",
    "signature_unsupported",
    "signature_not_checked",
    "public_key_unsupported",
    "public_key_missing",
    "public_key_planned",
]
SIGNATURE_STATUSES = frozenset(get_args(SignatureStatus))
SUPPORTED_TYPES = {
    "NODE",
    "SERVICE",
    "GATEWAY",
    "FEDERATION",
    "INTRODUCTION",
}
REQUIRED_FIELDS = (
    "v",
    "ko_id",
    "type",
    "origin",
    "subject",
    "created",
    "expires",
    "seq",
    "ttl",
    "payload",
    "signature",
)


class KnowledgeObjectError(ValueError):
    """Raised when a Knowledge Object cannot be created or validated."""


def create_node_knowledge_object(
    *,
    origin: str,
    subject: str,
    payload: dict[str, Any],
    seq: int = 1,
    ttl: int = 3,
    expires_in: int | None = None,
    expires_in_seconds: int | None = None,
    now: int | None = None,
    signing_secret: str | None = None,
    signer: Signer | None = None,
) -> dict[str, Any]:
    """Create a NODE Knowledge Object.

    TTL is a gossip hop count. Expiry is controlled separately by expires_in or
    expires_in_seconds, defaulting to 120 seconds for NODE objects.

    When signing_secret is supplied, the returned object is signed with the
    local identity's HMAC-SHA256 secret.
    """

    created = int(time.time() if now is None else now)
    expiry_duration = _resolve_expires_in(
        expires_in=expires_in,
        expires_in_seconds=expires_in_seconds,
    )
    knowledge_object = {
        "v": PROTOCOL_VERSION,
        "ko_id": str(uuid.uuid4()),
        "type": "NODE",
        "origin": origin,
        "subject": subject,
        "created": created,
        "expires": created + expiry_duration,
        "seq": seq,
        "ttl": ttl,
        "payload": payload,
        "signature_algorithm": None,
        "signature": None,
    }
    validate_knowledge_object(knowledge_object, now=created)
    if signing_secret is not None and signer is not None:
        raise KnowledgeObjectError("use either signing_secret or signer, not both")
    if signer is not None:
        sign_knowledge_object_with_signer(knowledge_object, signer)
    elif signing_secret is not None:
        sign_knowledge_object(knowledge_object, signing_secret)
    return knowledge_object


def create_service_knowledge_object(
    *,
    origin: str,
    service_name: str,
    payload: dict[str, Any],
    seq: int = 1,
    ttl: int = 3,
    expires_in: int = 300,
    now: int | None = None,
    signing_secret: str | None = None,
    signer: Signer | None = None,
) -> dict[str, Any]:
    """Create a SERVICE Knowledge Object with a 300-second default expiry."""

    created = int(time.time() if now is None else now)
    if (
        not isinstance(expires_in, int)
        or isinstance(expires_in, bool)
        or expires_in <= 0
    ):
        raise KnowledgeObjectError("expires_in must be a positive integer")
    knowledge_object = {
        "v": PROTOCOL_VERSION,
        "ko_id": str(uuid.uuid4()),
        "type": "SERVICE",
        "origin": origin,
        "subject": service_name,
        "created": created,
        "expires": created + expires_in,
        "seq": seq,
        "ttl": ttl,
        "payload": payload,
        "signature_algorithm": None,
        "signature": None,
    }
    validate_knowledge_object(knowledge_object, now=created)
    if signing_secret is not None and signer is not None:
        raise KnowledgeObjectError("use either signing_secret or signer, not both")
    if signer is not None:
        sign_knowledge_object_with_signer(knowledge_object, signer)
    elif signing_secret is not None:
        sign_knowledge_object(knowledge_object, signing_secret)
    return knowledge_object


def encode_knowledge_object(
    knowledge_object: dict[str, Any],
    *,
    now: int | None = None,
) -> bytes:
    """Validate and encode a Knowledge Object as UTF-8 JSON."""

    validate_knowledge_object(knowledge_object, now=now)
    return json.dumps(
        knowledge_object,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_knowledge_object(encoded: bytes) -> dict[str, Any]:
    """Decode UTF-8 JSON bytes and validate the resulting Knowledge Object."""

    try:
        decoded = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeObjectError(f"malformed JSON: invalid UTF-8: {exc}") from exc

    try:
        value = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise KnowledgeObjectError(f"malformed JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise KnowledgeObjectError("knowledge object must be a JSON object")

    validate_knowledge_object(value)
    return value


encode_message = encode_knowledge_object
decode_message = decode_knowledge_object


def canonicalize_knowledge_object(knowledge_object: dict[str, Any]) -> bytes:
    """Return deterministic JSON bytes for signing, excluding signature."""

    if not isinstance(knowledge_object, dict):
        raise KnowledgeObjectError("knowledge object must be a dictionary")
    canonical_object = {
        key: value
        for key, value in knowledge_object.items()
        if key != "signature"
    }
    try:
        return json.dumps(
            canonical_object,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise KnowledgeObjectError(
            f"knowledge object is not JSON serializable: {exc}"
        ) from exc


def sign_knowledge_object(
    knowledge_object: dict[str, Any],
    signing_secret: str,
) -> dict[str, Any]:
    """Sign a Knowledge Object in place and return it."""

    try:
        signer = HmacSigner(signing_secret)
    except ValueError as exc:
        raise KnowledgeObjectError(str(exc)) from exc
    return sign_knowledge_object_with_signer(knowledge_object, signer)


def sign_knowledge_object_with_signer(
    knowledge_object: dict[str, Any],
    signer: Signer,
) -> dict[str, Any]:
    """Sign a Knowledge Object using an injected signing implementation."""

    if not isinstance(knowledge_object, dict):
        raise KnowledgeObjectError("knowledge object must be a dictionary")
    algorithm = getattr(signer, "algorithm", None)
    if not isinstance(algorithm, str) or not algorithm.strip():
        raise KnowledgeObjectError("signer algorithm must be a non-empty string")
    knowledge_object["signature_algorithm"] = algorithm
    knowledge_object["signature"] = None
    knowledge_object["signature"] = signer.sign(
        canonicalize_knowledge_object(knowledge_object)
    )
    return knowledge_object


def verify_knowledge_object_signature(
    knowledge_object: dict[str, Any],
    signing_secret: str,
) -> bool:
    """Verify an HMAC signature when the origin secret is locally available."""

    try:
        signature = knowledge_object.get("signature")
        if (
            knowledge_object.get("signature_algorithm") != SIGNATURE_ALGORITHM
            or not isinstance(signature, str)
        ):
            return False
        verifier = HmacVerifier(signing_secret)
        return verifier.verify(
            canonicalize_knowledge_object(knowledge_object),
            signature,
        ).verified
    except (KnowledgeObjectError, AttributeError, ValueError):
        return False


def evaluate_signature_status(
    knowledge_object: dict[str, Any],
    *,
    local_node_id: str | None = None,
    local_signing_secret: str | None = None,
) -> SignatureStatus:
    """Classify a KO signature without exchanging origin signing secrets."""

    if not isinstance(knowledge_object, dict):
        return "signature_not_checked"

    algorithm = knowledge_object.get("signature_algorithm")
    signature = knowledge_object.get("signature")
    if algorithm == ED25519_PLANNED:
        return "public_key_planned"
    if algorithm == PUBLIC_KEY_UNSUPPORTED:
        return "public_key_unsupported"
    if isinstance(algorithm, str) and algorithm.startswith("PUBLIC-KEY-"):
        verification = UnsupportedPublicKeyVerifier(algorithm).verify(
            canonicalize_knowledge_object(knowledge_object),
            signature if isinstance(signature, str) else "",
        )
        if verification.status == "missing_key":
            return "public_key_missing"
        return "public_key_unsupported"
    if algorithm not in (None, SIGNATURE_ALGORITHM):
        return "signature_unsupported"
    if signature is None:
        return "unsigned" if algorithm is None else "signature_invalid"
    if algorithm != SIGNATURE_ALGORITHM:
        return "signature_unsupported"

    if knowledge_object.get("origin") == local_node_id:
        if local_signing_secret is None:
            return "signature_not_checked"
        if verify_knowledge_object_signature(
            knowledge_object,
            local_signing_secret,
        ):
            return "signed_self_verified"
        return "signature_invalid"

    return "signed_unverified_remote"


def validate_knowledge_object(
    knowledge_object: dict[str, Any],
    *,
    now: int | None = None,
) -> None:
    """Validate required StreetMesh v1 Knowledge Object fields."""

    if not isinstance(knowledge_object, dict):
        raise KnowledgeObjectError("knowledge object must be a dictionary")

    missing = [field for field in REQUIRED_FIELDS if field not in knowledge_object]
    if missing:
        raise KnowledgeObjectError(
            f"missing required field(s): {', '.join(missing)}"
        )

    if knowledge_object["v"] != PROTOCOL_VERSION:
        raise KnowledgeObjectError(
            f"unsupported protocol version: {knowledge_object['v']!r}"
        )

    if knowledge_object["type"] not in SUPPORTED_TYPES:
        raise KnowledgeObjectError(
            f"unsupported knowledge object type: {knowledge_object['type']!r}"
        )

    _validate_uuid4(knowledge_object["ko_id"])
    _validate_non_empty_string("origin", knowledge_object["origin"])
    _validate_non_empty_string("subject", knowledge_object["subject"])
    created = _validate_epoch_seconds("created", knowledge_object["created"])
    expires = _validate_epoch_seconds("expires", knowledge_object["expires"])
    _validate_non_negative_integer("seq", knowledge_object["seq"])
    _validate_ttl(knowledge_object["ttl"])

    if expires < created:
        raise KnowledgeObjectError("expires must not be earlier than created")

    current_time = int(time.time() if now is None else now)
    if expires <= current_time:
        raise KnowledgeObjectError("knowledge object is expired")

    _validate_signature_fields(knowledge_object)

    if not isinstance(knowledge_object["payload"], dict):
        raise KnowledgeObjectError("payload must be a JSON object")

    if knowledge_object["type"] == "NODE":
        _validate_node_payload(knowledge_object["payload"])
    elif knowledge_object["type"] == "SERVICE":
        _validate_service_payload(
            knowledge_object["payload"],
            origin=knowledge_object["origin"],
            subject=knowledge_object["subject"],
        )


def _validate_uuid4(value: object) -> None:
    if not isinstance(value, str):
        raise KnowledgeObjectError("ko_id must be a UUIDv4 string")

    try:
        parsed = uuid.UUID(value, version=4)
    except ValueError as exc:
        raise KnowledgeObjectError("ko_id must be a UUIDv4 string") from exc

    if str(parsed) != value.lower() or parsed.version != 4:
        raise KnowledgeObjectError("ko_id must be a UUIDv4 string")


def _validate_non_empty_string(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeObjectError(f"{field} must be a non-empty string")


def _validate_epoch_seconds(field: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise KnowledgeObjectError(f"{field} must be Unix epoch seconds")
    if value < 0:
        raise KnowledgeObjectError(f"{field} must be Unix epoch seconds")
    return value


def _validate_non_negative_integer(field: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KnowledgeObjectError(f"{field} must be a non-negative integer")
    return value


def _validate_ttl(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KnowledgeObjectError("ttl must be a non-negative integer")
    return value


def _validate_signature_fields(knowledge_object: dict[str, Any]) -> None:
    algorithm = knowledge_object.get("signature_algorithm")
    signature = knowledge_object["signature"]
    if signature is None:
        if algorithm is not None and (
            not isinstance(algorithm, str) or not algorithm.strip()
        ):
            raise KnowledgeObjectError(
                "signature_algorithm must be null or a non-empty string"
            )
        return

    if not isinstance(algorithm, str) or not algorithm.strip():
        raise KnowledgeObjectError(
            "signature_algorithm must be a non-empty string when signed"
        )
    if not isinstance(signature, str) or not signature:
        raise KnowledgeObjectError("signature must be a non-empty string")
    if algorithm == SIGNATURE_ALGORITHM and (
        len(signature) != 64
        or any(character not in string.hexdigits for character in signature)
    ):
        raise KnowledgeObjectError("signature must be a SHA-256 hexadecimal digest")


def _resolve_expires_in(
    *,
    expires_in: int | None,
    expires_in_seconds: int | None,
) -> int:
    if expires_in is not None and expires_in_seconds is not None:
        raise KnowledgeObjectError(
            "use either expires_in or expires_in_seconds, not both"
        )

    value = 120 if expires_in is None and expires_in_seconds is None else expires_in
    if expires_in_seconds is not None:
        value = expires_in_seconds

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise KnowledgeObjectError("expires_in must be a positive integer")
    return value


def _validate_node_payload(payload: dict[str, Any]) -> None:
    node_name = payload.get("node_name")
    if node_name is not None and (not isinstance(node_name, str) or not node_name.strip()):
        raise KnowledgeObjectError("payload.node_name must be a non-empty string")
    for field_name in (
        "fingerprint",
        "public_key_id",
        "public_key_algorithm",
        "public_key_status",
    ):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, str):
            raise KnowledgeObjectError(f"payload.{field_name} must be text or null")


def _validate_service_payload(
    payload: dict[str, Any],
    *,
    origin: object,
    subject: object,
) -> None:
    allowed = {
        "service_name",
        "provider",
        "capabilities",
        "endpoint",
        "protocol",
        "service_version",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise KnowledgeObjectError(
            f"unknown SERVICE payload field(s): {', '.join(sorted(unknown))}"
        )

    service_name = payload.get("service_name")
    provider = payload.get("provider")
    _validate_non_empty_string("payload.service_name", service_name)
    _validate_non_empty_string("payload.provider", provider)
    if service_name != subject:
        raise KnowledgeObjectError("payload.service_name must match subject")
    if provider != origin:
        raise KnowledgeObjectError("payload.provider must match origin")

    capabilities = payload.get("capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, list) or any(
            not isinstance(value, str) or not value.strip() for value in capabilities
        ):
            raise KnowledgeObjectError(
                "payload.capabilities must be a list of non-empty strings"
            )

    for field in ("endpoint", "protocol", "service_version"):
        value = payload.get(field)
        if value is not None:
            _validate_non_empty_string(f"payload.{field}", value)
