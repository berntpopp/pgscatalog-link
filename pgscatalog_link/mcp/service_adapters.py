"""Process-wide dependency-injection registry for the PGS Catalog service.

The running server registers a concrete :class:`PgsService` at startup; tests inject
one over a respx-mocked client. An unregistered service is an ``internal`` error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgscatalog_link.exceptions import InternalError

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from pgscatalog_link.service import PgsService

_service: PgsService | None = None


def get_pgs_service() -> PgsService:
    """Return the registered :class:`PgsService` or raise ``InternalError``."""
    if _service is None:
        raise InternalError(
            "PGS Catalog service is not initialised; the server must register it at startup.",
            recovery_action="switch_tool",
        )
    return _service


def set_pgs_service(service: PgsService | None) -> None:
    """Register (or clear) the process-wide service. Used by the server and tests."""
    global _service
    _service = service
