"""Tests for Milestone 17 trust promotion and name binding."""

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
from streetmesh.inspection import load_inspection_state
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
    encode_knowledge_object,
)
from streetmesh.resolver import resolve_node, resolve_service
from streetmesh.transport_udp import Datagram
from streetmesh.trust import TrustStore, TrustStoreError


NODE_NAME = "pi01@local@mesh"
NODE_ID = "pi01-node-id"
FINGERPRINT = "f" * 64


class FakeTransport:
    def __init__(self, knowledge_object: dict[str, object]) -> None:
        self.datagram = Datagram(
            data=encode_knowledge_object(knowledge_object),
            address=("127.0.0.1", 40404),
        )
        self.broadcasts: list[tuple[bytes, int, str | None]] = []

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
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
        self.broadcasts.append((data, port, host))
        return len(data)

    def close(self) -> None:
        pass


class TrustStoreBindingTests(unittest.TestCase):
    def test_name_binding_stores_name_fingerprint_and_timestamps(self) -> None:
        store = TrustStore()

        entry = store.add_trusted(
            NODE_ID,
            node_name=NODE_NAME,
            fingerprint=FINGERPRINT,
            now=1_000,
        )

        self.assertEqual(entry.node_name, NODE_NAME)
        self.assertEqual(entry.fingerprint, FINGERPRINT)
        self.assertEqual(entry.first_trusted, 1_000)
        self.assertEqual(entry.last_confirmed, 1_000)
        self.assertEqual(entry.binding_status, "bound")
        self.assertEqual(entry.trust_state, "trusted")

    def test_old_trust_entry_without_name_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trust.json"
            path.write_text(
                json.dumps(
                    {"nodes": [{"node_id": NODE_ID, "state": "trusted"}]}
                ),
                encoding="utf-8",
            )

            store = TrustStore.load(path)

            entry = store.get_entry(NODE_ID)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.state, "trusted")
            self.assertIsNone(entry.node_name)
            self.assertEqual(entry.binding_status, "unbound")

    def test_trusted_name_binding_cannot_be_replaced(self) -> None:
        store = TrustStore()
        store.bind_name(NODE_ID, NODE_NAME, "trusted", now=1_000)

        with self.assertRaisesRegex(TrustStoreError, "already bound"):
            store.bind_name("different-node-id", NODE_NAME, "trusted", now=1_001)

        self.assertEqual(store.get_by_name(NODE_NAME).node_id, NODE_ID)

    def test_bound_identity_claiming_new_name_is_stale(self) -> None:
        store = TrustStore()
        store.bind_name(NODE_ID, NODE_NAME, "trusted", now=1_000)

        self.assertEqual(
            store.binding_status_for_claim(NODE_ID, "new-name@local@mesh"),
            "stale_binding",
        )


class TrustByNameCliTests(unittest.TestCase):
    def test_trusts_node_by_resolved_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_awareness(data_dir, include_service=True)
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["--data-dir", str(data_dir), "--trust-node-name", NODE_NAME]
                )

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn(NODE_NAME, rendered)
            self.assertIn(NODE_ID, rendered)
            self.assertIn("previous_trust_state", rendered)
            self.assertIn("new_trust_state", rendered)
            self.assertIn("signed_unverified_remote", rendered)
            self.assertIn("bound", rendered)
            entry = TrustStore.load(data_dir / "trust.json").get_entry(NODE_ID)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.state, "trusted")
            self.assertEqual(entry.node_name, NODE_NAME)
            self.assertEqual(entry.fingerprint, FINGERPRINT)

    def test_blocks_node_by_resolved_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_awareness(data_dir)

            exit_code = _run_cli(
                ["--data-dir", str(data_dir), "--block-node-name", NODE_NAME]
            )[0]

            self.assertEqual(exit_code, 0)
            entry = TrustStore.load(data_dir / "trust.json").get_entry(NODE_ID)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.state, "blocked")
            self.assertEqual(entry.node_name, NODE_NAME)
            self.assertEqual(entry.binding_status, "bound")

    def test_trust_by_name_fails_when_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            exit_code, output = _run_cli(
                ["--data-dir", str(data_dir), "--trust-node-name", NODE_NAME]
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("resolution_status=not_found", output)
            self.assertFalse((data_dir / "trust.json").exists())

    def test_trust_by_name_fails_when_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            _add_node(store, NODE_ID, NODE_NAME)
            _add_node(store, "other-node-id", NODE_NAME)
            store.save()

            exit_code, output = _run_cli(
                ["--data-dir", str(data_dir), "--trust-node-name", NODE_NAME]
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("resolution_status=conflict", output)
            self.assertFalse((data_dir / "trust.json").exists())

    def test_list_and_show_trust_include_bound_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = TrustStore.load(data_dir / "trust.json")
            store.bind_name(
                NODE_ID,
                NODE_NAME,
                "trusted",
                fingerprint=FINGERPRINT,
                now=1_000,
            )

            list_code, list_output = _run_cli(
                ["--data-dir", str(data_dir), "--list-trust"]
            )
            show_code, show_output = _run_cli(
                ["--data-dir", str(data_dir), "--show-trust", NODE_NAME]
            )

            self.assertEqual((list_code, show_code), (0, 0))
            self.assertIn(NODE_NAME, list_output)
            self.assertIn("binding_status", list_output)
            self.assertIn(NODE_NAME, show_output)
            self.assertIn(FINGERPRINT, show_output)

    def test_trusted_provider_service_is_no_longer_limited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_awareness(data_dir, include_service=True)
            self.assertEqual(
                _run_cli(
                    ["--data-dir", str(data_dir), "--trust-node-name", NODE_NAME]
                )[0],
                0,
            )

            state = load_inspection_state(data_dir)
            service = state.awareness.get_service(NODE_ID, "temperature")
            result = resolve_service(state.awareness, "temperature")

            self.assertIsNotNone(service)
            assert service is not None
            self.assertEqual(service.trust_state, "trusted")
            self.assertFalse(service.accepted_limited)
            self.assertEqual(result.resolution_status, "resolved")
            self.assertEqual(result.provider_node_id, NODE_ID)


class NameConflictTests(unittest.TestCase):
    def test_conflicting_claim_is_detected_without_replacing_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trust_store = TrustStore.load(Path(temp_dir) / "trust.json")
            trust_store.bind_name(NODE_ID, NODE_NAME, "trusted", now=1_000)
            claimant_id = "different-node-id"
            claimant = create_node_knowledge_object(
                origin=claimant_id,
                subject=NODE_NAME,
                payload={
                    "node_id": claimant_id,
                    "node_name": NODE_NAME,
                    "fingerprint": "b" * 64,
                },
            )
            awareness = AwarenessStore(local_node_id="local-node-id")
            daemon = StreetMeshDaemon(_config(Path(temp_dir)))

            with self.assertLogs("streetmesh.daemon", level="WARNING") as logs:
                daemon.receive_once(
                    awareness,
                    DuplicateCache(),
                    FakeTransport(claimant),
                    trust_store=trust_store,
                    timeout=0,
                )

            conflict = awareness.get_by_node_id(claimant_id)
            self.assertIsNotNone(conflict)
            assert conflict is not None
            self.assertEqual(conflict.binding_status, "name_conflict")
            self.assertIn("Trusted name conflict", logs.output[0])
            self.assertEqual(trust_store.get_by_name(NODE_NAME).node_id, NODE_ID)

    def test_bound_identity_outranks_conflicting_claimant_and_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            awareness = AwarenessStore(path=data_dir / "awareness.json")
            _add_node(awareness, NODE_ID, NODE_NAME)
            _add_node(awareness, "different-node-id", NODE_NAME)
            _add_service(awareness, NODE_ID)
            _add_service(awareness, "different-node-id")
            awareness.save()
            trust = TrustStore.load(data_dir / "trust.json")
            trust.bind_name(NODE_ID, NODE_NAME, "trusted", now=1_000)

            state = load_inspection_state(data_dir)
            node_result = resolve_node(state.awareness, NODE_NAME)
            service_result = resolve_service(state.awareness, "temperature")

            conflicting = state.awareness.get_by_node_id("different-node-id")
            self.assertIsNotNone(conflicting)
            assert conflicting is not None
            self.assertEqual(conflicting.binding_status, "name_conflict")
            self.assertEqual(node_result.node_id, NODE_ID)
            self.assertEqual(node_result.resolution_status, "resolved")
            self.assertEqual(service_result.provider_node_id, NODE_ID)
            self.assertEqual(service_result.resolution_status, "resolved")


def _write_awareness(data_dir: Path, *, include_service: bool = False) -> None:
    store = AwarenessStore(path=data_dir / "awareness.json")
    _add_node(store, NODE_ID, NODE_NAME)
    if include_service:
        _add_service(store, NODE_ID)
    store.save()


def _add_node(store: AwarenessStore, node_id: str, node_name: str) -> None:
    store.update_from_knowledge_object(
        create_node_knowledge_object(
            origin=node_id,
            subject=node_name,
            payload={
                "node_id": node_id,
                "node_name": node_name,
                "fingerprint": FINGERPRINT if node_id == NODE_ID else "b" * 64,
            },
        ),
        trust_state="unknown",
        signature_status="signed_unverified_remote",
        binding_status="unbound",
    )


def _add_service(store: AwarenessStore, provider: str) -> None:
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
        ),
        trust_state="unknown",
        accepted_limited=True,
        signature_status="signed_unverified_remote",
    )


def _run_cli(arguments: list[str]) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(arguments)
    return exit_code, output.getvalue()


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
