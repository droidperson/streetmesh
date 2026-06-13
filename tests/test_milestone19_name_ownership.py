"""Regression tests for Milestone 19 name ownership and conflict handling."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.cli import main
from streetmesh.config import NodeConfig, StreetMeshConfig
from streetmesh.daemon import StreetMeshDaemon
from streetmesh.directory import AwarenessStore, DuplicateCache
from streetmesh.name_bindings import NameBindingRegistry
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
    encode_knowledge_object,
)
from streetmesh.resolver import resolve_node, resolve_service
from streetmesh.trust import TrustStore
from streetmesh.transport_udp import Datagram


NODE_NAME = "pi01@local@mesh"
NODE_A = "node-a"
NODE_B = "node-b"


class StoppingTransport:
    def send_broadcast(
        self,
        data: bytes,
        *,
        port: int,
        host: str | None = None,
    ) -> int:
        del port, host
        return len(data)

    def receive(self, *, timeout: float | None = None) -> None:
        del timeout
        raise KeyboardInterrupt

    def close(self) -> None:
        pass


class DatagramTransport:
    def __init__(self, knowledge_object: dict[str, object]) -> None:
        self.datagram = Datagram(
            encode_knowledge_object(knowledge_object),
            ("127.0.0.1", 40404),
        )

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        del timeout
        datagram = self.datagram
        self.datagram = None
        return datagram

    def send_broadcast(
        self,
        data: bytes,
        *,
        port: int,
        host: str | None = None,
    ) -> int:
        del port, host
        return len(data)

    def close(self) -> None:
        pass


class NameBindingRegistryTests(unittest.TestCase):
    def test_daemon_creates_local_privileged_name_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            daemon = StreetMeshDaemon(
                _config(data_dir, node_name="laptop-m19@local@mesh"),
                transport_factory=lambda _config: StoppingTransport(),
            )

            self.assertEqual(daemon.run(), 0)
            identity = json.loads(
                (data_dir / "identity.json").read_text(encoding="utf-8")
            )
            binding = NameBindingRegistry.load(
                data_dir / "name_bindings.json"
            ).get("laptop-m19@local@mesh")

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.node_id, identity["node_id"])
        self.assertEqual(binding.binding_state, "local")
        self.assertEqual(binding.source, "local")

    def test_missing_registry_loads_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "name_bindings.json"

            registry = NameBindingRegistry.load(path)

            self.assertEqual(registry.list_bindings(), [])
            self.assertEqual(registry.list_conflicts(), [])
            self.assertFalse(path.exists())

    def test_same_identity_confirms_binding_without_conflict(self) -> None:
        registry = NameBindingRegistry()
        original = registry.bind(NODE_NAME, NODE_A, now=100, save=False)

        status = registry.observe_claim(NODE_NAME, NODE_A, now=200, save=False)
        confirmed = registry.get(NODE_NAME)

        self.assertEqual(status, "bound")
        self.assertEqual(registry.list_conflicts(), [])
        self.assertEqual(confirmed.node_id, NODE_A)
        self.assertEqual(confirmed.first_bound, original.first_bound)
        self.assertEqual(confirmed.last_confirmed, 200)

    def test_different_identity_is_recorded_without_replacing_binding(self) -> None:
        registry = NameBindingRegistry()
        registry.bind(NODE_NAME, NODE_A, now=100, save=False)

        status = registry.observe_claim(
            NODE_NAME,
            NODE_B,
            fingerprint="b" * 64,
            now=200,
            save=False,
        )

        self.assertEqual(status, "name_conflict")
        self.assertEqual(registry.get(NODE_NAME).node_id, NODE_A)
        self.assertEqual(len(registry.list_conflicts()), 1)
        self.assertEqual(registry.list_conflicts()[0].claimant_node_id, NODE_B)

    def test_received_conflicting_node_is_persisted_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            path = data_dir / "name_bindings.json"
            registry = NameBindingRegistry(path)
            registry.bind(NODE_NAME, NODE_A, now=100)
            claimant = create_node_knowledge_object(
                origin=NODE_B,
                subject=NODE_NAME,
                payload={
                    "node_id": NODE_B,
                    "node_name": NODE_NAME,
                    "fingerprint": "b" * 64,
                },
            )
            awareness = AwarenessStore(local_node_id="local-node")

            with self.assertLogs("streetmesh.daemon", level="WARNING") as logs:
                StreetMeshDaemon(_config(data_dir)).receive_once(
                    awareness,
                    DuplicateCache(),
                    DatagramTransport(claimant),
                    name_bindings=registry,
                    timeout=0,
                )
            entry = awareness.get_by_node_id(NODE_B)
            reloaded = NameBindingRegistry.load(path)

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.binding_status, "name_conflict")
        self.assertEqual(reloaded.get(NODE_NAME).node_id, NODE_A)
        self.assertEqual(reloaded.list_conflicts()[0].claimant_node_id, NODE_B)
        self.assertIn("Name binding conflict", logs.output[0])

    def test_old_trust_entries_still_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"
            path.write_text(
                json.dumps(
                    {"nodes": [{"node_id": NODE_A, "state": "trusted"}]}
                ),
                encoding="utf-8",
            )

            entry = TrustStore.load(path).get_entry(NODE_A)

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIsNone(entry.node_name)
        self.assertEqual(entry.state, "trusted")


class ConflictAwareResolutionTests(unittest.TestCase):
    def test_current_bound_node_wins_with_conflicting_claimant_reported(self) -> None:
        store = AwarenessStore()
        _add_node(store, NODE_A, NODE_NAME)
        _add_node(store, NODE_B, NODE_NAME)
        registry = NameBindingRegistry()
        registry.bind(NODE_NAME, NODE_A, now=900, save=False)

        result = resolve_node(
            store,
            NODE_NAME,
            now=1_100,
            name_bindings=registry,
        )

        self.assertEqual(result.resolution_status, "resolved")
        self.assertEqual(result.node_id, NODE_A)
        self.assertIn("conflicting claimants", result.reason)
        self.assertEqual(result.candidates[1].binding_status, "name_conflict")

    def test_unavailable_bound_node_is_not_replaced_by_claimant(self) -> None:
        store = AwarenessStore()
        _add_node(store, NODE_B, NODE_NAME)
        registry = NameBindingRegistry()
        registry.bind(NODE_NAME, NODE_A, now=900, save=False)

        result = resolve_node(
            store,
            NODE_NAME,
            now=1_100,
            name_bindings=registry,
        )

        self.assertEqual(result.resolution_status, "conflict")
        self.assertEqual(registry.get(NODE_NAME).node_id, NODE_A)
        self.assertIn("bound to a different identity", result.reason)

    def test_multiple_unbound_claimants_are_conflict_not_arbitrary_resolution(self) -> None:
        store = AwarenessStore()
        _add_node(store, NODE_A, NODE_NAME)
        _add_node(store, NODE_B, NODE_NAME)

        result = resolve_node(store, NODE_NAME, now=1_100)

        self.assertEqual(result.resolution_status, "conflict")
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(store.get_by_node_name(NODE_NAME))

    def test_service_resolution_does_not_prefer_conflicting_provider(self) -> None:
        store = AwarenessStore()
        _add_node(store, NODE_A, NODE_NAME, binding_status="bound")
        _add_node(store, NODE_B, NODE_NAME, binding_status="name_conflict")
        _add_service(store, NODE_A, binding_status="bound", last_seen=1_001)
        _add_service(
            store,
            NODE_B,
            binding_status="name_conflict",
            last_seen=1_099,
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.provider_node_id, NODE_A)
        self.assertEqual(result.resolution_status, "limited")
        conflicting = next(
            item for item in result.candidates if item.provider_node_id == NODE_B
        )
        self.assertFalse(conflicting.usable)


class NameBindingCliTests(unittest.TestCase):
    def test_trust_node_name_persists_trust_and_name_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            _add_node(store, NODE_A, NODE_NAME, now=None)
            store.save()

            code, output = _run_cli(
                ["--data-dir", str(data_dir), "--trust-node-name", NODE_NAME]
            )
            trust_entry = TrustStore.load(data_dir / "trust.json").get_entry(NODE_A)
            binding = NameBindingRegistry.load(
                data_dir / "name_bindings.json"
            ).get(NODE_NAME)

        self.assertEqual(code, 0)
        self.assertIn("new_trust_state", output)
        self.assertEqual(trust_entry.state, "trusted")
        self.assertEqual(binding.node_id, NODE_A)
        self.assertEqual(binding.source, "trusted")

    def test_binding_and_conflict_inspection_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            registry = NameBindingRegistry(data_dir / "name_bindings.json")
            registry.bind(NODE_NAME, NODE_A, now=100, save=False)
            registry.observe_claim(NODE_NAME, NODE_B, now=200, save=True)

            list_code, list_output = _run_cli(
                ["--data-dir", str(data_dir), "--list-name-bindings"]
            )
            show_code, show_output = _run_cli(
                ["--data-dir", str(data_dir), "--show-name-binding", NODE_NAME]
            )
            conflict_code, conflict_output = _run_cli(
                ["--data-dir", str(data_dir), "--list-name-conflicts"]
            )

        self.assertEqual((list_code, show_code, conflict_code), (0, 0, 0))
        self.assertIn(NODE_NAME, list_output)
        self.assertIn(NODE_A, list_output)
        self.assertIn("binding_state", show_output)
        self.assertIn("conflict_count", show_output)
        self.assertIn(NODE_B, conflict_output)
        self.assertIn("claimant_node_id", conflict_output)

    def test_inspection_derives_active_conflict_from_persisted_awareness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            awareness = AwarenessStore(path=data_dir / "awareness.json")
            _add_node(awareness, NODE_A, NODE_NAME, now=None)
            _add_node(awareness, NODE_B, NODE_NAME, now=None)
            awareness.save()
            registry = NameBindingRegistry(data_dir / "name_bindings.json")
            registry.bind(NODE_NAME, NODE_A)
            trust = TrustStore.load(data_dir / "trust.json")
            trust.bind_name(NODE_A, NODE_NAME, "trusted")

            self.assertEqual(registry.list_conflicts(), [])
            list_code, list_output = _run_cli(
                ["--data-dir", str(data_dir), "--list-name-conflicts"]
            )
            show_code, show_output = _run_cli(
                ["--data-dir", str(data_dir), "--show-name-binding", NODE_NAME]
            )
            resolve_code, resolve_output = _run_cli(
                ["--data-dir", str(data_dir), "--resolve-node", NODE_NAME]
            )

        self.assertEqual((list_code, show_code, resolve_code), (0, 0, 0))
        self.assertIn(NODE_NAME, list_output)
        self.assertIn(NODE_A, list_output)
        self.assertIn(NODE_B, list_output)
        self.assertIn("active-name-claim-conflicts-with-binding", list_output)
        self.assertIn("conflict_count : 1", show_output)
        self.assertIn("resolution_status", resolve_output)
        self.assertIn("resolved", resolve_output)
        self.assertIn("conflicting claimants are present", resolve_output)
        self.assertIn("name_conflict", resolve_output)
        self.assertIn("no", resolve_output)


def _add_node(
    store: AwarenessStore,
    node_id: str,
    node_name: str,
    *,
    binding_status: str = "unbound",
    now: int | None = 1_001,
) -> None:
    created = 1_000 if now is not None else None
    store.update_from_knowledge_object(
        create_node_knowledge_object(
            origin=node_id,
            subject=node_name,
            payload={
                "node_id": node_id,
                "node_name": node_name,
                "fingerprint": ("a" if node_id == NODE_A else "b") * 64,
            },
            now=created,
        ),
        now=now,
        signature_status="signed_unverified_remote",
        binding_status=binding_status,
    )


def _add_service(
    store: AwarenessStore,
    provider: str,
    *,
    binding_status: str,
    last_seen: int,
) -> None:
    store.update_from_knowledge_object(
        create_service_knowledge_object(
            origin=provider,
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": provider,
                "endpoint": "/temperature",
                "protocol": "http",
            },
            now=1_000,
        ),
        now=1_001,
        trust_state="unknown",
        accepted_limited=True,
        binding_status=binding_status,
    )
    entry = store.get_service(provider, "temperature")
    assert entry is not None
    entry.last_seen = last_seen


def _run_cli(arguments: list[str]) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output):
        code = main(arguments)
    return code, output.getvalue()


def _config(data_dir: Path, *, node_name: str = "local@mesh") -> StreetMeshConfig:
    return StreetMeshConfig(
        path=None,
        node=NodeConfig(
            node_name=node_name,
            data_dir=data_dir,
            announce_interval=30,
            udp_port=40404,
            bind_host="127.0.0.1",
            broadcast_host="127.0.0.1",
        ),
    )


if __name__ == "__main__":
    unittest.main()
