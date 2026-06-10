"""Persistence for claims held for local policy review."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any


class QuarantineStore:
    """Append-only-by-ko_id storage for quarantined claims."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._claims: dict[str, dict[str, Any]] = {}

    @classmethod
    def load(cls, path: Path) -> "QuarantineStore":
        store = cls(path)
        if not path.exists():
            return store
        try:
            with path.open("r", encoding="utf-8") as quarantine_file:
                raw = json.load(quarantine_file)
        except (json.JSONDecodeError, OSError):
            return store
        claims = raw.get("claims") if isinstance(raw, dict) else None
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict) and isinstance(claim.get("ko_id"), str):
                    store._claims[claim["ko_id"]] = claim
        return store

    def add(
        self,
        knowledge_object: dict[str, Any],
        *,
        trust_state: str,
        reason: str,
        now: int | None = None,
    ) -> None:
        ko_id = knowledge_object.get("ko_id")
        if not isinstance(ko_id, str):
            return
        self._claims[ko_id] = {
            "ko_id": ko_id,
            "origin": knowledge_object.get("origin"),
            "type": knowledge_object.get("type"),
            "trust_state": trust_state,
            "reason": reason,
            "received": int(time.time() if now is None else now),
            "knowledge_object": knowledge_object,
        }
        self.save()

    def list_claims(self) -> list[dict[str, Any]]:
        return sorted(self._claims.values(), key=lambda claim: claim["ko_id"])

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as quarantine_file:
            json.dump(
                {"claims": self.list_claims()},
                quarantine_file,
                indent=2,
                sort_keys=True,
            )
            quarantine_file.write("\n")
