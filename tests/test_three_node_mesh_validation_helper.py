"""Tests for the Milestone 13 three-node artifact verifier."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.three_node_mesh_validation import VerificationError, verify_artifacts


class ThreeNodeMeshValidationHelperTests(unittest.TestCase):
    def test_verifies_complete_three_node_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_artifacts(Path(temp_dir))

            messages = verify_artifacts(**paths)

            self.assertIn("all nodes finished with three-node awareness", messages)
            self.assertIn(
                "both laptop observers logged Pi expiry followed by re-discovery",
                messages,
            )

    def test_rejects_missing_pi_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_artifacts(root)
            awareness_path = paths["test_data"] / "awareness.json"
            awareness = json.loads(awareness_path.read_text(encoding="utf-8"))
            awareness["services"] = []
            self._write_json(awareness_path, awareness)

            with self.assertRaisesRegex(VerificationError, "missing 'temperature'"):
                verify_artifacts(**paths)

    def test_rejects_missing_rediscovery_after_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_artifacts(root)
            log_path = paths["laptop_log"]
            log = log_path.read_text(encoding="utf-8")
            expiry = "NODE_EXPIRED node_name=pi01@local@mesh node_id=pi-id"
            log_path.write_text(log[: log.index(expiry) + len(expiry)], encoding="utf-8")

            with self.assertRaisesRegex(VerificationError, "expiry/re-discovery"):
                verify_artifacts(**paths)

    def _write_artifacts(self, root: Path) -> dict[str, Path]:
        identities = {
            "laptop": ("laptop-id", "laptop@local@mesh"),
            "pi": ("pi-id", "pi01@local@mesh"),
            "test": ("test-id", "laptop-test@local@mesh"),
        }
        for key, (node_id, node_name) in identities.items():
            data_dir = root / key / "data"
            data_dir.mkdir(parents=True)
            self._write_json(
                data_dir / "identity.json",
                {"node_id": node_id, "node_name": node_name},
            )
            self._write_json(
                data_dir / "awareness.json",
                {
                    "nodes": [
                        {"node_id": known_id, "node_name": known_name}
                        for known_id, known_name in identities.values()
                    ],
                    "services": [
                        {
                            "service_name": "temperature",
                            "provider": "pi-id",
                            "trust_state": "trusted" if key == "laptop" else "unknown",
                            "accepted_limited": False if key == "laptop" else True,
                        }
                    ],
                },
            )
        self._write_json(
            root / "laptop" / "data" / "trust.json",
            {"nodes": [{"node_id": "pi-id", "state": "trusted"}]},
        )

        laptop_log = (
            "Node discovered: node_name=pi01@local@mesh node_id=pi-id seq=1\n"
            "Node discovered: node_name=laptop-test@local@mesh node_id=test-id seq=1\n"
            "SERVICE discovered: service_name=temperature provider=pi-id seq=1\n"
            "Gossip forwarded: ko_id=service-ko origin=pi-id ttl=3 forwarded_ttl=2\n"
            "Duplicate Knowledge Object suppressed: ko_id=service-ko\n"
            "NODE_EXPIRED node_name=pi01@local@mesh node_id=pi-id expires=100\n"
            "Node discovered: node_name=pi01@local@mesh node_id=pi-id seq=1\n"
            "Policy accepted: type=SERVICE origin=pi-id trust_state=trusted reason=service-trusted ko_id=service-ko-2\n"
        )
        pi_log = (
            "Node discovered: node_name=laptop@local@mesh node_id=laptop-id seq=1\n"
            "Node discovered: node_name=laptop-test@local@mesh node_id=test-id seq=1\n"
        )
        test_log = (
            "Node discovered: node_name=laptop@local@mesh node_id=laptop-id seq=1\n"
            "Node discovered: node_name=pi01@local@mesh node_id=pi-id seq=1\n"
            "SERVICE discovered: service_name=temperature provider=pi-id seq=1\n"
            "NODE_EXPIRED node_name=pi01@local@mesh node_id=pi-id expires=100\n"
            "Node discovered: node_name=pi01@local@mesh node_id=pi-id seq=1\n"
        )
        log_paths = {}
        for key, contents in (
            ("laptop", laptop_log),
            ("pi", pi_log),
            ("test", test_log),
        ):
            path = root / key / "streetmesh.log"
            path.write_text(contents, encoding="utf-8")
            log_paths[key] = path

        return {
            "laptop_data": root / "laptop" / "data",
            "pi_data": root / "pi" / "data",
            "test_data": root / "test" / "data",
            "laptop_log": log_paths["laptop"],
            "pi_log": log_paths["pi"],
            "test_log": log_paths["test"],
        }

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
