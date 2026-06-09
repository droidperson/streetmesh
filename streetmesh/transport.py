"""Transport placeholders.

No networking is implemented in Milestone 0.
"""


class TransportUnavailable(RuntimeError):
    """Raised if transport behavior is requested before implementation."""


class NullTransport:
    """Transport stub that refuses network operations."""

    def start(self) -> None:
        raise TransportUnavailable("networking is not implemented yet")
