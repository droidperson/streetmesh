"""Tests for StreetMesh daemon announcement behavior."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.config import NodeConfig, StreetMeshConfig
from streetmesh.directory import AwarenessStore
from streetmesh.daemon import StreetMeshDaemon
from streetmesh.identity import NodeIdentity
from streetmesh.protocol import (
    create_node_knowledge_object,
    decode_knowledge_object,
    encode_knowledge_object,
)
from streetmesh.transport_udp import Datagram


class FakeTransport:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[bytes, int, str | None]] = []
        self.datagrams: list[Datagram] = []
        self.closed = False

    def send_broadcast(self, data: bytes, *, port: int, host: str | None = None) -> int:
        self.broadcasts.append((data, port, host))
        return len(data)

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        if self.datagrams:
            return self.datagrams.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


class InterruptingTransport(FakeTransport):
    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        raise KeyboardInterrupt


class DaemonAnnouncementTests(unittest.TestCase):
    def test_announce_once_broadcasts_node_knowledge_object(self) -> None:
        config = self._config(Path("data"))
        daemon = StreetMeshDaemon(config)
        transport = FakeTransport()
        identity = self._identity()

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            ko = daemon.announce_once(identity, transport)

        self.assertEqual(ko["seq"], 1)
        self.assertEqual(ko["ttl"], 3)
        self.assertEqual(ko["expires"], ko["created"] + 120)
        self.assertEqual(len(transport.broadcasts), 1)

        data, port, host = transport.broadcasts[0]
        decoded = decode_knowledge_object(data)
        self.assertEqual(decoded, ko)
        self.assertEqual(port, 40404)
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(decoded["origin"], identity.node_id)
        self.assertEqual(decoded["subject"], identity.node_name)
        self.assertEqual(decoded["payload"]["node_id"], identity.node_id)
        self.assertEqual(decoded["payload"]["node_name"], identity.node_name)
        log_line = logs.output[0]
        self.assertIn("NODE announcement broadcast", log_line)
        self.assertIn("node_name=node01@local@mesh", log_line)
        self.assertIn(f"ko_id={ko['ko_id']}", log_line)
        self.assertIn("seq=1", log_line)
        self.assertIn("ttl=3", log_line)
        self.assertIn(f"expires={ko['expires']}", log_line)

    def test_announcement_sequence_increments(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        identity = self._identity()

        first = daemon.announce_once(identity, transport)
        second = daemon.announce_once(identity, transport)

        self.assertEqual(first["seq"], 1)
        self.assertEqual(second["seq"], 2)

    def test_receive_once_updates_awareness_store_for_node_ko(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        remote_ko = create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(remote_ko),
                address=("127.0.0.1", 40404),
            )
        )

        daemon.receive_once(awareness, transport, timeout=0)

        entry = awareness.get_by_node_id("remote-node-id")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.node_name, "remote@local@mesh")
        self.assertFalse(entry.is_local)

    def test_receive_once_ignores_invalid_datagrams(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore()
        transport.datagrams.append(Datagram(data=b"{not-json", address=("127.0.0.1", 1)))

        with self.assertLogs("streetmesh.daemon", level="WARNING"):
            daemon.receive_once(awareness, transport, timeout=0)

        self.assertEqual(awareness.list_nodes(), [])

    def test_run_stops_cleanly_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transport = InterruptingTransport()
            config = self._config(Path(temp_dir))

            def make_transport(_config: StreetMeshConfig) -> InterruptingTransport:
                return transport

            daemon = StreetMeshDaemon(
                config,
                transport_factory=make_transport,
            )

            exit_code = daemon.run()

            self.assertEqual(exit_code, 0)
            self.assertTrue(transport.closed)
            self.assertEqual(len(transport.broadcasts), 1)

    def _config(self, data_dir: Path) -> StreetMeshConfig:
        return StreetMeshConfig(
            path=None,
            node=NodeConfig(
                node_name="node01@local@mesh",
                data_dir=data_dir,
                announce_interval=30,
                udp_port=40404,
                bind_host="127.0.0.1",
                broadcast_host="127.0.0.1",
            ),
        )

    def _identity(self) -> NodeIdentity:
        return NodeIdentity(
            node_id="550e8400-e29b-41d4-a716-446655440000",
            node_name="node01@local@mesh",
            created="2026-06-09T00:00:00+00:00",
            fingerprint="f" * 64,
        )


if __name__ == "__main__":
    unittest.main()
