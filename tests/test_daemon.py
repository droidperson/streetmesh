"""Tests for StreetMesh daemon announcement behavior."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from streetmesh.config import NodeConfig, StreetMeshConfig
from streetmesh.directory import AwarenessStore, DuplicateCache
from streetmesh.daemon import StreetMeshDaemon
from streetmesh.gossip import GossipForwarder
from streetmesh.identity import NodeIdentity, load_identity
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
    decode_knowledge_object,
    encode_knowledge_object,
    verify_knowledge_object_signature,
)
from streetmesh.policy import ReviewPolicy
from streetmesh.quarantine import QuarantineStore
from streetmesh.services import ServiceDefinition, ServiceRegistry
from streetmesh.trust import TrustStore
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


class SecondReceiveInterruptTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.receive_count = 0

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        self.receive_count += 1
        if self.receive_count == 2:
            raise KeyboardInterrupt
        return None


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
        self.assertTrue(
            verify_knowledge_object_signature(decoded, identity.signing_secret)
        )
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

    def test_announce_services_broadcasts_registered_service(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        services = ServiceRegistry(
            [
                ServiceDefinition(
                    service_name="temperature",
                    capabilities=("humidity",),
                    endpoint="/temperature",
                )
            ]
        )

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            announcements = daemon.announce_services_once(
                self._identity(),
                services,
                transport,
            )

        self.assertEqual(len(announcements), 1)
        decoded = decode_knowledge_object(transport.broadcasts[0][0])
        self.assertEqual(decoded["type"], "SERVICE")
        self.assertEqual(decoded["subject"], "temperature")
        self.assertEqual(decoded["payload"]["provider"], self._identity().node_id)
        self.assertTrue(
            verify_knowledge_object_signature(
                decoded,
                self._identity().signing_secret,
            )
        )
        self.assertIn("SERVICE announced", logs.output[0])

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

        daemon.receive_once(awareness, DuplicateCache(), transport, timeout=0)

        entry = awareness.get_by_node_id("remote-node-id")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.node_name, "remote@local@mesh")
        self.assertFalse(entry.is_local)
        self.assertEqual(entry.trust_state, "unknown")

    def test_receive_once_forwards_accepted_remote_node_ko(self) -> None:
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
            ttl=3,
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(remote_ko),
                address=("127.0.0.1", 40404),
            )
        )
        gossip = GossipForwarder(
            local_node_id=awareness.local_node_id or "",
            transport=transport,
            port=40404,
            host="127.0.0.1",
        )

        daemon.receive_once(
            awareness,
            DuplicateCache(),
            transport,
            gossip=gossip,
            timeout=0,
        )

        self.assertEqual(len(transport.broadcasts), 1)
        forwarded = decode_knowledge_object(transport.broadcasts[0][0])
        self.assertEqual(forwarded["ko_id"], remote_ko["ko_id"])
        self.assertEqual(forwarded["ttl"], 2)

    def test_receive_once_stores_and_forwards_remote_service(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        remote_ko = create_service_knowledge_object(
            origin="remote-node-id",
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": "remote-node-id",
                "capabilities": ["humidity"],
            },
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(remote_ko),
                address=("127.0.0.1", 40404),
            )
        )
        gossip = GossipForwarder(
            local_node_id=awareness.local_node_id or "",
            transport=transport,
            port=40404,
        )

        daemon.receive_once(
            awareness,
            DuplicateCache(),
            transport,
            gossip=gossip,
            timeout=0,
        )

        entry = awareness.get_service("remote-node-id", "temperature")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.trust_state, "unknown")
        self.assertTrue(entry.accepted_limited)
        self.assertEqual(len(transport.broadcasts), 1)
        forwarded = decode_knowledge_object(transport.broadcasts[0][0])
        self.assertEqual(forwarded["ttl"], 2)

    def test_blocked_claim_is_rejected_and_not_forwarded(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        blocked_ko = create_node_knowledge_object(
            origin="blocked-node-id",
            subject="blocked@local@mesh",
            payload={
                "node_id": "blocked-node-id",
                "node_name": "blocked@local@mesh",
                "fingerprint": "b" * 64,
            },
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(blocked_ko),
                address=("127.0.0.1", 40404),
            )
        )
        trust_store = TrustStore()
        trust_store.add_blocked("blocked-node-id")
        gossip = GossipForwarder(
            local_node_id=awareness.local_node_id or "",
            transport=transport,
            port=40404,
        )

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            daemon.receive_once(
                awareness,
                DuplicateCache(),
                transport,
                gossip=gossip,
                trust_store=trust_store,
                policy=ReviewPolicy(),
                timeout=0,
            )

        self.assertIsNone(awareness.get_by_node_id("blocked-node-id"))
        self.assertEqual(transport.broadcasts, [])
        self.assertTrue(any("Policy rejected" in line for line in logs.output))

    def test_unknown_gateway_is_quarantined(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        gateway_ko = create_node_knowledge_object(
            origin="gateway-node-id",
            subject="gateway@local@mesh",
            payload={},
        )
        gateway_ko["type"] = "GATEWAY"
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(gateway_ko),
                address=("127.0.0.1", 40404),
            )
        )
        quarantine = QuarantineStore()

        daemon.receive_once(
            awareness,
            DuplicateCache(),
            transport,
            trust_store=TrustStore(),
            policy=ReviewPolicy(),
            quarantine=quarantine,
            timeout=0,
        )

        self.assertEqual(len(quarantine.list_claims()), 1)
        self.assertEqual(quarantine.list_claims()[0]["type"], "GATEWAY")

    def test_trusted_service_is_accepted_normally(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        remote_ko = create_service_knowledge_object(
            origin="trusted-node-id",
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": "trusted-node-id",
            },
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(remote_ko),
                address=("127.0.0.1", 40404),
            )
        )
        trust_store = TrustStore()
        trust_store.add_trusted("trusted-node-id")

        daemon.receive_once(
            awareness,
            DuplicateCache(),
            transport,
            trust_store=trust_store,
            policy=ReviewPolicy(),
            timeout=0,
        )

        entry = awareness.get_service("trusted-node-id", "temperature")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.trust_state, "trusted")
        self.assertFalse(entry.accepted_limited)

    def test_receive_once_does_not_forward_ignored_older_node_ko(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore(local_node_id=self._identity().node_id)
        newer = create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
            seq=2,
        )
        older = create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
            seq=1,
        )
        awareness.update_from_knowledge_object(newer)
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(older),
                address=("127.0.0.1", 40404),
            )
        )
        gossip = GossipForwarder(
            local_node_id=awareness.local_node_id or "",
            transport=transport,
            port=40404,
        )

        daemon.receive_once(
            awareness,
            DuplicateCache(),
            transport,
            gossip=gossip,
            timeout=0,
        )

        self.assertEqual(transport.broadcasts, [])

    def test_receive_once_ignores_invalid_datagrams(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore()
        transport.datagrams.append(Datagram(data=b"{not-json", address=("127.0.0.1", 1)))

        with self.assertLogs("streetmesh.daemon", level="WARNING"):
            daemon.receive_once(awareness, DuplicateCache(), transport, timeout=0)

        self.assertEqual(awareness.list_nodes(), [])

    def test_receive_once_suppresses_duplicate_knowledge_objects(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        awareness = AwarenessStore()
        duplicate_cache = DuplicateCache()
        remote_ko = create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
        )
        encoded = encode_knowledge_object(remote_ko)
        transport.datagrams.extend(
            [
                Datagram(data=encoded, address=("127.0.0.1", 40404)),
                Datagram(data=encoded, address=("127.0.0.1", 40404)),
            ]
        )

        daemon.receive_once(awareness, duplicate_cache, transport, timeout=0)
        with self.assertLogs("streetmesh.directory", level="INFO") as logs:
            daemon.receive_once(awareness, duplicate_cache, transport, timeout=0)

        self.assertEqual(len(awareness.list_nodes()), 1)
        self.assertIn("Duplicate Knowledge Object suppressed", logs.output[0])

    def test_receive_once_suppresses_received_self_announcement(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        identity = self._identity()
        awareness = AwarenessStore(local_node_id=identity.node_id)
        duplicate_cache = DuplicateCache()
        awareness.add_local_node(
            node_id=identity.node_id,
            node_name=identity.node_name,
            expires=9_999,
            now=100,
        )
        announcement = create_node_knowledge_object(
            origin=identity.node_id,
            subject=identity.node_name,
            payload={
                "node_id": identity.node_id,
                "node_name": identity.node_name,
                "fingerprint": identity.fingerprint,
            },
            seq=1,
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(announcement),
                address=("127.0.0.1", 40404),
            )
        )

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            daemon.receive_once(awareness, duplicate_cache, transport, timeout=0)

        entry = awareness.get_by_node_id(identity.node_id)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertTrue(entry.is_local)
        self.assertEqual(entry.seq, 0)
        self.assertEqual(entry.last_seen, 100)
        self.assertEqual(len(duplicate_cache), 1)
        self.assertIn("Suppressed received self-announcement", logs.output[0])

    def test_receive_once_suppresses_received_self_service_announcement(self) -> None:
        daemon = StreetMeshDaemon(self._config(Path("data")))
        transport = FakeTransport()
        identity = self._identity()
        awareness = AwarenessStore(local_node_id=identity.node_id)
        duplicate_cache = DuplicateCache()
        announcement = create_service_knowledge_object(
            origin=identity.node_id,
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": identity.node_id,
                "endpoint": "/temperature",
            },
            seq=1,
        )
        awareness.update_from_knowledge_object(
            announcement,
            now=100,
            trust_state="privileged",
        )
        transport.datagrams.append(
            Datagram(
                data=encode_knowledge_object(announcement),
                address=("127.0.0.1", 40404),
            )
        )

        with self.assertLogs("streetmesh.daemon", level="INFO") as logs:
            daemon.receive_once(awareness, duplicate_cache, transport, timeout=0)

        entry = awareness.get_service(identity.node_id, "temperature")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertTrue(entry.is_local)
        self.assertEqual(entry.seq, 1)
        self.assertEqual(entry.last_seen, 100)
        self.assertEqual(entry.trust_state, "privileged")
        self.assertFalse(entry.accepted_limited)
        self.assertEqual(len(duplicate_cache), 1)
        self.assertEqual(transport.broadcasts, [])
        self.assertIn("Suppressed received self-announcement", logs.output[0])

    def test_receive_loop_expires_stale_awareness(self) -> None:
        times = iter([0.0, 31.0])
        daemon = StreetMeshDaemon(
            self._config(Path("data")),
            clock=lambda: next(times),
        )
        transport = FakeTransport()
        awareness = AwarenessStore()
        duplicate_cache = DuplicateCache()
        remote_ko = create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
        )
        awareness.update_from_knowledge_object(remote_ko)
        entry = awareness.get_by_node_id("remote-node-id")
        self.assertIsNotNone(entry)
        assert entry is not None
        entry.expires = 0

        with self.assertLogs("streetmesh.directory", level="INFO") as logs:
            daemon._receive_until_next_announcement(
                awareness,
                duplicate_cache,
                transport,
            )

        self.assertIsNone(awareness.get_by_node_id("remote-node-id"))
        self.assertIn("NODE_EXPIRED", logs.output[0])

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

    def test_runtime_periodically_announces_services(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service_path = Path(temp_dir) / "services.json"
            service_path.write_text(
                '{"services":[{"service_name":"temperature"}]}',
                encoding="utf-8",
            )
            transport = SecondReceiveInterruptTransport()
            times = iter([0.0, 0.0, 0.0, 0.0, 61.0, 61.0])
            base_config = self._config(Path(temp_dir))
            config = StreetMeshConfig(
                path=None,
                node=NodeConfig(
                    node_name=base_config.node.node_name,
                    data_dir=base_config.node.data_dir,
                    announce_interval=30,
                    udp_port=base_config.node.udp_port,
                    bind_host=base_config.node.bind_host,
                    broadcast_host=base_config.node.broadcast_host,
                    service_announce_interval=60,
                    services_file=service_path,
                ),
            )

            daemon = StreetMeshDaemon(
                config,
                transport_factory=lambda _config: transport,
                clock=lambda: next(times),
            )

            self.assertEqual(daemon.run(), 0)
            types = [
                decode_knowledge_object(data)["type"]
                for data, _port, _host in transport.broadcasts
            ]
            self.assertEqual(types.count("SERVICE"), 2)

            identity = load_identity(Path(temp_dir) / "identity.json")
            awareness = AwarenessStore.load(
                Path(temp_dir) / "awareness.json",
                local_node_id=identity.node_id,
            )
            entry = awareness.get_service(identity.node_id, "temperature")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertTrue(entry.is_local)
            self.assertEqual(entry.seq, 2)
            self.assertEqual(entry.trust_state, "privileged")
            self.assertFalse(entry.accepted_limited)

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
            signing_secret="a" * 64,
        )


if __name__ == "__main__":
    unittest.main()
