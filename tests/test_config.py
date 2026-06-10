"""Tests for StreetMesh configuration loading."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from streetmesh.config import DEFAULT_NODE_NAME, ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_without_config_file(self) -> None:
        config = load_config()

        self.assertIsNone(config.path)
        self.assertEqual(config.node.node_name, DEFAULT_NODE_NAME)
        self.assertEqual(config.node.data_dir, Path("data"))
        self.assertEqual(config.node.announce_interval, 30)
        self.assertEqual(config.node.udp_port, 40404)
        self.assertEqual(config.node.service_announce_interval, 60)
        self.assertIsNone(config.node.services_file)

    def test_loads_json_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "node": {
                            "node_name": "alpha@local@mesh",
                            "data_dir": "state",
                            "announce_interval": 5,
                            "service_announce_interval": 15,
                            "services_file": "services.json",
                            "udp_port": 40405,
                            "bind_host": "127.0.0.1",
                            "broadcast_host": "127.0.0.1",
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.path, config_path)
            self.assertEqual(config.node.node_name, "alpha@local@mesh")
            self.assertEqual(config.node.data_dir, Path("state"))
            self.assertEqual(config.node.announce_interval, 5)
            self.assertEqual(config.node.udp_port, 40405)
            self.assertEqual(config.node.service_announce_interval, 15)
            self.assertEqual(config.node.services_file, Path("services.json"))
            self.assertEqual(config.node.bind_host, "127.0.0.1")
            self.assertEqual(config.node.broadcast_host, "127.0.0.1")

    def test_cli_overrides_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            override_data_dir = Path(temp_dir) / "override-data"
            config_path.write_text(
                json.dumps(
                    {
                        "node": {
                            "node_name": "alpha@local@mesh",
                            "data_dir": "state",
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                config_path,
                data_dir=override_data_dir,
                node_name="beta@local@mesh",
                announce_interval=9,
                service_announce_interval=19,
                services_file=Path("override-services.json"),
                udp_port=40406,
            )

            self.assertEqual(config.node.node_name, "beta@local@mesh")
            self.assertEqual(config.node.data_dir, override_data_dir)
            self.assertEqual(config.node.announce_interval, 9)
            self.assertEqual(config.node.udp_port, 40406)
            self.assertEqual(config.node.service_announce_interval, 19)
            self.assertEqual(
                config.node.services_file,
                Path("override-services.json"),
            )

    def test_empty_node_name_is_invalid(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(node_name=" ")

    def test_invalid_announce_interval_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "announce_interval"):
            load_config(announce_interval=0)

    def test_invalid_service_announce_interval_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "service_announce_interval"):
            load_config(service_announce_interval=0)


if __name__ == "__main__":
    unittest.main()
