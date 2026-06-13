"""Node identity persistence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import string
import uuid

from .signing import HMAC_SHA256, HmacSigner, Signer


LOGGER = logging.getLogger(__name__)
IDENTITY_VERSION = 2
PUBLIC_KEY_STATUSES = {
    "not_configured",
    "planned",
    "unsupported",
    "active",
    "revoked",
}


@dataclass(frozen=True)
class NodeIdentity:
    """Stable local node identity."""

    node_id: str
    node_name: str
    created: str
    fingerprint: str
    signing_secret: str = field(repr=False)
    identity_version: int = IDENTITY_VERSION
    signing_algorithm: str = HMAC_SHA256
    public_key_id: str | None = None
    public_key_algorithm: str | None = None
    public_key_material: str | None = field(default=None, repr=False)
    public_key_created: str | None = None
    public_key_status: str = "not_configured"

    @classmethod
    def from_json(cls, value: object) -> "NodeIdentity":
        if not isinstance(value, dict):
            raise IdentityError("identity file must contain a JSON object")

        required = ("node_id", "node_name", "created", "fingerprint")
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise IdentityError(f"identity file missing required field(s): {', '.join(missing)}")

        signing_secret = value.get("signing_secret", "")
        if "signing_secret" in value and not _is_signing_secret(signing_secret):
            raise IdentityError("identity signing_secret must be 64 hexadecimal characters")

        identity_version = value.get("identity_version", IDENTITY_VERSION)
        if not isinstance(identity_version, int) or isinstance(identity_version, bool):
            raise IdentityError("identity_version must be an integer")
        signing_algorithm = value.get("signing_algorithm", HMAC_SHA256)
        if not isinstance(signing_algorithm, str) or not signing_algorithm.strip():
            raise IdentityError("signing_algorithm must be a non-empty string")
        public_identity = value.get("public_identity", {})
        if public_identity is None:
            public_identity = {}
        if not isinstance(public_identity, dict):
            raise IdentityError("public_identity must be a JSON object or null")
        public_key_id = public_identity.get(
            "public_key_id",
            value.get("public_key_id"),
        )
        public_key_algorithm = public_identity.get(
            "public_key_algorithm",
            value.get("public_key_algorithm"),
        )
        public_key_material = public_identity.get(
            "public_key_material",
            value.get("public_key_material"),
        )
        public_key_created = public_identity.get(
            "public_key_created",
            value.get("public_key_created"),
        )
        public_key_status = public_identity.get(
            "public_key_status",
            value.get("public_key_status", "not_configured"),
        )
        for field_name, field_value in (
            ("public_key_id", public_key_id),
            ("public_key_algorithm", public_key_algorithm),
            ("public_key_material", public_key_material),
            ("public_key_created", public_key_created),
        ):
            if field_value is not None and not isinstance(field_value, str):
                raise IdentityError(f"{field_name} must be text or null")
        if public_key_status not in PUBLIC_KEY_STATUSES:
            raise IdentityError(f"invalid public_key_status: {public_key_status!r}")

        return cls(
            node_id=str(value["node_id"]),
            node_name=str(value["node_name"]),
            created=str(value["created"]),
            fingerprint=str(value["fingerprint"]),
            signing_secret=signing_secret,
            identity_version=identity_version,
            signing_algorithm=signing_algorithm,
            public_key_id=public_key_id,
            public_key_algorithm=public_key_algorithm,
            public_key_material=public_key_material,
            public_key_created=public_key_created,
            public_key_status=public_key_status,
        )

    @property
    def public_identity(self) -> dict[str, str | None]:
        return {
            "public_key_id": self.public_key_id,
            "public_key_algorithm": self.public_key_algorithm,
            "public_key_material": self.public_key_material,
            "public_key_created": self.public_key_created,
            "public_key_status": self.public_key_status,
        }

    def public_identity_payload(self) -> dict[str, str | None]:
        """Return safe public identity fields for NODE announcements."""

        return {
            "public_key_id": self.public_key_id,
            "public_key_algorithm": self.public_key_algorithm,
            "public_key_status": self.public_key_status,
        }

    def create_signer(self) -> Signer:
        """Create the signer selected by this persistent identity."""

        if self.signing_algorithm != HMAC_SHA256:
            raise IdentityError(
                f"unsupported local signing algorithm: {self.signing_algorithm}"
            )
        return HmacSigner(self.signing_secret)

    def to_json(self) -> dict[str, object]:
        return {
            "identity_version": self.identity_version,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "created": self.created,
            "fingerprint": self.fingerprint,
            "signing_secret": self.signing_secret,
            "signing_algorithm": self.signing_algorithm,
            "public_identity": self.public_identity,
        }


class IdentityError(ValueError):
    """Raised when local identity cannot be loaded or created."""


def load_or_create_identity(data_dir: Path, node_name: str) -> NodeIdentity:
    """Load identity from data_dir, creating it when missing."""

    identity_path = data_dir / "identity.json"
    if identity_path.exists():
        needs_metadata_upgrade = _needs_metadata_upgrade(identity_path)
        identity = load_identity(identity_path)
        if not identity.signing_secret:
            identity = replace(identity, signing_secret=_create_signing_secret())
            needs_metadata_upgrade = True
        if needs_metadata_upgrade:
            save_identity(identity_path, identity)
            LOGGER.info("Identity upgraded: %s", identity_path)
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
        signing_secret=_create_signing_secret(),
        identity_version=IDENTITY_VERSION,
        signing_algorithm=HMAC_SHA256,
    )


def _fingerprint(*, node_id: str, node_name: str, created: str) -> str:
    digest = hashlib.sha256()
    digest.update(node_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(node_name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(created.encode("utf-8"))
    return digest.hexdigest()


def _create_signing_secret() -> str:
    return secrets.token_hex(32)


def _is_signing_secret(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in string.hexdigits for character in value)
    )


def _needs_metadata_upgrade(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as identity_file:
            value = json.load(identity_file)
    except (json.JSONDecodeError, OSError):
        return False
    return not (
        isinstance(value, dict)
        and value.get("identity_version") == IDENTITY_VERSION
        and isinstance(value.get("signing_algorithm"), str)
        and bool(value.get("signing_algorithm"))
        and isinstance(value.get("public_identity"), dict)
    )
