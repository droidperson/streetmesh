"""Local StreetMesh service definitions and SERVICE announcements."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from .protocol import create_service_knowledge_object


class ServiceConfigError(ValueError):
    """Raised when local service definitions are invalid."""


@dataclass(frozen=True)
class ServiceDefinition:
    service_name: str
    capabilities: tuple[str, ...] = ()
    endpoint: str | None = None
    protocol: str | None = None
    service_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.service_name, str) or not self.service_name.strip():
            raise ServiceConfigError("service_name must be a non-empty string")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.capabilities
        ):
            raise ServiceConfigError(
                "service capabilities must be a tuple of non-empty strings"
            )
        for key, value in (
            ("endpoint", self.endpoint),
            ("protocol", self.protocol),
            ("service_version", self.service_version),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ServiceConfigError(f"{key} must be a non-empty string")

    @classmethod
    def from_dict(cls, value: object) -> "ServiceDefinition":
        if not isinstance(value, dict):
            raise ServiceConfigError("service definition must be a JSON object")
        allowed = {
            "service_name",
            "capabilities",
            "endpoint",
            "protocol",
            "service_version",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ServiceConfigError(
                f"unknown service option(s): {', '.join(sorted(unknown))}"
            )

        service_name = _required_string(value, "service_name")
        raw_capabilities = value.get("capabilities", [])
        if not isinstance(raw_capabilities, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in raw_capabilities
        ):
            raise ServiceConfigError(
                "service capabilities must be a list of non-empty strings"
            )
        return cls(
            service_name=service_name,
            capabilities=tuple(raw_capabilities),
            endpoint=_optional_string(value, "endpoint"),
            protocol=_optional_string(value, "protocol"),
            service_version=_optional_string(value, "service_version"),
        )

    def payload(self, provider: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "service_name": self.service_name,
            "provider": provider,
        }
        if self.capabilities:
            payload["capabilities"] = list(self.capabilities)
        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint
        if self.protocol is not None:
            payload["protocol"] = self.protocol
        if self.service_version is not None:
            payload["service_version"] = self.service_version
        return payload


class ServiceRegistry:
    """Registered local services and their announcement sequences."""

    def __init__(self, services: Iterable[ServiceDefinition] = ()) -> None:
        self._services: dict[str, ServiceDefinition] = {}
        self._sequences: dict[str, int] = {}
        for service in services:
            self.register(service)

    @classmethod
    def load(cls, path: Path | None) -> "ServiceRegistry":
        if path is None:
            return cls()
        if not path.exists():
            raise ServiceConfigError(f"service file not found: {path}")
        try:
            with path.open("r", encoding="utf-8") as service_file:
                raw = json.load(service_file)
        except json.JSONDecodeError as exc:
            raise ServiceConfigError(f"invalid JSON in service file: {exc}") from exc
        except OSError as exc:
            raise ServiceConfigError(f"could not read service file: {exc}") from exc

        definitions = raw.get("services") if isinstance(raw, dict) else raw
        if not isinstance(definitions, list):
            raise ServiceConfigError(
                "service file must contain a list or an object with a services list"
            )
        return cls(ServiceDefinition.from_dict(value) for value in definitions)

    def register(self, service: ServiceDefinition) -> None:
        if service.service_name in self._services:
            raise ServiceConfigError(
                f"duplicate service_name: {service.service_name}"
            )
        self._services[service.service_name] = service
        self._sequences[service.service_name] = 0

    def list_local_services(self) -> list[ServiceDefinition]:
        return sorted(self._services.values(), key=lambda item: item.service_name)

    def create_announcements(
        self,
        *,
        provider: str,
        now: int | None = None,
        signing_secret: str | None = None,
    ) -> list[dict[str, Any]]:
        announcements = []
        for service in self.list_local_services():
            sequence = self._sequences[service.service_name] + 1
            self._sequences[service.service_name] = sequence
            announcements.append(
                create_service_knowledge_object(
                    origin=provider,
                    service_name=service.service_name,
                    payload=service.payload(provider),
                    seq=sequence,
                    now=now,
                    signing_secret=signing_secret,
                )
            )
        return announcements


def _required_string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ServiceConfigError(f"{key} must be a non-empty string")
    return result


def _optional_string(value: dict[str, object], key: str) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str) or not result.strip():
        raise ServiceConfigError(f"{key} must be a non-empty string")
    return result
