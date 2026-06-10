"""Tests for persisted StreetMesh CLI inspection formatting."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from streetmesh.cli import main
from streetmesh.config import load_config
from streetmesh.directory import AwarenessStore, NodeEntry, ServiceEntry
from streetmesh.identity import create_identity, save_identity
from streetmesh.inspection import (
    InspectionState,
    format_nodes,
    format_services,
    format_status,
    format_trust,
    load_inspection_state,
)
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
)
from streetmesh.trust import TrustStore


class InspectionFormattingTests(unittest.TestCase):
    def test_formats_status_counts_and_local_identity(self) -> None:
        identity = create_identity("local@mesh")
        awareness = AwarenessStore(local_node_id=identity.node_id)
        awareness.add_local_node(
            node_id=identity.node_id,
            node_name=identity.node_name,
            expires=2_000,
            now=1_000,
        )
        trust = TrustStore()
        trust.add_trusted("remote-node")
        state = InspectionState(identity, awareness, trust)

        output = format_status(state, load_config(udp_port=40405))

        self.assertIn(identity.node_id, output)
        self.assertIn("local node_name", output)
        self.assertIn("local@mesh", output)
        self.assertIn("UDP port", output)
        self.assertIn("40405", output)
        self.assertIn("policy mode", output)
        self.assertIn("review", output)
        self.assertIn("known nodes", output)
        self.assertIn("known services", output)
        self.assertIn("trust entries", output)

    def test_formats_nodes_with_current_and_expired_status(self) -> None:
        nodes = [
            NodeEntry("a", "alpha", 100, 110, 200, False, 1, "trusted"),
            NodeEntry("b", "beta", 100, 110, 99, False, 1, "unknown"),
        ]

        output = format_nodes(nodes, now=100)

        self.assertIn("node_name", output)
        self.assertIn("alpha", output)
        self.assertIn("trusted", output)
        self.assertIn("current", output)
        self.assertIn("expired", output)

    def test_formats_limited_service_and_optional_fields(self) -> None:
        service = ServiceEntry(
            service_name="temperature",
            provider="node-a",
            provider_name="alpha",
            capabilities=[],
            endpoint=None,
            protocol="http",
            service_version=None,
            first_seen=100,
            last_seen=110,
            expires=200,
            is_local=False,
            seq=1,
            trust_state="unknown",
            accepted_limited=True,
        )

        output = format_services([service], now=100)

        self.assertIn("temperature", output)
        self.assertIn("unknown (limited)", output)
        self.assertIn("http", output)
        self.assertIn("current", output)

    def test_formats_empty_trust_store_readably(self) -> None:
        self.assertEqual(format_trust([]), "No trust entries.")

    def test_blocked_service_is_not_labeled_limited(self) -> None:
        service = ServiceEntry(
            service_name="temperature",
            provider="node-a",
            provider_name=None,
            capabilities=[],
            endpoint=None,
            protocol=None,
            service_version=None,
            first_seen=100,
            last_seen=110,
            expires=200,
            is_local=False,
            seq=1,
            trust_state="blocked",
            accepted_limited=False,
        )

        output = format_services([service], now=100)

        self.assertIn("blocked", output)
        self.assertNotIn("blocked (limited)", output)


class PersistedInspectionTests(unittest.TestCase):
    def test_loads_persisted_nodes_services_identity_and_trust(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            identity = create_identity("local@mesh")
            save_identity(data_dir / "identity.json", identity)
            awareness = AwarenessStore(
                local_node_id=identity.node_id,
                path=data_dir / "awareness.json",
            )
            awareness.add_local_node(
                node_id=identity.node_id,
                node_name=identity.node_name,
                expires=2_000,
                now=1_000,
            )
            awareness.update_from_knowledge_object(
                create_node_knowledge_object(
                    origin="remote-node",
                    subject="remote@mesh",
                    payload={
                        "node_id": "remote-node",
                        "node_name": "remote@mesh",
                    },
                    now=1_000,
                ),
                now=1_001,
            )
            awareness.update_from_knowledge_object(
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
                accepted_limited=True,
            )
            awareness.save()
            trust = TrustStore.load(data_dir / "trust.json")
            trust.add_trusted("remote-node")

            state = load_inspection_state(data_dir)

            self.assertEqual(state.identity, identity)
            self.assertEqual(len(state.awareness.list_nodes()), 2)
            local = state.awareness.get_by_node_id(identity.node_id)
            self.assertIsNotNone(local)
            assert local is not None
            self.assertEqual(local.trust_state, "privileged")
            service = state.awareness.get_service("remote-node", "temperature")
            self.assertIsNotNone(service)
            assert service is not None
            self.assertEqual(service.trust_state, "trusted")
            self.assertFalse(service.accepted_limited)

    def test_cli_list_nodes_reads_persisted_state_without_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            awareness = AwarenessStore(path=data_dir / "awareness.json")
            awareness.update_from_knowledge_object(
                create_node_knowledge_object(
                    origin="remote-node",
                    subject="remote@mesh",
                    payload={
                        "node_id": "remote-node",
                        "node_name": "remote@mesh",
                    },
                )
            )
            awareness.save()
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["--data-dir", str(data_dir), "--list-nodes"]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("remote@mesh", output.getvalue())
            self.assertFalse((data_dir / "trust.json").exists())


if __name__ == "__main__":
    unittest.main()
