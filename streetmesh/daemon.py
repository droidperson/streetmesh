"""StreetMesh daemon lifecycle."""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from .config import StreetMeshConfig
from .directory import AwarenessStore, DuplicateCache
from .gossip import GossipForwarder
from .identity import IdentityError, NodeIdentity, load_or_create_identity
from .name_bindings import NameBindingError, NameBindingRegistry
from .policy import ReviewPolicy
from .protocol import (
    KnowledgeObjectError,
    create_node_knowledge_object,
    decode_knowledge_object,
    encode_knowledge_object,
    evaluate_signature_status,
)
from .services import ServiceConfigError, ServiceRegistry
from .quarantine import QuarantineStore
from .transport_udp import Datagram, UDPTransport, UDPTransportError
from .trust import TrustStore, TrustStoreError


LOGGER = logging.getLogger(__name__)


class AnnouncementTransport(Protocol):
    def send_broadcast(self, data: bytes, *, port: int, host: str | None = None) -> int:
        """Broadcast bytes."""

    def receive(self, *, timeout: float | None = None) -> Datagram | None:
        """Receive bytes."""

    def close(self) -> None:
        """Close the transport."""


class StreetMeshDaemon:
    """StreetMesh daemon runtime for NODE announcements and gossip."""

    def __init__(
        self,
        config: StreetMeshConfig,
        *,
        transport_factory: Callable[[StreetMeshConfig], AnnouncementTransport] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._transport_factory = transport_factory or self._create_udp_transport
        self._clock = clock
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
            services = ServiceRegistry.load(self.config.node.services_file)
        except ServiceConfigError as exc:
            print(f"Service configuration error: {exc}")
            return 1

        try:
            trust_store = TrustStore.load(
                self.config.node.data_dir / "trust.json"
            )
        except TrustStoreError as exc:
            print(f"Trust store error: {exc}")
            return 1
        try:
            name_bindings = NameBindingRegistry.load(
                self.config.node.data_dir / "name_bindings.json"
            )
            for entry in trust_store.list_entries():
                if entry.node_name is None or entry.binding_status != "bound":
                    continue
                name_bindings.bind(
                    entry.node_name,
                    entry.node_id,
                    fingerprint=entry.fingerprint,
                    public_key_id=entry.public_key_id,
                    source="trusted" if entry.state == "trusted" else "manual",
                    notes="migrated from trust store",
                    save=False,
                )
            name_bindings.bind_local(
                identity.node_name,
                identity.node_id,
                fingerprint=identity.fingerprint,
                public_key_id=identity.public_key_id,
                save=False,
            )
            name_bindings.save()
        except NameBindingError as exc:
            print(f"Name binding error: {exc}")
            return 1
        policy = ReviewPolicy()
        quarantine = QuarantineStore.load(
            self.config.node.data_dir / "quarantine.json"
        )

        try:
            transport = self._transport_factory(self.config)
        except UDPTransportError as exc:
            print(f"UDP transport error: {exc}")
            return 1

        awareness = AwarenessStore.load(
            self.config.node.data_dir / "awareness.json",
            local_node_id=identity.node_id,
        )
        duplicate_cache = DuplicateCache()
        gossip = GossipForwarder(
            local_node_id=identity.node_id,
            transport=transport,
            port=self.config.node.udp_port,
            host=self.config.node.broadcast_host,
            trust_store=trust_store,
            policy=policy,
        )
        awareness.add_local_node(
            node_id=identity.node_id,
            node_name=identity.node_name,
            expires=int(time.time()) + 120,
            fingerprint=identity.fingerprint,
            public_key_id=identity.public_key_id,
            public_key_algorithm=identity.public_key_algorithm,
            public_key_status=identity.public_key_status,
        )
        awareness.save()

        LOGGER.info(
            "StreetMesh node started: node_name=%s node_id=%s udp_port=%s",
            identity.node_name,
            identity.node_id,
            self.config.node.udp_port,
        )
        LOGGER.info("Press Ctrl+C to stop StreetMesh.")

        try:
            self._run_runtime(
                identity,
                services,
                awareness,
                duplicate_cache,
                transport,
                gossip,
                trust_store,
                name_bindings,
                policy,
                quarantine,
            )
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
                **identity.public_identity_payload(),
            },
            seq=self._seq,
            signer=identity.create_signer(),
        )
        encoded = encode_knowledge_object(knowledge_object)
        transport.send_broadcast(
            encoded,
            port=self.config.node.udp_port,
            host=self.config.node.broadcast_host,
        )

        LOGGER.info(
            "NODE announcement broadcast: node_name=%s ko_id=%s seq=%s ttl=%s expires=%s signature_status=signed_self_verified",
            identity.node_name,
            knowledge_object["ko_id"],
            knowledge_object["seq"],
            knowledge_object["ttl"],
            knowledge_object["expires"],
        )
        return knowledge_object

    def announce_services_once(
        self,
        identity: NodeIdentity,
        services: ServiceRegistry,
        transport: AnnouncementTransport,
    ) -> list[dict[str, object]]:
        """Create and broadcast one claim for each registered local service."""

        announcements = services.create_announcements(
            provider=identity.node_id,
            signer=identity.create_signer(),
        )
        for knowledge_object in announcements:
            transport.send_broadcast(
                encode_knowledge_object(knowledge_object),
                port=self.config.node.udp_port,
                host=self.config.node.broadcast_host,
            )
            LOGGER.info(
                "SERVICE announced: service_name=%s provider=%s ko_id=%s seq=%s ttl=%s expires=%s signature_status=signed_self_verified",
                knowledge_object["subject"],
                identity.node_id,
                knowledge_object["ko_id"],
                knowledge_object["seq"],
                knowledge_object["ttl"],
                knowledge_object["expires"],
            )
        return announcements

    def receive_once(
        self,
        awareness: AwarenessStore,
        duplicate_cache: DuplicateCache,
        transport: AnnouncementTransport,
        *,
        gossip: GossipForwarder | None = None,
        trust_store: TrustStore | None = None,
        name_bindings: NameBindingRegistry | None = None,
        policy: ReviewPolicy | None = None,
        quarantine: QuarantineStore | None = None,
        local_signing_secret: str | None = None,
        timeout: float | None = None,
    ) -> None:
        datagram = transport.receive(timeout=timeout)
        if datagram is None:
            return

        try:
            knowledge_object = decode_knowledge_object(datagram.data)
        except KnowledgeObjectError as exc:
            LOGGER.warning(
                "Ignored invalid Knowledge Object from %s:%s: %s",
                datagram.address[0],
                datagram.address[1],
                exc,
            )
            return

        if not duplicate_cache.remember(knowledge_object.get("ko_id")):
            return

        signature_status = evaluate_signature_status(
            knowledge_object,
            local_node_id=awareness.local_node_id,
            local_signing_secret=local_signing_secret,
        )
        active_trust_store = trust_store or TrustStore()
        binding_status = "unknown"
        if knowledge_object.get("type") == "NODE":
            payload = knowledge_object.get("payload")
            node_name = payload.get("node_name") if isinstance(payload, dict) else None
            origin = knowledge_object.get("origin")
            if name_bindings is not None:
                binding_status = name_bindings.observe_claim(
                    node_name,
                    origin,
                    fingerprint=(
                        payload.get("fingerprint") if isinstance(payload, dict) else None
                    ),
                    public_key_id=(
                        payload.get("public_key_id") if isinstance(payload, dict) else None
                    ),
                )
            if binding_status in {"unknown", "unbound"}:
                binding_status = active_trust_store.binding_status_for_claim(
                    origin,
                    node_name,
                )
            if binding_status == "name_conflict":
                message = (
                    "Name binding conflict"
                    if name_bindings is not None
                    else "Trusted name conflict"
                )
                LOGGER.warning(
                    "%s: node_name=%s claimant_node_id=%s ko_id=%s",
                    message,
                    node_name,
                    origin,
                    knowledge_object.get("ko_id"),
                )
        elif knowledge_object.get("type") == "SERVICE":
            provider = awareness.get_by_node_id(
                str(knowledge_object.get("origin"))
            )
            if provider is not None:
                binding_status = provider.binding_status
            else:
                trust_entry = active_trust_store.get_entry(
                    knowledge_object.get("origin")
                )
                if trust_entry is not None:
                    binding_status = trust_entry.binding_status

        if (
            knowledge_object.get("origin") == awareness.local_node_id
            and signature_status != "signature_invalid"
        ):
            LOGGER.info(
                "Suppressed received self-announcement: node_id=%s ko_id=%s signature_status=%s",
                awareness.local_node_id,
                knowledge_object.get("ko_id"),
                signature_status,
            )
            return

        active_policy = policy or ReviewPolicy()
        trust_state = active_trust_store.get_state(knowledge_object.get("origin"))
        decision = active_policy.decide(
            knowledge_object,
            trust_state,
            signature_status,
        )
        LOGGER.info(
            "Policy %s: type=%s origin=%s trust_state=%s signature_status=%s reason=%s ko_id=%s",
            decision.action,
            knowledge_object.get("type"),
            knowledge_object.get("origin"),
            trust_state,
            decision.signature_status,
            decision.reason,
            knowledge_object.get("ko_id"),
        )

        if decision.action == "rejected":
            return
        if decision.action == "quarantined":
            if quarantine is not None:
                quarantine.add(
                    knowledge_object,
                    trust_state=trust_state,
                    reason=decision.reason,
                    signature_status=decision.signature_status,
                )
            return

        update = awareness.update_from_knowledge_object(
            knowledge_object,
            trust_state=trust_state,
            accepted_limited=decision.action == "accepted-limited",
            signature_status=decision.signature_status,
            binding_status=binding_status,
        )
        if update.status != "ignored":
            awareness.save()
            if gossip is not None and decision.forward:
                gossip.forward(knowledge_object)

    def _receive_until_next_announcement(
        self,
        awareness: AwarenessStore,
        duplicate_cache: DuplicateCache,
        transport: AnnouncementTransport,
        gossip: GossipForwarder | None = None,
    ) -> None:
        deadline = self._clock() + self.config.node.announce_interval
        while True:
            if awareness.expire_stale():
                awareness.save()
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            self.receive_once(
                awareness,
                duplicate_cache,
                transport,
                gossip=gossip,
                timeout=min(1.0, remaining),
            )

    def _run_runtime(
        self,
        identity: NodeIdentity,
        services: ServiceRegistry,
        awareness: AwarenessStore,
        duplicate_cache: DuplicateCache,
        transport: AnnouncementTransport,
        gossip: GossipForwarder,
        trust_store: TrustStore,
        name_bindings: NameBindingRegistry,
        policy: ReviewPolicy,
        quarantine: QuarantineStore,
    ) -> None:
        next_node_announcement = self._clock()
        next_service_announcement = self._clock()
        has_services = bool(services.list_local_services())

        while True:
            current_time = self._clock()
            if current_time >= next_node_announcement:
                announcement = self.announce_once(identity, transport)
                awareness.update_from_knowledge_object(
                    announcement,
                    trust_state="privileged",
                    signature_status=evaluate_signature_status(
                        announcement,
                        local_node_id=identity.node_id,
                        local_signing_secret=identity.signing_secret,
                    ),
                    binding_status="bound",
                )
                awareness.save()
                next_node_announcement = (
                    current_time + self.config.node.announce_interval
                )

            if has_services and current_time >= next_service_announcement:
                service_announcements = self.announce_services_once(
                    identity,
                    services,
                    transport,
                )
                for announcement in service_announcements:
                    awareness.update_from_knowledge_object(
                        announcement,
                        trust_state="privileged",
                        signature_status=evaluate_signature_status(
                            announcement,
                            local_node_id=identity.node_id,
                            local_signing_secret=identity.signing_secret,
                        ),
                        binding_status="bound",
                    )
                if service_announcements:
                    awareness.save()
                next_service_announcement = (
                    current_time + self.config.node.service_announce_interval
                )

            if awareness.expire_stale():
                awareness.save()

            next_deadline = next_node_announcement
            if has_services:
                next_deadline = min(next_deadline, next_service_announcement)
            timeout = min(1.0, max(0.0, next_deadline - self._clock()))
            self.receive_once(
                awareness,
                duplicate_cache,
                transport,
                gossip=gossip,
                trust_store=trust_store,
                name_bindings=name_bindings,
                policy=policy,
                quarantine=quarantine,
                local_signing_secret=identity.signing_secret,
                timeout=timeout,
            )

    @staticmethod
    def _create_udp_transport(config: StreetMeshConfig) -> UDPTransport:
        return UDPTransport(
            bind_host=config.node.bind_host,
            bind_port=config.node.udp_port,
            broadcast_host=config.node.broadcast_host,
        )
