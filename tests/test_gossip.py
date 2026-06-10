"""Tests for StreetMesh gossip forwarding policy."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest

from streetmesh.gossip import GossipForwarder
from streetmesh.protocol import create_node_knowledge_object
from streetmesh.policy import ReviewPolicy
from streetmesh.trust import TrustStore


class FakeTransport:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[bytes, int, str | None]] = []

    def send_broadcast(self, data: bytes, *, port: int, host: str | None = None) -> int:
        self.broadcasts.append((data, port, host))
        return len(data)


class GossipForwarderTests(unittest.TestCase):
    def test_decrements_ttl_before_forwarding(self) -> None:
        transport = FakeTransport()
        forwarder = self._forwarder(transport)

        forwarded = forwarder.forward(self._ko(ttl=3), now=1_000)

        self.assertIsNotNone(forwarded)
        assert forwarded is not None
        self.assertEqual(forwarded["ttl"], 2)
        encoded, port, host = transport.broadcasts[0]
        self.assertEqual(json.loads(encoded), forwarded)
        self.assertEqual((port, host), (40404, "255.255.255.255"))

    def test_zero_ttl_is_not_forwarded(self) -> None:
        transport = FakeTransport()

        with self.assertLogs("streetmesh.gossip", level="INFO") as logs:
            forwarded = self._forwarder(transport).forward(self._ko(ttl=0), now=1_000)

        self.assertIsNone(forwarded)
        self.assertEqual(transport.broadcasts, [])
        self.assertIn("reason=ttl-exhausted", logs.output[0])

    def test_one_ttl_forwards_as_terminal_zero_ttl(self) -> None:
        transport = FakeTransport()

        forwarded = self._forwarder(transport).forward(self._ko(ttl=1), now=1_000)

        self.assertIsNotNone(forwarded)
        assert forwarded is not None
        self.assertEqual(forwarded["ttl"], 0)

    def test_expired_object_is_not_forwarded(self) -> None:
        transport = FakeTransport()

        with self.assertLogs("streetmesh.gossip", level="INFO") as logs:
            forwarded = self._forwarder(transport).forward(self._ko(), now=1_121)

        self.assertIsNone(forwarded)
        self.assertEqual(transport.broadcasts, [])
        self.assertIn("reason=invalid", logs.output[0])

    def test_self_originated_object_is_not_forwarded(self) -> None:
        transport = FakeTransport()
        ko = self._ko()
        ko["origin"] = "local-node-id"
        ko["payload"]["node_id"] = "local-node-id"

        with self.assertLogs("streetmesh.gossip", level="INFO") as logs:
            forwarded = self._forwarder(transport).forward(ko, now=1_000)

        self.assertIsNone(forwarded)
        self.assertEqual(transport.broadcasts, [])
        self.assertIn("reason=self-originated", logs.output[0])

    def test_preserves_every_field_except_ttl(self) -> None:
        transport = FakeTransport()
        original = self._ko(ttl=3)
        snapshot = deepcopy(original)

        forwarded = self._forwarder(transport).forward(original, now=1_000)

        self.assertEqual(original, snapshot)
        self.assertIsNotNone(forwarded)
        assert forwarded is not None
        for field, value in original.items():
            if field != "ttl":
                self.assertEqual(forwarded[field], value)
        self.assertEqual(forwarded["ttl"], original["ttl"] - 1)

    def test_duplicate_object_is_not_forwarded_twice(self) -> None:
        transport = FakeTransport()
        forwarder = self._forwarder(transport)
        ko = self._ko()

        first = forwarder.forward(ko, now=1_000)
        with self.assertLogs("streetmesh.gossip", level="INFO") as logs:
            second = forwarder.forward(ko, now=1_001)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(transport.broadcasts), 1)
        self.assertTrue(any("reason=duplicate" in line for line in logs.output))

    def test_malformed_object_is_not_forwarded(self) -> None:
        transport = FakeTransport()

        forwarded = self._forwarder(transport).forward({"ttl": 3}, now=1_000)

        self.assertIsNone(forwarded)
        self.assertEqual(transport.broadcasts, [])

    def test_blocked_object_is_not_forwarded_by_gossip_policy(self) -> None:
        transport = FakeTransport()
        trust_store = TrustStore()
        trust_store.add_blocked("remote-node-id")
        forwarder = GossipForwarder(
            local_node_id="local-node-id",
            transport=transport,
            port=40404,
            trust_store=trust_store,
            policy=ReviewPolicy(),
        )

        with self.assertLogs("streetmesh.gossip", level="INFO") as logs:
            forwarded = forwarder.forward(self._ko(), now=1_000)

        self.assertIsNone(forwarded)
        self.assertEqual(transport.broadcasts, [])
        self.assertIn("reason=policy-rejected", logs.output[0])

    def _forwarder(self, transport: FakeTransport) -> GossipForwarder:
        return GossipForwarder(
            local_node_id="local-node-id",
            transport=transport,
            port=40404,
            host="255.255.255.255",
        )

    def _ko(self, *, ttl: int = 3) -> dict[str, object]:
        return create_node_knowledge_object(
            origin="remote-node-id",
            subject="remote@local@mesh",
            payload={
                "node_id": "remote-node-id",
                "node_name": "remote@local@mesh",
                "fingerprint": "a" * 64,
            },
            ttl=ttl,
            now=1_000,
        )


if __name__ == "__main__":
    unittest.main()
