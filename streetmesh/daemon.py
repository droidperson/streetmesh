"""StreetMesh daemon lifecycle."""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from .config import StreetMeshConfig
from .identity import IdentityError, NodeIdentity, load_or_create_identity
from .protocol import create_node_knowledge_object, encode_knowledge_object
from .transport_udp import UDPTransport, UDPTransportError


LOGGER = logging.getLogger(__name__)


class AnnouncementTransport(Protocol):
    def send_broadcast(self, data: bytes, *, port: int, host: str | None = None) -> int:
        """Broadcast bytes."""

    def close(self) -> None:
        """Close the transport."""


class StreetMeshDaemon:
    """StreetMesh daemon runtime for local NODE announcements."""

    def __init__(
        self,
        config: StreetMeshConfig,
        *,
        transport_factory: Callable[[StreetMeshConfig], AnnouncementTransport] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport_factory = transport_factory or self._create_udp_transport
        self._sleep = sleep
        self._seq = 0

    def run(self) -> int:
        try:
            identity = load_or_create_identity(
                self.config.node.data_dir,
                self.config.node.node_name,
            )
        except IdentityError as exc:
            print(f"Identity error: {exc}")
            return 1

        try:
            transport = self._transport_factory(self.config)
        except UDPTransportError as exc:
            print(f"UDP transport error: {exc}")
            return 1

        LOGGER.info(
            "StreetMesh node started: node_name=%s node_id=%s udp_port=%s",
            identity.node_name,
            identity.node_id,
            self.config.node.udp_port,
        )
        LOGGER.info("Press Ctrl+C to stop StreetMesh.")

        try:
            while True:
                self.announce_once(identity, transport)
                self._sleep(self.config.node.announce_interval)
        except KeyboardInterrupt:
            LOGGER.info("StreetMesh shutdown requested; stopping cleanly.")
            return 0
        finally:
            transport.close()

    def announce_once(
        self,
        identity: NodeIdentity,
        transport: AnnouncementTransport,
    ) -> dict[str, object]:
        """Create and broadcast one NODE announcement."""

        self._seq += 1
        knowledge_object = create_node_knowledge_object(
            origin=identity.node_id,
            subject=identity.node_name,
            payload={
                "node_id": identity.node_id,
                "node_name": identity.node_name,
                "fingerprint": identity.fingerprint,
            },
            seq=self._seq,
        )
        encoded = encode_knowledge_object(knowledge_object)
        transport.send_broadcast(
            encoded,
            port=self.config.node.udp_port,
            host=self.config.node.broadcast_host,
        )

        LOGGER.info(
            "NODE announcement broadcast: node_name=%s ko_id=%s seq=%s ttl=%s expires=%s",
            identity.node_name,
            knowledge_object["ko_id"],
            knowledge_object["seq"],
            knowledge_object["ttl"],
            knowledge_object["expires"],
        )
        return knowledge_object

    @staticmethod
    def _create_udp_transport(config: StreetMeshConfig) -> UDPTransport:
        return UDPTransport(
            bind_host=config.node.bind_host,
            bind_port=config.node.udp_port,
            broadcast_host=config.node.broadcast_host,
        )
