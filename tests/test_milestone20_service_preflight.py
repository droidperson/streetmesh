"""Regression tests for Milestone 20 service access preflight."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from streetmesh.cli import main
from streetmesh.directory import AwarenessStore
from streetmesh.name_bindings import NameBindingRegistry, NameConflict
from streetmesh.preflight import NO_NETWORK_ACCESS, preflight_service
from streetmesh.protocol import (
    create_node_knowledge_object,
    create_service_knowledge_object,
)
from streetmesh.trust import TrustStore


SERVICE_NAME = "temperature"


class ServicePreflightTests(unittest.TestCase):
    def test_local_privileged_service_is_allowed(self) -> None:
        store = AwarenessStore(local_node_id="local-node")
        store.add_local_node(
            node_id="local-node",
            node_name="local@mesh",
            expires=1_300,
            now=1_000,
            fingerprint="a" * 64,
        )
        _add_service(
            store,
            "local-node",
            trust_state="privileged",
            binding_status="bound",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "allowed")
        self.assertTrue(result.provider_usable)
        self.assertEqual(result.provider_status, "current")
        self.assertEqual(result.access_action, NO_NETWORK_ACCESS)

    def test_trusted_bound_remote_service_is_allowed(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "allowed")
        self.assertEqual(result.trust_state, "trusted")
        self.assertEqual(result.binding_status, "bound")
        self.assertEqual(result.provider_fingerprint, "f" * 64)
        self.assertEqual(result.public_key_id, "future-key")

    def test_unknown_remote_service_is_limited(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "unknown-node",
            "unknown@local@mesh",
            trust_state="unknown",
            binding_status="unbound",
            accepted_limited=True,
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "limited")
        self.assertTrue(result.service_limited)

    def test_blocked_provider_is_denied(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "blocked-node",
            "blocked@local@mesh",
            trust_state="blocked",
            binding_status="bound",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "denied")
        self.assertIn("blocked", result.reason)
        self.assertFalse(result.provider_usable)

    def test_name_conflict_provider_is_not_allowed(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "conflict-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="name_conflict",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "conflict")
        self.assertFalse(result.provider_usable)

    def test_expired_service_is_reported(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
        )
        service = store.get_service("trusted-node", SERVICE_NAME)
        assert service is not None
        service.expires = 1_050

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "expired")
        self.assertEqual(result.service_status, "expired")

    def test_missing_service_is_not_found(self) -> None:
        result = preflight_service(AwarenessStore(), "missing", now=1_100)

        self.assertEqual(result.decision, "not_found")
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.access_action, NO_NETWORK_ACCESS)

    def test_service_without_provider_awareness_is_denied(self) -> None:
        store = AwarenessStore()
        _add_service(
            store,
            "missing-provider",
            trust_state="trusted",
            binding_status="bound",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "denied")
        self.assertEqual(result.provider_status, "missing")
        self.assertFalse(result.provider_usable)

    def test_multiple_unknown_providers_are_ambiguous(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "node-a",
            "a@local@mesh",
            trust_state="unknown",
            binding_status="unbound",
            accepted_limited=True,
        )
        _add_node_service(
            store,
            "node-b",
            "b@local@mesh",
            trust_state="unknown",
            binding_status="unbound",
            accepted_limited=True,
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "ambiguous")
        self.assertEqual(result.candidate_count, 2)

    def test_trusted_bound_provider_wins_over_unknown_provider(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "unknown-node",
            "unknown@local@mesh",
            trust_state="unknown",
            binding_status="unbound",
            accepted_limited=True,
            last_seen=1_099,
        )
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
            last_seen=1_001,
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "allowed")
        self.assertEqual(result.provider_node_id, "trusted-node")
        self.assertTrue(result.warnings)

    def test_conflicting_claimants_produce_warning(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
        )
        conflict = NameConflict(
            node_name="pi01@local@mesh",
            bound_node_id="trusted-node",
            claimant_node_id="other-node",
        )

        result = preflight_service(
            store,
            SERVICE_NAME,
            now=1_100,
            name_conflicts=[conflict],
        )

        self.assertEqual(result.decision, "allowed")
        self.assertTrue(
            any("Conflicting identities" in warning for warning in result.warnings)
        )

    def test_protocol_and_endpoint_are_reported(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.protocol, "http")
        self.assertEqual(result.endpoint, "/temperature")

    def test_missing_or_unknown_protocol_fails_safely(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
            protocol="future-protocol",
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "unsupported")
        self.assertEqual(result.access_action, NO_NETWORK_ACCESS)

    def test_missing_endpoint_is_denied_without_access(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
            endpoint=None,
        )

        result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "denied")
        self.assertIn("endpoint", result.reason)
        self.assertEqual(result.access_action, NO_NETWORK_ACCESS)

    def test_preflight_performs_no_network_access(self) -> None:
        store = AwarenessStore()
        _add_node_service(
            store,
            "trusted-node",
            "pi01@local@mesh",
            trust_state="trusted",
            binding_status="bound",
        )

        with (
            patch.object(socket, "create_connection") as connect,
            patch.object(socket, "socket") as socket_factory,
            patch.object(urllib.request, "urlopen") as urlopen,
        ):
            result = preflight_service(store, SERVICE_NAME, now=1_100)

        self.assertEqual(result.decision, "allowed")
        connect.assert_not_called()
        socket_factory.assert_not_called()
        urlopen.assert_not_called()


class ServicePreflightCliTests(unittest.TestCase):
    def test_cli_preflight_service_reports_decision_and_no_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = AwarenessStore(path=data_dir / "awareness.json")
            _add_node_service(
                store,
                "trusted-node",
                "pi01@local@mesh",
                trust_state="unknown",
                binding_status="unbound",
                now=None,
            )
            store.save()
            TrustStore.load(data_dir / "trust.json").bind_name(
                "trusted-node",
                "pi01@local@mesh",
                "trusted",
            )
            NameBindingRegistry(data_dir / "name_bindings.json").bind(
                "pi01@local@mesh",
                "trusted-node",
                source="trusted",
            )
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "--data-dir",
                        str(data_dir),
                        "--preflight-service",
                        SERVICE_NAME,
                    ]
                )

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("decision", rendered)
        self.assertIn("allowed", rendered)
        self.assertIn("pi01@local@mesh", rendered)
        self.assertIn("http", rendered)
        self.assertIn("/temperature", rendered)
        self.assertIn(NO_NETWORK_ACCESS, rendered)


def _add_node_service(
    store: AwarenessStore,
    provider: str,
    provider_name: str,
    *,
    trust_state: str,
    binding_status: str,
    accepted_limited: bool = False,
    protocol: str | None = "http",
    endpoint: str | None = "/temperature",
    last_seen: int = 1_001,
    now: int | None = 1_001,
) -> None:
    _add_node(
        store,
        provider,
        provider_name,
        trust_state=trust_state,
        binding_status=binding_status,
        now=now,
    )
    _add_service(
        store,
        provider,
        trust_state=trust_state,
        binding_status=binding_status,
        accepted_limited=accepted_limited,
        protocol=protocol,
        endpoint=endpoint,
        now=now,
    )
    service = store.get_service(provider, SERVICE_NAME)
    assert service is not None
    if now is not None:
        service.last_seen = last_seen


def _add_node(
    store: AwarenessStore,
    provider: str,
    provider_name: str,
    *,
    trust_state: str,
    binding_status: str,
    now: int | None,
) -> None:
    created = 1_000 if now is not None else None
    store.update_from_knowledge_object(
        create_node_knowledge_object(
            origin=provider,
            subject=provider_name,
            payload={
                "node_id": provider,
                "node_name": provider_name,
                "fingerprint": "f" * 64,
                "public_key_id": "future-key",
            },
            now=created,
        ),
        now=now,
        trust_state=trust_state,
        signature_status="signed_unverified_remote",
        binding_status=binding_status,
    )


def _add_service(
    store: AwarenessStore,
    provider: str,
    *,
    trust_state: str,
    binding_status: str,
    accepted_limited: bool = False,
    protocol: str | None = "http",
    endpoint: str | None = "/temperature",
    now: int | None = 1_001,
) -> None:
    created = 1_000 if now is not None else None
    payload: dict[str, object] = {
        "service_name": SERVICE_NAME,
        "provider": provider,
    }
    if protocol is not None:
        payload["protocol"] = protocol
    if endpoint is not None:
        payload["endpoint"] = endpoint
    store.update_from_knowledge_object(
        create_service_knowledge_object(
            origin=provider,
            service_name=SERVICE_NAME,
            payload=payload,
            now=created,
        ),
        now=now,
        trust_state=trust_state,
        accepted_limited=accepted_limited,
        signature_status="signed_unverified_remote",
        binding_status=binding_status,
    )


if __name__ == "__main__":
    unittest.main()
