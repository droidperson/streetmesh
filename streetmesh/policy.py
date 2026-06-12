"""Simple review-mode policy for StreetMesh Knowledge Objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .protocol import SignatureStatus
from .trust import TrustState


PolicyAction = Literal[
    "accepted",
    "accepted-limited",
    "quarantined",
    "rejected",
]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    forward: bool
    reason: str
    signature_status: SignatureStatus = "signature_not_checked"


class ReviewPolicy:
    """Default policy separating awareness from trusted usability."""

    mode = "review"
    _trusted_states = {"trusted", "privileged"}
    _limited_states = {"unknown", "observed", "candidate"}
    _sensitive_types = {"GATEWAY", "FEDERATION", "INTRODUCTION"}

    def decide(
        self,
        knowledge_object: dict[str, object],
        trust_state: TrustState,
        signature_status: SignatureStatus = "signature_not_checked",
    ) -> PolicyDecision:
        if signature_status == "signature_invalid":
            return PolicyDecision(
                "rejected",
                False,
                "invalid-verifiable-signature",
                signature_status,
            )

        if trust_state in {"blocked", "revoked"}:
            return PolicyDecision(
                "rejected",
                False,
                f"origin-{trust_state}",
                signature_status,
            )

        object_type = knowledge_object.get("type")
        if trust_state == "quarantined":
            return PolicyDecision(
                "quarantined",
                False,
                "origin-quarantined",
                signature_status,
            )

        if object_type in self._sensitive_types:
            return PolicyDecision(
                "quarantined",
                False,
                f"review-required-{str(object_type).lower()}",
                signature_status,
            )

        if object_type == "NODE":
            return PolicyDecision(
                "accepted",
                True,
                f"node-{trust_state}",
                signature_status,
            )

        if object_type == "SERVICE":
            if trust_state in self._trusted_states:
                return PolicyDecision(
                    "accepted",
                    True,
                    f"service-{trust_state}",
                    signature_status,
                )
            if trust_state in self._limited_states:
                return PolicyDecision(
                    "accepted-limited",
                    True,
                    f"service-{trust_state}",
                    signature_status,
                )

        return PolicyDecision(
            "rejected",
            False,
            "unsupported-policy-claim",
            signature_status,
        )
