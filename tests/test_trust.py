"""Tests for the persistent StreetMesh Trust Store."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.trust import TRUST_STATES, TrustStore


class TrustStoreTests(unittest.TestCase):
    def test_defaults_unknown_for_unlisted_node(self) -> None:
        store = TrustStore()

        self.assertEqual(store.get_state("new-node"), "unknown")

    def test_adds_and_looks_up_trusted_node(self) -> None:
        store = TrustStore()

        store.add_trusted("trusted-node")

        self.assertEqual(store.get_state("trusted-node"), "trusted")

    def test_persists_trusted_and_blocked_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"
            store = TrustStore.load(path)
            store.add_trusted("trusted-node")
            store.add_blocked("blocked-node")

            loaded = TrustStore.load(path)

            self.assertEqual(loaded.get_state("trusted-node"), "trusted")
            self.assertEqual(loaded.get_state("blocked-node"), "blocked")

    def test_creates_default_store_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"

            TrustStore.load(path)

            self.assertTrue(path.exists())

    def test_read_only_load_does_not_create_missing_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"

            store = TrustStore.load(path, create_if_missing=False)

            self.assertEqual(store.list_entries(), [])
            self.assertFalse(path.exists())

    def test_supports_all_declared_trust_states(self) -> None:
        store = TrustStore()

        for state in TRUST_STATES:
            store.set_state(f"node-{state}", state)

        self.assertEqual(
            {entry.state for entry in store.list_entries()},
            set(TRUST_STATES),
        )


if __name__ == "__main__":
    unittest.main()
