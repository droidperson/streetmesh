"""Tests for Milestone 16 node and service resolution."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.cli import main
from streetmesh.directory import AwarenessStore
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
)
from streetmesh.resolver import resolve_node, resolve_service


class NodeResolutionTests(unittest.TestCase):
    def test_resolves_existing_current_node(self) -> None:
        store = AwarenessStore()
        _add_node(
            store,
            node_id="pi01-id",
            node_name="pi01@local@mesh",
            trust_state="trusted",
            signature_status="signed_unverified_remote",
        )

        result = resolve_node(store, "pi01@local@mesh", now=1_100)

        self.assertEqual(result.resolution_status, "resolved")
        self.assertEqual(result.node_id, "pi01-id")
        self.assertEqual(result.trust_state, "trusted")
        self.assertEqual(result.signature_status, "signed_unverified_remote")
        self.assertEqual(result.status, "current")

    def test_missing_node_is_not_found(self) -> None:
        result = resolve_node(AwarenessStore(), "missing@local@mesh", now=1_100)

        self.assertEqual(result.resolution_status, "not_found")
        self.assertIsNone(result.chosen)
        self.assertEqual(result.candidates, ())

    def test_expired_node_is_reported(self) -> None:
        store = AwarenessStore()
        _add_node(store, node_id="pi01-id", node_name="pi01@local@mesh")

        result = resolve_node(store, "pi01@local@mesh", now=1_121)

        self.assertEqual(result.resolution_status, "expired")
        self.assertEqual(result.status, "expired")

    def test_multiple_node_ids_for_one_name_report_conflict(self) -> None:
        store = AwarenessStore()
        _add_node(store, node_id="node-a", node_name="shared@local@mesh")
        _add_node(store, node_id="node-b", node_name="shared@local@mesh")

        result = resolve_node(store, "shared@local@mesh", now=1_100)

        self.assertEqual(result.resolution_status, "conflict")
        self.assertEqual(len(result.candidates), 2)


class ServiceResolutionTests(unittest.TestCase):
    def test_resolves_service_with_one_trusted_provider(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="pi01-id",
            trust_state="trusted",
            signature_status="signed_unverified_remote",
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.resolution_status, "resolved")
        self.assertEqual(result.provider_node_id, "pi01-id")
        self.assertEqual(result.endpoint, "/temperature")
        self.assertEqual(result.protocol, "http")

    def test_multiple_current_providers_are_ambiguous(self) -> None:
        store = AwarenessStore()
        _add_service(store, provider="node-a", trust_state="trusted")
        _add_service(store, provider="node-b", trust_state="trusted")

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.resolution_status, "ambiguous")
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNotNone(result.chosen)

    def test_ranking_prefers_trusted_over_unknown(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="unknown-node",
            trust_state="unknown",
            last_seen=1_090,
        )
        _add_service(
            store,
            provider="trusted-node",
            trust_state="trusted",
            last_seen=1_010,
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.resolution_status, "ambiguous")
        self.assertEqual(result.provider_node_id, "trusted-node")
        self.assertEqual(result.candidates[0].rank, 1)

    def test_ranking_prefers_self_verified_signature(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="remote-node",
            trust_state="trusted",
            signature_status="signed_unverified_remote",
        )
        _add_service(
            store,
            provider="local-node",
            trust_state="trusted",
            signature_status="signed_self_verified",
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.provider_node_id, "local-node")

    def test_ranking_prefers_current_over_expired(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="expired-trusted",
            trust_state="privileged",
            expires=1_050,
        )
        _add_service(
            store,
            provider="current-unknown",
            trust_state="unknown",
            expires=1_300,
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.provider_node_id, "current-unknown")
        self.assertEqual(result.resolution_status, "limited")

    def test_unknown_limited_service_resolves_as_limited(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="unknown-node",
            trust_state="unknown",
            accepted_limited=True,
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.resolution_status, "limited")
        self.assertEqual(result.trust_state, "unknown")

    def test_blocked_provider_is_not_preferred(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="blocked-node",
            trust_state="blocked",
            signature_status="signed_self_verified",
            last_seen=1_099,
        )
        _add_service(
            store,
            provider="unknown-node",
            trust_state="unknown",
            signature_status="unsigned",
            last_seen=1_001,
        )

        result = resolve_service(store, "temperature", now=1_100)

        self.assertEqual(result.provider_node_id, "unknown-node")
        self.assertEqual(result.resolution_status, "limited")
        self.assertFalse(result.candidates[1].usable)

    def test_fully_qualified_service_name_resolves_without_migration(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            provider="pi01-id",
            service_name="temperature@local@mesh",
            trust_state="trusted",
        )

        result = resolve_service(
            store,
            "temperature@local@mesh",
            now=1_100,
        )

        self.assertEqual(result.resolution_status, "resolved")
        self.assertEqual(result.service_name, "temperature@local@mesh")


class ResolutionCliTests(unittest.TestCase):
    def test_cli_resolve_node_includes_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            _add_node(
                store,
                node_id="pi01-id",
                node_name="pi01@local@mesh",
                trust_state="trusted",
                signature_status="signed_unverified_remote",
                now=None,
            )
            store.save()
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--data-dir",
                        str(data_dir),
                        "--resolve-node",
                        "pi01@local@mesh",
                    ]
                )

            rendered = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("resolution_status", rendered)
            self.assertIn("trust_state", rendered)
            self.assertIn("signature_status", rendered)
            self.assertIn("pi01-id", rendered)
            self.assertFalse((data_dir / "trust.json").exists())

    def test_cli_resolve_service_includes_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            _add_service(
                store,
                provider="pi01-id",
                trust_state="trusted",
                signature_status="signed_unverified_remote",
                now=None,
            )
            store.save()
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--data-dir",
                        str(data_dir),
                        "--resolve-service",
                        "temperature",
                    ]
                )

            rendered = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("resolution_status", rendered)
            self.assertIn("provider_node_id", rendered)
            self.assertIn("/temperature", rendered)
            self.assertIn("http", rendered)
            self.assertIn("trust_state", rendered)
            self.assertIn("signature_status", rendered)

    def test_resolver_loads_old_awareness_without_trust_or_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            path = data_dir / "awareness.json"
            store = AwarenessStore(path=path)
            _add_node(
                store,
                node_id="pi01-id",
                node_name="pi01@local@mesh",
                now=None,
            )
            _add_service(store, provider="pi01-id", now=None)
            store.save()
            raw = json.loads(path.read_text(encoding="utf-8"))
            for entry in [*raw["nodes"], *raw["services"]]:
                entry.pop("trust_state")
                entry.pop("signature_status")
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = AwarenessStore.load(path)
            node = resolve_node(loaded, "pi01@local@mesh")
            service = resolve_service(loaded, "temperature")

            self.assertEqual(node.resolution_status, "resolved")
            self.assertEqual(node.trust_state, "unknown")
            self.assertEqual(node.signature_status, "signature_not_checked")
            self.assertEqual(service.resolution_status, "limited")
            self.assertEqual(service.signature_status, "signature_not_checked")


def _add_node(
    store: AwarenessStore,
    *,
    node_id: str,
    node_name: str,
    trust_state: str = "unknown",
    signature_status: str = "signature_not_checked",
    now: int | None = 1_001,
) -> None:
    created = 1_000 if now is not None else None
    store.update_from_knowledge_object(
        create_node_knowledge_object(
            origin=node_id,
            subject=node_name,
            payload={"node_id": node_id, "node_name": node_name},
            now=created,
        ),
        now=now,
        trust_state=trust_state,
        signature_status=signature_status,
    )


def _add_service(
    store: AwarenessStore,
    *,
    provider: str,
    service_name: str = "temperature",
    trust_state: str = "unknown",
    signature_status: str = "signature_not_checked",
    accepted_limited: bool = False,
    last_seen: int = 1_001,
    expires: int = 1_300,
    now: int | None = 1_001,
) -> None:
    created = 1_000 if now is not None else None
    store.update_from_knowledge_object(
        create_service_knowledge_object(
            origin=provider,
            service_name=service_name,
            payload={
                "service_name": service_name,
                "provider": provider,
                "endpoint": "/temperature",
                "protocol": "http",
            },
            now=created,
        ),
        now=now,
        trust_state=trust_state,
        accepted_limited=accepted_limited,
        signature_status=signature_status,
    )
    entry = store.get_service(provider, service_name)
    assert entry is not None
    entry.last_seen = last_seen if now is not None else entry.last_seen
    entry.expires = expires if now is not None else entry.expires


if __name__ == "__main__":
    unittest.main()
