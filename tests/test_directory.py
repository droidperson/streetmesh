"""Tests for the StreetMesh Awareness Store."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.directory import AwarenessStore
from streetmesh.protocol import create_node_knowledge_object


class AwarenessStoreTests(unittest.TestCase):
    def test_stores_and_looks_up_known_nodes(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        ko = self._node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )

        update = store.update_from_knowledge_object(ko, now=1_001)

        self.assertEqual(update.status, "discovered")
        by_id = store.get_by_node_id("remote-node-id")
        by_name = store.get_by_node_name("remote@local@mesh")
        self.assertIsNotNone(by_id)
        self.assertIs(by_id, by_name)
        assert by_id is not None
        self.assertEqual(by_id.node_id, "remote-node-id")
        self.assertEqual(by_id.node_name, "remote@local@mesh")
        self.assertEqual(by_id.first_seen, 1_001)
        self.assertEqual(by_id.last_seen, 1_001)
        self.assertEqual(by_id.expires, ko["expires"])
        self.assertFalse(by_id.is_local)
        self.assertEqual(store.list_nodes(), [by_id])

    def test_distinguishes_local_node(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        ko = self._node_ko(
            node_id="local-node-id",
            node_name="node01@local@mesh",
            seq=1,
            now=1_000,
        )

        store.update_from_knowledge_object(ko, now=1_001)

        entry = store.get_by_node_id("local-node-id")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertTrue(entry.is_local)

    def test_refreshes_existing_entry_when_newer_node_ko_arrives(self) -> None:
        store = AwarenessStore()
        first = self._node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )
        second = self._node_ko(
            node_id="remote-node-id",
            node_name="remote-renamed@local@mesh",
            seq=2,
            now=1_010,
        )

        store.update_from_knowledge_object(first, now=1_001)
        update = store.update_from_knowledge_object(second, now=1_011)

        entry = store.get_by_node_id("remote-node-id")
        self.assertEqual(update.status, "refreshed")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.first_seen, 1_001)
        self.assertEqual(entry.last_seen, 1_011)
        self.assertEqual(entry.node_name, "remote-renamed@local@mesh")
        self.assertEqual(entry.seq, 2)
        self.assertIsNone(store.get_by_node_name("remote@local@mesh"))
        self.assertIs(entry, store.get_by_node_name("remote-renamed@local@mesh"))

    def test_ignores_older_node_ko(self) -> None:
        store = AwarenessStore()
        newer = self._node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=2,
            now=1_000,
        )
        older = self._node_ko(
            node_id="remote-node-id",
            node_name="stale@local@mesh",
            seq=1,
            now=1_010,
        )

        store.update_from_knowledge_object(newer, now=1_001)
        update = store.update_from_knowledge_object(older, now=1_011)

        entry = store.get_by_node_id("remote-node-id")
        self.assertEqual(update.status, "ignored")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.node_name, "remote@local@mesh")
        self.assertEqual(entry.last_seen, 1_001)

    def test_ignores_malformed_node_data(self) -> None:
        store = AwarenessStore()
        ko = self._node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )
        ko["payload"]["node_id"] = "different-node-id"

        update = store.update_from_knowledge_object(ko, now=1_001)

        self.assertEqual(update.status, "ignored")
        self.assertEqual(store.list_nodes(), [])

    def test_persists_directory_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "awareness.json"
            store = AwarenessStore(path=path)
            ko = self._node_ko(
                node_id="remote-node-id",
                node_name="remote@local@mesh",
                seq=1,
                now=1_000,
            )
            store.update_from_knowledge_object(ko, now=1_001)
            store.save()

            loaded = AwarenessStore.load(path)

            entry = loaded.get_by_node_id("remote-node-id")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.node_name, "remote@local@mesh")
            self.assertEqual(entry.first_seen, 1_001)

    def _node_ko(
        self,
        *,
        node_id: str,
        node_name: str,
        seq: int,
        now: int,
    ) -> dict[str, object]:
        return create_node_knowledge_object(
            origin=node_id,
            subject=node_name,
            payload={
                "node_id": node_id,
                "node_name": node_name,
                "fingerprint": "f" * 64,
            },
            seq=seq,
            now=now,
        )


if __name__ == "__main__":
    unittest.main()
