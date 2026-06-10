"""Simple review-mode policy for StreetMesh Knowledge Objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    ) -> PolicyDecision:
        if trust_state in {"blocked", "revoked"}:
            return PolicyDecision("rejected", False, f"origin-{trust_state}")

        object_type = knowledge_object.get("type")
        if trust_state == "quarantined":
            return PolicyDecision("quarantined", False, "origin-quarantined")

        if object_type in self._sensitive_types:
            return PolicyDecision(
                "quarantined",
                False,
                f"review-required-{str(object_type).lower()}",
            )

        if object_type == "NODE":
            return PolicyDecision("accepted", True, f"node-{trust_state}")

        if object_type == "SERVICE":
            if trust_state in self._trusted_states:
                return PolicyDecision("accepted", True, f"service-{trust_state}")
            if trust_state in self._limited_states:
                return PolicyDecision(
                    "accepted-limited",
                    True,
                    f"service-{trust_state}",
                )

        return PolicyDecision("rejected", False, "unsupported-policy-claim")
