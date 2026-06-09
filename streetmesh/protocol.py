"""StreetMesh Knowledge Object protocol primitives."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

PROTOCOL_NAME = "streetmesh"
PROTOCOL_VERSION = 1
SUPPORTED_TYPES = {"NODE"}
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
) -> dict[str, Any]:
    """Create a NODE Knowledge Object.

    TTL is a gossip hop count. Expiry is controlled separately by expires_in or
    expires_in_seconds, defaulting to 120 seconds for NODE objects.

    Signatures are intentionally left as null in v0.1 Milestone 2.
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
        "signature": None,
    }
    validate_knowledge_object(knowledge_object, now=created)
    return knowledge_object


def encode_knowledge_object(knowledge_object: dict[str, Any]) -> bytes:
    """Validate and encode a Knowledge Object as UTF-8 JSON."""

    validate_knowledge_object(knowledge_object)
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
    ttl = _validate_ttl(knowledge_object["ttl"])

    if expires < created:
        raise KnowledgeObjectError("expires must not be earlier than created")

    current_time = int(time.time() if now is None else now)
    if expires <= current_time:
        raise KnowledgeObjectError("knowledge object is expired")

    if knowledge_object["signature"] is not None:
        raise KnowledgeObjectError("signature must be null")

    if not isinstance(knowledge_object["payload"], dict):
        raise KnowledgeObjectError("payload must be a JSON object")

    if knowledge_object["type"] == "NODE":
        _validate_node_payload(knowledge_object["payload"])


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
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise KnowledgeObjectError("ttl must be a positive integer")
    return value


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
