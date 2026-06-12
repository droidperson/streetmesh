"""Tests for Milestone 15 signature-aware trust policy."""

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
from streetmesh.policy import ReviewPolicy
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
    encode_knowledge_object,
    evaluate_signature_status,
)
from streetmesh.transport_udp import Datagram


LOCAL_NODE_ID = "550e8400-e29b-41d4-a716-446655440000"
LOCAL_SECRET = "a" * 64
REMOTE_SECRET = "b" * 64


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


class SignatureEvaluationTests(unittest.TestCase):
    def test_unsigned_ko_is_classified_unsigned(self) -> None:
        ko = _node_ko(origin="remote-node")

        status = evaluate_signature_status(
            ko,
            local_node_id=LOCAL_NODE_ID,
            local_signing_secret=LOCAL_SECRET,
        )

        self.assertEqual(status, "unsigned")

    def test_local_signed_ko_is_self_verified(self) -> None:
        ko = _node_ko(
            origin=LOCAL_NODE_ID,
            signing_secret=LOCAL_SECRET,
        )

        status = evaluate_signature_status(
            ko,
            local_node_id=LOCAL_NODE_ID,
            local_signing_secret=LOCAL_SECRET,
        )

        self.assertEqual(status, "signed_self_verified")

    def test_tampered_local_signed_ko_is_invalid(self) -> None:
        ko = _node_ko(
            origin=LOCAL_NODE_ID,
            signing_secret=LOCAL_SECRET,
        )
        ko["subject"] = "tampered@local@mesh"
        ko["payload"]["node_name"] = "tampered@local@mesh"

        status = evaluate_signature_status(
            ko,
            local_node_id=LOCAL_NODE_ID,
            local_signing_secret=LOCAL_SECRET,
        )

        self.assertEqual(status, "signature_invalid")

    def test_remote_signed_ko_without_secret_is_unverified(self) -> None:
        ko = _node_ko(origin="remote-node", signing_secret=REMOTE_SECRET)

        status = evaluate_signature_status(
            ko,
            local_node_id=LOCAL_NODE_ID,
            local_signing_secret=LOCAL_SECRET,
        )

        self.assertEqual(status, "signed_unverified_remote")

    def test_unsupported_algorithm_is_classified_unsupported(self) -> None:
        ko = _node_ko(origin="remote-node", signing_secret=REMOTE_SECRET)
        ko["signature_algorithm"] = "FUTURE-SIGNATURE"

        self.assertEqual(
            evaluate_signature_status(ko, local_node_id=LOCAL_NODE_ID),
            "signature_unsupported",
        )
        encode_knowledge_object(ko)


class SignaturePolicyTests(unittest.TestCase):
    def test_policy_decision_includes_signature_status(self) -> None:
        decision = ReviewPolicy().decide(
            {"type": "NODE"},
            "unknown",
            "signed_unverified_remote",
        )

        self.assertEqual(decision.action, "accepted")
        self.assertEqual(
            decision.signature_status,
            "signed_unverified_remote",
        )

    def test_invalid_verifiable_signature_is_rejected(self) -> None:
        decision = ReviewPolicy().decide(
            {"type": "NODE"},
            "unknown",
            "signature_invalid",
        )

        self.assertEqual(decision.action, "rejected")
        self.assertFalse(decision.forward)
        self.assertEqual(decision.signature_status, "signature_invalid")

    def test_remote_signed_service_remains_accepted_limited(self) -> None:
        service = create_service_knowledge_object(
            origin="remote-node",
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": "remote-node",
            },
            signing_secret=REMOTE_SECRET,
        )
        awareness = AwarenessStore(local_node_id=LOCAL_NODE_ID)
        daemon = StreetMeshDaemon(_config(Path("data")))

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            daemon.receive_once(
                awareness,
                DuplicateCache(),
                FakeTransport(service),
                local_signing_secret=LOCAL_SECRET,
                timeout=0,
            )

        entry = awareness.get_service("remote-node", "temperature")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertTrue(entry.accepted_limited)
        self.assertEqual(entry.signature_status, "signed_unverified_remote")
        self.assertTrue(
            any("signature_status=signed_unverified_remote" in line for line in logs.output)
        )

    def test_tampered_local_claim_is_rejected_before_self_suppression(self) -> None:
        ko = _node_ko(
            origin=LOCAL_NODE_ID,
            signing_secret=LOCAL_SECRET,
        )
        ko["subject"] = "tampered@local@mesh"
        ko["payload"]["node_name"] = "tampered@local@mesh"
        awareness = AwarenessStore(local_node_id=LOCAL_NODE_ID)
        daemon = StreetMeshDaemon(_config(Path("data")))

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            daemon.receive_once(
                awareness,
                DuplicateCache(),
                FakeTransport(ko),
                local_signing_secret=LOCAL_SECRET,
                timeout=0,
            )

        self.assertEqual(awareness.list_nodes(), [])
        self.assertTrue(any("Policy rejected" in line for line in logs.output))
        self.assertTrue(any("signature_status=signature_invalid" in line for line in logs.output))


class SignatureAwarenessTests(unittest.TestCase):
    def test_node_and_service_signature_status_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "awareness.json"
            store = AwarenessStore(path=path, local_node_id=LOCAL_NODE_ID)
            store.update_from_knowledge_object(
                _node_ko(origin="remote-node", signing_secret=REMOTE_SECRET),
                signature_status="signed_unverified_remote",
                now=1_001,
            )
            store.update_from_knowledge_object(
                create_service_knowledge_object(
                    origin="remote-node",
                    service_name="temperature",
                    payload={
                        "service_name": "temperature",
                        "provider": "remote-node",
                    },
                    now=1_000,
                    signing_secret=REMOTE_SECRET,
                ),
                signature_status="signed_unverified_remote",
                now=1_001,
            )
            store.save()

            loaded = AwarenessStore.load(path, local_node_id=LOCAL_NODE_ID)

            node = loaded.get_by_node_id("remote-node")
            service = loaded.get_service("remote-node", "temperature")
            self.assertIsNotNone(node)
            self.assertIsNotNone(service)
            assert node is not None and service is not None
            self.assertEqual(node.signature_status, "signed_unverified_remote")
            self.assertEqual(service.signature_status, "signed_unverified_remote")

    def test_legacy_awareness_without_signature_status_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "awareness.json"
            store = AwarenessStore(path=path)
            store.update_from_knowledge_object(_node_ko(origin="remote-node"), now=1_001)
            store.update_from_knowledge_object(
                create_service_knowledge_object(
                    origin="remote-node",
                    service_name="temperature",
                    payload={
                        "service_name": "temperature",
                        "provider": "remote-node",
                    },
                    now=1_000,
                ),
                now=1_001,
            )
            store.save()
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["nodes"][0].pop("signature_status")
            raw["services"][0].pop("signature_status")
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = AwarenessStore.load(path)

            self.assertEqual(
                loaded.get_by_node_id("remote-node").signature_status,
                "signature_not_checked",
            )
            self.assertEqual(
                loaded.get_service("remote-node", "temperature").signature_status,
                "signature_not_checked",
            )

    def test_cli_node_and_service_lists_include_signature_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            store.update_from_knowledge_object(
                _node_ko(origin="remote-node", signing_secret=REMOTE_SECRET),
                signature_status="signed_unverified_remote",
            )
            store.update_from_knowledge_object(
                create_service_knowledge_object(
                    origin="remote-node",
                    service_name="temperature",
                    payload={
                        "service_name": "temperature",
                        "provider": "remote-node",
                    },
                    signing_secret=REMOTE_SECRET,
                ),
                signature_status="signed_unverified_remote",
            )
            store.save()

            node_output = StringIO()
            with redirect_stdout(node_output):
                self.assertEqual(
                    main(["--data-dir", str(data_dir), "--list-nodes"]),
                    0,
                )
            service_output = StringIO()
            with redirect_stdout(service_output):
                self.assertEqual(
                    main(["--data-dir", str(data_dir), "--list-services"]),
                    0,
                )

            self.assertIn("signature_status", node_output.getvalue())
            self.assertIn("signed_unverified_remote", node_output.getvalue())
            self.assertIn("signature_status", service_output.getvalue())
            self.assertIn("signed_unverified_remote", service_output.getvalue())


def _node_ko(
    *,
    origin: str,
    signing_secret: str | None = None,
) -> dict[str, object]:
    node_name = f"{origin}@local@mesh"
    return create_node_knowledge_object(
        origin=origin,
        subject=node_name,
        payload={
            "node_id": origin,
            "node_name": node_name,
            "fingerprint": "f" * 64,
        },
        signing_secret=signing_secret,
    )


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
