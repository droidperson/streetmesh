"""Tests for quarantined claim persistence."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.protocol import create_node_knowledge_object
from streetmesh.quarantine import QuarantineStore


class QuarantineStoreTests(unittest.TestCase):
    def test_persists_quarantined_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quarantine.json"
            claim = create_node_knowledge_object(
                origin="gateway-node",
                subject="gateway",
                payload={},
                now=1_000,
            )
            claim["type"] = "GATEWAY"
            store = QuarantineStore(path)
            store.add(
                claim,
                trust_state="unknown",
                reason="review-required-gateway",
                now=1_001,
            )

            loaded = QuarantineStore.load(path)

            self.assertEqual(len(loaded.list_claims()), 1)
            self.assertEqual(loaded.list_claims()[0]["type"], "GATEWAY")


if __name__ == "__main__":
    unittest.main()
