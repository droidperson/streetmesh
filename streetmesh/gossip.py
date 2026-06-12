"""Gossip forwarding policy for accepted remote Knowledge Objects."""

from __future__ import annotations

from copy import deepcopy
import logging
import time
from typing import Protocol

from .directory import DuplicateCache
from .protocol import (
    KnowledgeObjectError,
    encode_knowledge_object,
    evaluate_signature_status,
    validate_knowledge_object,
)
from .policy import ReviewPolicy
from .trust import TrustStore


LOGGER = logging.getLogger(__name__)


class GossipTransport(Protocol):
    def send_broadcast(self, data: bytes, *, port: int, host: str | None = None) -> int:
        """Broadcast encoded Knowledge Object bytes."""


class GossipForwarder:
    """Validate and forward eligible remote Knowledge Objects once."""

    def __init__(
        self,
        *,
        local_node_id: str,
        transport: GossipTransport,
        port: int,
        host: str | None = None,
        duplicate_cache: DuplicateCache | None = None,
        trust_store: TrustStore | None = None,
        policy: ReviewPolicy | None = None,
    ) -> None:
        self.local_node_id = local_node_id
        self.transport = transport
        self.port = port
        self.host = host
        self.duplicate_cache = (
            duplicate_cache if duplicate_cache is not None else DuplicateCache()
        )
        self.trust_store = trust_store
        self.policy = policy

    def forward(
        self,
        knowledge_object: dict[str, object],
        *,
        now: int | None = None,
    ) -> dict[str, object] | None:
        """Forward an eligible object with TTL reduced by one."""

        current_time = int(time.time() if now is None else now)
        ko_id = knowledge_object.get("ko_id")

        try:
            validate_knowledge_object(knowledge_object, now=current_time)
        except KnowledgeObjectError as exc:
            LOGGER.info(
                "Gossip not forwarded: ko_id=%s reason=invalid error=%s",
                ko_id,
                exc,
            )
            return None

        if knowledge_object.get("origin") == self.local_node_id:
            LOGGER.info("Gossip not forwarded: ko_id=%s reason=self-originated", ko_id)
            return None

        if self.trust_store is not None and self.policy is not None:
            trust_state = self.trust_store.get_state(knowledge_object.get("origin"))
            signature_status = evaluate_signature_status(
                knowledge_object,
                local_node_id=self.local_node_id,
            )
            decision = self.policy.decide(
                knowledge_object,
                trust_state,
                signature_status,
            )
            if not decision.forward:
                LOGGER.info(
                    "Gossip not forwarded: ko_id=%s reason=policy-%s trust_state=%s signature_status=%s",
                    ko_id,
                    decision.action,
                    trust_state,
                    decision.signature_status,
                )
                return None

        ttl = knowledge_object["ttl"]
        assert isinstance(ttl, int)
        if ttl <= 0:
            LOGGER.info(
                "Gossip not forwarded: ko_id=%s reason=ttl-exhausted ttl=%s",
                ko_id,
                ttl,
            )
            return None

        if not self.duplicate_cache.remember(ko_id, now=current_time):
            LOGGER.info("Gossip not forwarded: ko_id=%s reason=duplicate", ko_id)
            return None

        forwarded = deepcopy(knowledge_object)
        forwarded["ttl"] = ttl - 1
        self.transport.send_broadcast(
            encode_knowledge_object(forwarded, now=current_time),
            port=self.port,
            host=self.host,
        )
        LOGGER.info(
            "Gossip forwarded: ko_id=%s origin=%s ttl=%s forwarded_ttl=%s signature_status=%s",
            ko_id,
            knowledge_object.get("origin"),
            ttl,
            forwarded["ttl"],
            evaluate_signature_status(
                knowledge_object,
                local_node_id=self.local_node_id,
            ),
        )
        return forwarded
