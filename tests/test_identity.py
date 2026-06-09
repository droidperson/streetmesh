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
            self.assertIn("Identity created:", logs.output[0])

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
