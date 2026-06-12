"""StreetMesh Knowledge Object protocol primitives."""

from __future__ import annotations

import hashlib
import hmac
import json
import string
import time
import uuid
from typing import Any

PROTOCOL_NAME = "streetmesh"
PROTOCOL_VERSION = 1
SIGNATURE_ALGORITHM = "HMAC-SHA256"
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
    if signing_secret is not None:
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
    if signing_secret is not None:
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

    if not isinstance(knowledge_object, dict):
        raise KnowledgeObjectError("knowledge object must be a dictionary")
    secret = _decode_signing_secret(signing_secret)
    knowledge_object["signature_algorithm"] = SIGNATURE_ALGORITHM
    knowledge_object["signature"] = None
    knowledge_object["signature"] = hmac.new(
        secret,
        canonicalize_knowledge_object(knowledge_object),
        hashlib.sha256,
    ).hexdigest()
    return knowledge_object


def verify_knowledge_object_signature(
    knowledge_object: dict[str, Any],
    signing_secret: str,
) -> bool:
    """Verify an HMAC signature when the origin secret is locally available."""

    try:
        secret = _decode_signing_secret(signing_secret)
        signature = knowledge_object.get("signature")
        if (
            knowledge_object.get("signature_algorithm") != SIGNATURE_ALGORITHM
            or not isinstance(signature, str)
        ):
            return False
        expected = hmac.new(
            secret,
            canonicalize_knowledge_object(knowledge_object),
            hashlib.sha256,
        ).hexdigest()
    except (KnowledgeObjectError, AttributeError):
        return False
    return hmac.compare_digest(signature, expected)


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
        if algorithm is not None:
            raise KnowledgeObjectError(
                "signature_algorithm must be null when signature is null"
            )
        return

    if algorithm != SIGNATURE_ALGORITHM:
        raise KnowledgeObjectError(
            f"unsupported signature algorithm: {algorithm!r}"
        )
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(character not in string.hexdigits for character in signature)
    ):
        raise KnowledgeObjectError("signature must be a SHA-256 hexadecimal digest")


def _decode_signing_secret(signing_secret: object) -> bytes:
    if (
        not isinstance(signing_secret, str)
        or len(signing_secret) != 64
        or any(character not in string.hexdigits for character in signing_secret)
    ):
        raise KnowledgeObjectError(
            "signing_secret must be 64 hexadecimal characters"
        )
    return bytes.fromhex(signing_secret)


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
