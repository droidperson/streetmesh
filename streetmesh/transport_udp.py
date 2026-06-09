"""UDP byte transport for StreetMesh.

This module moves bytes only. It intentionally does not inspect or interpret
Knowledge Object semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import socket
from typing import TypeAlias


LOGGER = logging.getLogger(__name__)
DEFAULT_UDP_PORT = 40404
MAX_PACKET_SIZE = 1200
Address: TypeAlias = tuple[str, int]


class UDPTransportError(OSError):
    """Raised when UDP transport operations fail."""


@dataclass(frozen=True)
class Datagram:
    data: bytes
    address: Address


class UDPTransport:
    """Small UDP transport that sends and receives raw datagrams."""

    def __init__(
        self,
        *,
        bind_host: str = "0.0.0.0",
        bind_port: int = DEFAULT_UDP_PORT,
        broadcast_host: str = "255.255.255.255",
    ) -> None:
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.broadcast_host = broadcast_host
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            self._socket.bind((self.bind_host, self.bind_port))
        except OSError as exc:
            self._socket.close()
            LOGGER.error(
                "UDP bind failed on %s:%s: %s",
                self.bind_host,
                self.bind_port,
                exc,
            )
            raise UDPTransportError(str(exc)) from exc

    @property
    def address(self) -> Address:
        host, port = self._socket.getsockname()
        return str(host), int(port)

    def send(self, data: bytes, host: str, port: int) -> int:
        """Send raw bytes to a specific UDP host and port."""

        packet = _validate_packet(data)
        try:
            return self._socket.sendto(packet, (host, port))
        except OSError as exc:
            LOGGER.error("UDP send failed to %s:%s: %s", host, port, exc)
            raise UDPTransportError(str(exc)) from exc

    def send_broadcast(
        self,
        data: bytes,
        *,
        port: int = DEFAULT_UDP_PORT,
        host: str | None = None,
    ) -> int:
        """Broadcast raw bytes on the LAN."""

        return self.send(data, host or self.broadcast_host, port)

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        """Receive one UDP datagram, returning None on timeout."""

        previous_timeout = self._socket.gettimeout()
        self._socket.settimeout(timeout)
        try:
            data, address = self._socket.recvfrom(MAX_PACKET_SIZE)
        except TimeoutError:
            return None
        except socket.timeout:
            return None
        except OSError as exc:
            LOGGER.error("UDP receive failed: %s", exc)
            raise UDPTransportError(str(exc)) from exc
        finally:
            self._socket.settimeout(previous_timeout)

        host, port = address
        return Datagram(data=data, address=(str(host), int(port)))

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> "UDPTransport":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _validate_packet(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise UDPTransportError("UDP packet data must be bytes")
    if len(data) > MAX_PACKET_SIZE:
        raise UDPTransportError(
            f"UDP packet exceeds maximum size of {MAX_PACKET_SIZE} bytes"
        )
    return data
