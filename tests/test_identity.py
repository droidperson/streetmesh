"""Tests for StreetMesh identity persistence."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.identity import IdentityError, load_identity, load_or_create_identity


class IdentityTests(unittest.TestCase):
    def test_creates_identity_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            with self.assertLogs("streetmesh.identity", level="INFO") as logs:
                identity = load_or_create_identity(data_dir, "node01@local@mesh")

            self.assertTrue((data_dir / "identity.json").exists())
            self.assertEqual(identity.node_name, "node01@local@mesh")
            self.assertTrue(identity.node_id)
            self.assertTrue(identity.created)
            self.assertEqual(len(identity.fingerprint), 64)
            self.assertEqual(len(identity.signing_secret), 64)
            persisted = json.loads((data_dir / "identity.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["signing_secret"], identity.signing_secret)
            self.assertIn("Identity created:", logs.output[0])

    def test_upgrades_existing_identity_with_signing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            identity_path = data_dir / "identity.json"
            legacy_identity = {
                "node_id": "550e8400-e29b-41d4-a716-446655440000",
                "node_name": "node01@local@mesh",
                "created": "2026-06-09T00:00:00+00:00",
                "fingerprint": "f" * 64,
            }
            identity_path.write_text(json.dumps(legacy_identity), encoding="utf-8")

            with self.assertLogs("streetmesh.identity", level="INFO") as logs:
                identity = load_or_create_identity(data_dir, "changed@local@mesh")

            self.assertEqual(identity.node_id, legacy_identity["node_id"])
            self.assertEqual(identity.node_name, legacy_identity["node_name"])
            self.assertEqual(len(identity.signing_secret), 64)
            persisted = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["node_id"], legacy_identity["node_id"])
            self.assertEqual(persisted["node_name"], legacy_identity["node_name"])
            self.assertEqual(persisted["signing_secret"], identity.signing_secret)
            self.assertTrue(any("Identity upgraded" in line for line in logs.output))

    def test_loads_existing_identity_stably(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            first = load_or_create_identity(data_dir, "node01@local@mesh")
            with self.assertLogs("streetmesh.identity", level="INFO") as logs:
                second = load_or_create_identity(data_dir, "changed@local@mesh")

            self.assertEqual(first, second)
            self.assertEqual(first.node_id, second.node_id)
            self.assertEqual(second.node_name, "node01@local@mesh")
            self.assertIn("Identity loaded:", logs.output[0])

    def test_invalid_identity_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "identity.json"
            identity_path.write_text(json.dumps({"node_id": "abc"}), encoding="utf-8")

            with self.assertRaises(IdentityError):
                load_identity(identity_path)


if __name__ == "__main__":
    unittest.main()
