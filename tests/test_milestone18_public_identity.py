"""Regression tests for Milestone 18 public-key-ready identity metadata."""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import hmac
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.cli import main
from streetmesh.config import NodeConfig, StreetMeshConfig
from streetmesh.daemon import StreetMeshDaemon
from streetmesh.directory import AwarenessStore
from streetmesh.identity import (
    IDENTITY_VERSION,
    create_identity,
    load_or_create_identity,
    save_identity,
)
from streetmesh.protocol import (
    canonicalize_knowledge_object,
    create_node_knowledge_object,
    evaluate_signature_status,
)
from streetmesh.signing import (
    ED25519_PLANNED,
    HMAC_SHA256,
    PUBLIC_KEY_UNSUPPORTED,
)
from streetmesh.trust import TrustStore


class RecordingTransport:
    def __init__(self) -> None:
        self.broadcasts: list[bytes] = []

    def send_broadcast(
        self,
        data: bytes,
        *,
        port: int,
        host: str | None = None,
    ) -> int:
        del port, host
        self.broadcasts.append(data)
        return len(data)

    def receive(self, *, timeout: float | None = None) -> None:
        del timeout
        return None

    def close(self) -> None:
        pass


class PublicIdentityTests(unittest.TestCase):
    def test_new_identity_has_versioned_signing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            identity = load_or_create_identity(data_dir, "node@local@mesh")
            persisted = json.loads(
                (data_dir / "identity.json").read_text(encoding="utf-8")
            )

        self.assertEqual(identity.identity_version, IDENTITY_VERSION)
        self.assertEqual(identity.signing_algorithm, HMAC_SHA256)
        self.assertEqual(identity.public_key_status, "not_configured")
        self.assertIsNone(identity.public_key_material)
        self.assertEqual(persisted["identity_version"], IDENTITY_VERSION)
        self.assertEqual(persisted["signing_algorithm"], HMAC_SHA256)
        self.assertEqual(
            persisted["public_identity"]["public_key_status"],
            "not_configured",
        )

    def test_existing_identity_upgrade_preserves_id_name_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            identity_path = data_dir / "identity.json"
            secret = "a" * 64
            legacy = {
                "node_id": "legacy-node-id",
                "node_name": "legacy@local@mesh",
                "created": "2026-06-09T00:00:00+00:00",
                "fingerprint": "f" * 64,
                "signing_secret": secret,
            }
            identity_path.write_text(json.dumps(legacy), encoding="utf-8")

            identity = load_or_create_identity(data_dir, "changed@local@mesh")
            persisted = json.loads(identity_path.read_text(encoding="utf-8"))

        self.assertEqual(identity.node_id, legacy["node_id"])
        self.assertEqual(identity.node_name, legacy["node_name"])
        self.assertEqual(identity.signing_secret, secret)
        self.assertEqual(persisted["signing_secret"], secret)
        self.assertEqual(persisted["identity_version"], IDENTITY_VERSION)
        self.assertIn("public_identity", persisted)

    def test_node_announcement_contains_only_safe_public_identity_metadata(self) -> None:
        identity = replace(
            create_identity("node@local@mesh"),
            public_key_id="future-key-1",
            public_key_algorithm="ED25519",
            public_key_material="public-material-not-advertised",
            public_key_status="planned",
        )
        daemon = StreetMeshDaemon(_config(Path("data")))
        announcement = daemon.announce_once(identity, RecordingTransport())
        payload = announcement["payload"]

        self.assertEqual(payload["fingerprint"], identity.fingerprint)
        self.assertEqual(payload["public_key_id"], "future-key-1")
        self.assertEqual(payload["public_key_algorithm"], "ED25519")
        self.assertEqual(payload["public_key_status"], "planned")
        self.assertNotIn("signing_secret", payload)
        self.assertNotIn("public_key_material", payload)
        self.assertNotIn(identity.signing_secret, json.dumps(announcement))

    def test_public_identity_awareness_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "awareness.json"
            store = AwarenessStore(path=path)
            ko = create_node_knowledge_object(
                origin="remote-node",
                subject="remote@local@mesh",
                payload={
                    "node_id": "remote-node",
                    "node_name": "remote@local@mesh",
                    "fingerprint": "f" * 64,
                    "public_key_id": "future-key-1",
                    "public_key_algorithm": "ED25519",
                    "public_key_status": "planned",
                },
            )
            store.update_from_knowledge_object(ko)
            store.save()

            loaded = AwarenessStore.load(path)
            entry = loaded.get_by_node_id("remote-node")

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.public_key_id, "future-key-1")
        self.assertEqual(entry.public_key_algorithm, "ED25519")
        self.assertEqual(entry.public_key_status, "planned")


class SigningCompatibilityTests(unittest.TestCase):
    def test_hmac_signer_matches_existing_hmac_sha256_model(self) -> None:
        secret = "a" * 64
        identity = replace(create_identity("node@local@mesh"), signing_secret=secret)
        ko = create_node_knowledge_object(
            origin=identity.node_id,
            subject=identity.node_name,
            payload={"node_name": identity.node_name},
            signer=identity.create_signer(),
            now=1_700_000_000,
        )
        expected = hmac.new(
            bytes.fromhex(secret),
            canonicalize_knowledge_object(ko),
            hashlib.sha256,
        ).hexdigest()

        self.assertEqual(ko["signature_algorithm"], HMAC_SHA256)
        self.assertEqual(ko["signature"], expected)
        self.assertEqual(
            evaluate_signature_status(
                ko,
                local_node_id=identity.node_id,
                local_signing_secret=secret,
            ),
            "signed_self_verified",
        )

    def test_remote_hmac_status_remains_unverified(self) -> None:
        ko = create_node_knowledge_object(
            origin="remote-node",
            subject="remote@local@mesh",
            payload={"node_name": "remote@local@mesh"},
            signing_secret="b" * 64,
        )

        self.assertEqual(
            evaluate_signature_status(
                ko,
                local_node_id="local-node",
                local_signing_secret="a" * 64,
            ),
            "signed_unverified_remote",
        )

    def test_public_key_algorithms_are_never_falsely_verified(self) -> None:
        ko = create_node_knowledge_object(
            origin="remote-node",
            subject="remote@local@mesh",
            payload={"node_name": "remote@local@mesh"},
        )

        ko["signature_algorithm"] = PUBLIC_KEY_UNSUPPORTED
        self.assertEqual(
            evaluate_signature_status(ko),
            "public_key_unsupported",
        )
        ko["signature_algorithm"] = ED25519_PLANNED
        self.assertEqual(evaluate_signature_status(ko), "public_key_planned")
        ko["signature_algorithm"] = "PUBLIC-KEY-ED25519"
        self.assertEqual(evaluate_signature_status(ko), "public_key_missing")


class TrustAndInspectionCompatibilityTests(unittest.TestCase):
    def test_trust_binding_preserves_public_key_id(self) -> None:
        store = TrustStore()
        entry = store.bind_name(
            "node-id",
            "node@local@mesh",
            "trusted",
            fingerprint="f" * 64,
            public_key_id="future-key-1",
            now=1_000,
        )

        self.assertEqual(entry.public_key_id, "future-key-1")
        self.assertEqual(store.get_by_name("node@local@mesh"), entry)

    def test_old_trust_file_loads_without_public_key_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"
            path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "node_id": "node-id",
                                "state": "trusted",
                                "node_name": "node@local@mesh",
                                "fingerprint": "f" * 64,
                                "binding_status": "bound",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            entry = TrustStore.load(path).get_entry("node-id")

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIsNone(entry.public_key_id)
        self.assertEqual(entry.binding_status, "bound")

    def test_status_shows_model_but_never_signing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            identity = create_identity("node@local@mesh")
            save_identity(data_dir / "identity.json", identity)
            rendered = StringIO()
            with redirect_stdout(rendered):
                self.assertEqual(
                    main(["--data-dir", str(data_dir), "--status"]),
                    0,
                )
            output = rendered.getvalue()

        self.assertIn("signing algorithm", output)
        self.assertIn(HMAC_SHA256, output)
        self.assertIn("public key status", output)
        self.assertIn("not_configured", output)
        self.assertNotIn("signing_secret", output)
        self.assertNotIn(identity.signing_secret, output)


def _config(data_dir: Path) -> StreetMeshConfig:
    return StreetMeshConfig(
        path=None,
        node=NodeConfig(
            node_name="local@mesh",
            data_dir=data_dir,
            announce_interval=30,
            udp_port=40404,
            bind_host="127.0.0.1",
            broadcast_host="127.0.0.1",
        ),
    )


if __name__ == "__main__":
    unittest.main()
