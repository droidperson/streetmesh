"""Tests for local StreetMesh service definitions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.services import (
    ServiceConfigError,
    ServiceDefinition,
    ServiceRegistry,
)


class ServiceRegistryTests(unittest.TestCase):
    def test_supports_static_service_definitions(self) -> None:
        registry = ServiceRegistry(
            [
                ServiceDefinition(
                    service_name="temperature",
                    capabilities=("current_temperature", "humidity"),
                    endpoint="/temperature",
                    protocol="http",
                    service_version="0.1",
                )
            ]
        )

        services = registry.list_local_services()

        self.assertEqual([service.service_name for service in services], ["temperature"])

    def test_loads_services_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "services.json"
            path.write_text(
                json.dumps(
                    {
                        "services": [
                            {
                                "service_name": "temperature",
                                "capabilities": ["humidity"],
                                "endpoint": "/temperature",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            registry = ServiceRegistry.load(path)

            service = registry.list_local_services()[0]
            self.assertEqual(service.service_name, "temperature")
            self.assertEqual(service.capabilities, ("humidity",))

    def test_no_configured_service_file_means_no_local_services(self) -> None:
        registry = ServiceRegistry.load(None)

        self.assertEqual(registry.list_local_services(), [])

    def test_missing_configured_service_file_is_rejected(self) -> None:
        with self.assertRaisesRegex(ServiceConfigError, "not found"):
            ServiceRegistry.load(Path("does-not-exist.json"))

    def test_creates_service_announcements_with_incrementing_sequences(self) -> None:
        registry = ServiceRegistry([ServiceDefinition(service_name="temperature")])

        first = registry.create_announcements(provider="node-a", now=1_000)[0]
        second = registry.create_announcements(provider="node-a", now=1_010)[0]

        self.assertEqual(first["seq"], 1)
        self.assertEqual(second["seq"], 2)
        self.assertEqual(first["payload"]["provider"], "node-a")
        self.assertEqual(first["expires"], 1_300)

    def test_rejects_duplicate_service_names(self) -> None:
        with self.assertRaisesRegex(ServiceConfigError, "duplicate"):
            ServiceRegistry(
                [
                    ServiceDefinition(service_name="temperature"),
                    ServiceDefinition(service_name="temperature"),
                ]
            )

    def test_rejects_invalid_static_service_definition(self) -> None:
        with self.assertRaisesRegex(ServiceConfigError, "service_name"):
            ServiceDefinition(service_name=" ")


if __name__ == "__main__":
    unittest.main()
