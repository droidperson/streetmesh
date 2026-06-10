"""Tests for the Milestone 7 artifact verifier."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.two_node_discovery import VerificationError, verify_artifacts


class TwoNodeDiscoveryHelperTests(unittest.TestCase):
    def test_verifies_bidirectional_discovery_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_artifacts(root)

            messages = verify_artifacts(**paths)

            self.assertIn("Node A discovered Node B", messages)
            self.assertIn("Node B logged NODE_EXPIRED for Node A", messages)

    def test_rejects_missing_expiry_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_artifacts(root)
            paths["node_b_log"].write_text(
                "Node discovered: node_name=node-a@local@mesh node_id=node-a-id\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(VerificationError, "NODE_EXPIRED"):
                verify_artifacts(**paths)

    def _write_artifacts(self, root: Path) -> dict[str, Path]:
        node_a_data = root / "node-a"
        node_b_data = root / "node-b"
        node_a_data.mkdir()
        node_b_data.mkdir()
        self._write_json(
            node_a_data / "identity.json",
            {"node_id": "node-a-id", "node_name": "node-a@local@mesh"},
        )
        self._write_json(
            node_b_data / "identity.json",
            {"node_id": "node-b-id", "node_name": "node-b@local@mesh"},
        )
        self._write_json(
            node_b_data / "awareness.json",
            {"nodes": [{"node_id": "node-b-id"}]},
        )
        node_a_log = root / "node-a.log"
        node_b_log = root / "node-b.log"
        node_a_log.write_text(
            "Node discovered: node_name=node-b@local@mesh node_id=node-b-id seq=1\n",
            encoding="utf-8",
        )
        node_b_log.write_text(
            "Node discovered: node_name=node-a@local@mesh node_id=node-a-id seq=2\n"
            "NODE_EXPIRED node_name=node-a@local@mesh node_id=node-a-id expires=100\n",
            encoding="utf-8",
        )
        return {
            "node_a_data": node_a_data,
            "node_b_data": node_b_data,
            "node_a_log": node_a_log,
            "node_b_log": node_b_log,
        }

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
