"""Tests for the StreetMesh Awareness Store."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.directory import AwarenessStore, DuplicateCache
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
)


class AwarenessStoreTests(unittest.TestCase):
    def test_stores_and_looks_up_known_nodes(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        ko = _node_ko(
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
        ko = _node_ko(
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
        first = _node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )
        second = _node_ko(
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
        newer = _node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=2,
            now=1_000,
        )
        older = _node_ko(
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
        ko = _node_ko(
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
            ko = _node_ko(
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

    def test_ignores_expired_node_knowledge_object(self) -> None:
        store = AwarenessStore()
        ko = _node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )

        update = store.update_from_knowledge_object(ko, now=1_121)

        self.assertEqual(update.status, "ignored")
        self.assertEqual(store.list_nodes(), [])

    def test_expires_stale_remote_nodes(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        remote = _node_ko(
            node_id="remote-node-id",
            node_name="remote@local@mesh",
            seq=1,
            now=1_000,
        )
        local = _node_ko(
            node_id="local-node-id",
            node_name="node01@local@mesh",
            seq=1,
            now=1_000,
        )
        store.update_from_knowledge_object(remote, now=1_001)
        store.update_from_knowledge_object(local, now=1_001)

        with self.assertLogs("streetmesh.directory", level="INFO") as logs:
            expired = store.expire_stale(now=1_121)

        self.assertEqual([entry.node_id for entry in expired], ["remote-node-id"])
        self.assertIsNone(store.get_by_node_id("remote-node-id"))
        self.assertIsNotNone(store.get_by_node_id("local-node-id"))
        self.assertEqual(
            [entry.node_id for entry in store.list_nodes(now=1_121)],
            ["local-node-id"],
        )
        self.assertIn("NODE_EXPIRED", logs.output[0])

    def test_stores_refreshes_and_looks_up_services(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        store.update_from_knowledge_object(
            _node_ko(
                node_id="provider-id",
                node_name="provider@local@mesh",
                seq=1,
                now=1_000,
            ),
            now=1_001,
        )
        first = _service_ko(seq=1, now=1_000)
        second = _service_ko(seq=2, now=1_010, endpoint="/temperature/v2")

        discovered = store.update_from_knowledge_object(first, now=1_001)
        refreshed = store.update_from_knowledge_object(second, now=1_011)

        entry = store.get_service("provider-id", "temperature")
        self.assertEqual(discovered.status, "discovered")
        self.assertEqual(refreshed.status, "refreshed")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.provider_name, "provider@local@mesh")
        self.assertEqual(entry.endpoint, "/temperature/v2")
        self.assertEqual(entry.seq, 2)
        self.assertEqual(store.list_services(service_name="temperature"), [entry])

    def test_persists_service_awareness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "awareness.json"
            store = AwarenessStore(path=path)
            store.update_from_knowledge_object(_service_ko(seq=1, now=1_000), now=1_001)
            store.save()

            loaded = AwarenessStore.load(path)

            entry = loaded.get_service("provider-id", "temperature")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.capabilities, ["humidity"])

    def test_expires_stale_remote_services(self) -> None:
        store = AwarenessStore(local_node_id="local-node-id")
        store.update_from_knowledge_object(_service_ko(seq=1, now=1_000), now=1_001)

        with self.assertLogs("streetmesh.directory", level="INFO") as logs:
            expired = store.expire_stale(now=1_301)

        self.assertEqual(len(expired), 1)
        self.assertIsNone(store.get_service("provider-id", "temperature"))
        self.assertIn("SERVICE expired", logs.output[0])


class DuplicateCacheTests(unittest.TestCase):
    def test_remembers_new_knowledge_object_ids(self) -> None:
        cache = DuplicateCache(retention_seconds=300)

        self.assertTrue(cache.remember("ko-1", now=1_000))
        self.assertIn("ko-1", cache)
        self.assertEqual(len(cache), 1)

    def test_rejects_duplicate_knowledge_object_ids(self) -> None:
        cache = DuplicateCache(retention_seconds=300)
        cache.remember("ko-1", now=1_000)

        with self.assertLogs("streetmesh.directory", level="INFO") as logs:
            self.assertFalse(cache.remember("ko-1", now=1_001))

        self.assertIn("Duplicate Knowledge Object suppressed", logs.output[0])
        self.assertEqual(len(cache), 1)

    def test_expires_old_duplicate_cache_entries(self) -> None:
        cache = DuplicateCache(retention_seconds=300)
        cache.remember("ko-1", now=1_000)

        self.assertTrue(cache.remember("ko-1", now=1_301))

        self.assertIn("ko-1", cache)
        self.assertEqual(len(cache), 1)

    def test_rejects_invalid_retention(self) -> None:
        with self.assertRaisesRegex(ValueError, "retention_seconds"):
            DuplicateCache(retention_seconds=0)

def _node_ko(
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


def _service_ko(
    *,
    seq: int,
    now: int,
    endpoint: str = "/temperature",
) -> dict[str, object]:
    return create_service_knowledge_object(
        origin="provider-id",
        service_name="temperature",
        payload={
            "service_name": "temperature",
            "provider": "provider-id",
            "capabilities": ["humidity"],
            "endpoint": endpoint,
            "protocol": "http",
            "service_version": "0.1",
        },
        seq=seq,
        now=now,
    )


if __name__ == "__main__":
    unittest.main()
