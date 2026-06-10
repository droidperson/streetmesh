"""Tests for StreetMesh review-mode policy decisions."""

from __future__ import annotations

import unittest

from streetmesh.policy import ReviewPolicy


class ReviewPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ReviewPolicy()

    def test_default_mode_is_review(self) -> None:
        self.assertEqual(self.policy.mode, "review")

    def test_unknown_node_is_accepted_as_awareness(self) -> None:
        decision = self.policy.decide({"type": "NODE"}, "unknown")

        self.assertEqual(decision.action, "accepted")
        self.assertTrue(decision.forward)

    def test_unknown_service_is_accepted_limited(self) -> None:
        decision = self.policy.decide({"type": "SERVICE"}, "unknown")

        self.assertEqual(decision.action, "accepted-limited")
        self.assertTrue(decision.forward)

    def test_unknown_gateway_is_quarantined(self) -> None:
        decision = self.policy.decide({"type": "GATEWAY"}, "unknown")

        self.assertEqual(decision.action, "quarantined")
        self.assertFalse(decision.forward)

    def test_blocked_origin_is_rejected(self) -> None:
        decision = self.policy.decide({"type": "NODE"}, "blocked")

        self.assertEqual(decision.action, "rejected")
        self.assertFalse(decision.forward)

    def test_revoked_origin_is_rejected(self) -> None:
        decision = self.policy.decide({"type": "SERVICE"}, "revoked")

        self.assertEqual(decision.action, "rejected")
        self.assertFalse(decision.forward)

    def test_trusted_service_is_accepted_normally(self) -> None:
        decision = self.policy.decide({"type": "SERVICE"}, "trusted")

        self.assertEqual(decision.action, "accepted")
        self.assertTrue(decision.forward)


if __name__ == "__main__":
    unittest.main()
