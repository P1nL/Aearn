"""Service-owned Tutor Harness provider, port, and run-loop boundaries.

The package exports are lazy: context-budget/provider-request modules import
Tutor submodules while their own definitions are still being initialized.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
    from app.services.tutor.run_loop import TutorHarnessService, TutorRunLoop

__all__ = ["PrimaryTutorProviderGateway", "TutorHarnessService", "TutorRunLoop"]


def __getattr__(name: str) -> Any:
    if name == "PrimaryTutorProviderGateway":
        from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
        return PrimaryTutorProviderGateway
    if name in {"TutorHarnessService", "TutorRunLoop"}:
        from app.services.tutor.run_loop import TutorHarnessService, TutorRunLoop
        return {"TutorHarnessService": TutorHarnessService, "TutorRunLoop": TutorRunLoop}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
