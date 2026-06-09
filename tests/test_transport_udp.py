"""Tests for StreetMesh UDP byte transport."""

from __future__ import annotations

import unittest

from streetmesh.transport_udp import (
    DEFAULT_UDP_PORT,
    MAX_PACKET_SIZE,
    UDPTransport,
    UDPTransportError,
)


class UDPTransportTests(unittest.TestCase):
    def test_default_port_constant_is_40404(self) -> None:
        self.assertEqual(DEFAULT_UDP_PORT, 40404)

    def test_sends_and_receives_bytes_on_localhost(self) -> None:
        sender = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        receiver = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        try:
            payload = b"streetmesh-bytes"

            sent = sender.send(payload, "127.0.0.1", receiver.address[1])
            datagram = receiver.receive(timeout=1.0)

            self.assertEqual(sent, len(payload))
            self.assertIsNotNone(datagram)
            assert datagram is not None
            self.assertEqual(datagram.data, payload)
            self.assertEqual(datagram.address[1], sender.address[1])
        finally:
            sender.close()
            receiver.close()

    def test_receive_returns_none_on_timeout(self) -> None:
        transport = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        try:
            self.assertIsNone(transport.receive(timeout=0.01))
        finally:
            transport.close()

    def test_rejects_outgoing_packets_larger_than_1200_bytes(self) -> None:
        transport = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        try:
            with self.assertRaisesRegex(UDPTransportError, "maximum size"):
                transport.send(b"x" * (MAX_PACKET_SIZE + 1), "127.0.0.1", 9)
        finally:
            transport.close()

    def test_rejects_non_bytes_packets(self) -> None:
        transport = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        try:
            with self.assertRaisesRegex(UDPTransportError, "must be bytes"):
                transport.send("not-bytes", "127.0.0.1", 9)  # type: ignore[arg-type]
        finally:
            transport.close()

    def test_logs_send_errors(self) -> None:
        transport = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        transport.close()

        with self.assertLogs("streetmesh.transport_udp", level="ERROR") as logs:
            with self.assertRaises(UDPTransportError):
                transport.send(b"bytes", "127.0.0.1", 9)

        self.assertIn("UDP send failed", logs.output[0])

    def test_broadcast_send_uses_configured_broadcast_host(self) -> None:
        sender = UDPTransport(
            bind_host="127.0.0.1",
            bind_port=0,
            broadcast_host="127.0.0.1",
        )
        receiver = UDPTransport(bind_host="127.0.0.1", bind_port=0)
        try:
            payload = b"broadcast-bytes"

            sent = sender.send_broadcast(payload, port=receiver.address[1])
            datagram = receiver.receive(timeout=1.0)

            self.assertEqual(sent, len(payload))
            self.assertIsNotNone(datagram)
            assert datagram is not None
            self.assertEqual(datagram.data, payload)
        finally:
            sender.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
