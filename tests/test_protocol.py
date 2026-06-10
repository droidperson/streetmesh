"""Tests for StreetMesh Knowledge Object protocol behavior."""

from __future__ import annotations

import unittest
import time
import uuid

from streetmesh.protocol import (
    KnowledgeObjectError,
    create_node_knowledge_object,
    create_service_knowledge_object,
    decode_knowledge_object,
    decode_message,
    encode_knowledge_object,
    encode_message,
    validate_knowledge_object,
)


class KnowledgeObjectTests(unittest.TestCase):
    def test_creates_node_knowledge_object(self) -> None:
        ko = create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            seq=7,
            ttl=9,
            expires_in=60,
            now=1_700_000_000,
        )

        self.assertEqual(ko["v"], 1)
        self.assertEqual(uuid.UUID(ko["ko_id"]).version, 4)
        self.assertEqual(ko["type"], "NODE")
        self.assertEqual(ko["origin"], "node-a")
        self.assertEqual(ko["subject"], "node-a")
        self.assertEqual(ko["created"], 1_700_000_000)
        self.assertEqual(ko["expires"], 1_700_000_060)
        self.assertEqual(ko["seq"], 7)
        self.assertEqual(ko["ttl"], 9)
        self.assertEqual(ko["payload"], {"node_name": "node01@local@mesh"})
        self.assertIsNone(ko["signature"])

    def test_node_defaults_ttl_and_expiry_independently(self) -> None:
        ko = create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            now=1_700_000_000,
        )

        self.assertEqual(ko["ttl"], 3)
        self.assertEqual(ko["expires"], 1_700_000_120)

    def test_creates_service_knowledge_object_with_defaults(self) -> None:
        ko = create_service_knowledge_object(
            origin="node-a",
            service_name="temperature",
            payload={
                "service_name": "temperature",
                "provider": "node-a",
                "capabilities": ["current_temperature", "humidity"],
                "endpoint": "/temperature",
                "protocol": "http",
                "service_version": "0.1",
            },
            now=1_700_000_000,
        )

        self.assertEqual(ko["type"], "SERVICE")
        self.assertEqual(ko["subject"], "temperature")
        self.assertEqual(ko["ttl"], 3)
        self.assertEqual(ko["expires"], 1_700_000_300)

    def test_rejects_service_without_required_provider(self) -> None:
        with self.assertRaisesRegex(KnowledgeObjectError, "provider"):
            create_service_knowledge_object(
                origin="node-a",
                service_name="temperature",
                payload={"service_name": "temperature"},
                now=1_700_000_000,
            )

    def test_rejects_service_with_invalid_capabilities(self) -> None:
        with self.assertRaisesRegex(KnowledgeObjectError, "capabilities"):
            create_service_knowledge_object(
                origin="node-a",
                service_name="temperature",
                payload={
                    "service_name": "temperature",
                    "provider": "node-a",
                    "capabilities": ["temperature", 1],
                },
                now=1_700_000_000,
            )

    def test_ttl_and_expires_are_independent(self) -> None:
        ko = create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            ttl=1,
            expires_in_seconds=300,
            now=1_700_000_000,
        )

        self.assertEqual(ko["ttl"], 1)
        self.assertEqual(ko["expires"], 1_700_000_300)
        validate_knowledge_object(ko, now=1_700_000_001)

    def test_encodes_and_decodes_utf8_json(self) -> None:
        now = int(time.time())
        ko = create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            now=now,
        )

        encoded = encode_knowledge_object(ko)
        decoded = decode_knowledge_object(encoded)

        self.assertIsInstance(encoded, bytes)
        self.assertEqual(decoded, ko)

    def test_message_aliases_round_trip(self) -> None:
        now = int(time.time())
        ko = create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            now=now,
        )

        encoded = encode_message(ko)
        decoded = decode_message(encoded)

        self.assertIsInstance(encoded, bytes)
        self.assertEqual(decoded, ko)

    def test_rejects_malformed_json(self) -> None:
        with self.assertRaisesRegex(KnowledgeObjectError, "malformed JSON"):
            decode_knowledge_object(b"{not-json")

    def test_rejects_missing_required_fields(self) -> None:
        with self.assertRaisesRegex(KnowledgeObjectError, "missing required field"):
            validate_knowledge_object({"v": 1})

    def test_rejects_unsupported_types(self) -> None:
        ko = self._valid_ko()
        ko["type"] = "EDGE"

        with self.assertRaisesRegex(KnowledgeObjectError, "unsupported"):
            validate_knowledge_object(ko, now=1_700_000_000)

    def test_rejects_expired_objects(self) -> None:
        ko = self._valid_ko()
        ko["expires"] = 1_700_000_001

        with self.assertRaisesRegex(KnowledgeObjectError, "expired"):
            validate_knowledge_object(ko, now=1_700_000_002)

    def test_accepts_zero_ttl_as_terminal_hop(self) -> None:
        ko = self._valid_ko()
        ko["ttl"] = 0

        validate_knowledge_object(ko, now=1_700_000_000)

    def test_rejects_negative_ttl(self) -> None:
        ko = self._valid_ko()
        ko["ttl"] = -1

        with self.assertRaisesRegex(KnowledgeObjectError, "ttl"):
            validate_knowledge_object(ko, now=1_700_000_000)

    def test_rejects_expires_earlier_than_created(self) -> None:
        ko = self._valid_ko()
        ko["expires"] = ko["created"] - 1

        with self.assertRaisesRegex(KnowledgeObjectError, "expires"):
            validate_knowledge_object(ko, now=1_700_000_000)

    def test_rejects_invalid_node_payload(self) -> None:
        ko = self._valid_ko()
        ko["payload"] = {"node_name": ""}

        with self.assertRaisesRegex(KnowledgeObjectError, "payload.node_name"):
            validate_knowledge_object(ko, now=1_700_000_000)

    def _valid_ko(self) -> dict[str, object]:
        return create_node_knowledge_object(
            origin="node-a",
            subject="node-a",
            payload={"node_name": "node01@local@mesh"},
            seq=1,
            ttl=3,
            expires_in=60,
            now=1_700_000_000,
        )


if __name__ == "__main__":
    unittest.main()
