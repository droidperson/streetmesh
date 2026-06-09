"""Node identity persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import uuid


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeIdentity:
    """Stable local node identity."""

    node_id: str
    node_name: str
    created: str
    fingerprint: str

    @classmethod
    def from_json(cls, value: object) -> "NodeIdentity":
        if not isinstance(value, dict):
            raise IdentityError("identity file must contain a JSON object")

        required = ("node_id", "node_name", "created", "fingerprint")
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise IdentityError(f"identity file missing required field(s): {', '.join(missing)}")

        return cls(
            node_id=str(value["node_id"]),
            node_name=str(value["node_name"]),
            created=str(value["created"]),
            fingerprint=str(value["fingerprint"]),
        )

    def to_json(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "created": self.created,
            "fingerprint": self.fingerprint,
        }


class IdentityError(ValueError):
    """Raised when local identity cannot be loaded or created."""


def load_or_create_identity(data_dir: Path, node_name: str) -> NodeIdentity:
    """Load identity from data_dir, creating it when missing."""

    identity_path = data_dir / "identity.json"
    if identity_path.exists():
        identity = load_identity(identity_path)
        LOGGER.info("Identity loaded: %s", identity_path)
        return identity

    identity = create_identity(node_name=node_name)
    save_identity(identity_path, identity)
    LOGGER.info("Identity created: %s", identity_path)
    return identity


def load_identity(path: Path) -> NodeIdentity:
    try:
        with path.open("r", encoding="utf-8") as identity_file:
            return NodeIdentity.from_json(json.load(identity_file))
    except json.JSONDecodeError as exc:
        raise IdentityError(f"invalid JSON in identity file: {exc}") from exc
    except OSError as exc:
        raise IdentityError(f"could not read identity file: {exc}") from exc


def save_identity(path: Path, identity: NodeIdentity) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as identity_file:
            json.dump(identity.to_json(), identity_file, indent=2, sort_keys=True)
            identity_file.write("\n")
    except OSError as exc:
        raise IdentityError(f"could not write identity file: {exc}") from exc


def create_identity(node_name: str) -> NodeIdentity:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    node_id = str(uuid.uuid4())
    fingerprint = _fingerprint(node_id=node_id, node_name=node_name, created=created)
    return NodeIdentity(
        node_id=node_id,
        node_name=node_name,
        created=created,
        fingerprint=fingerprint,
    )


def _fingerprint(*, node_id: str, node_name: str, created: str) -> str:
    digest = hashlib.sha256()
    digest.update(node_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(node_name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(created.encode("utf-8"))
    return digest.hexdigest()
