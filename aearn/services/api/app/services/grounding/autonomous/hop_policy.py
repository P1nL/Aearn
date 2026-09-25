"""Per-hop probe authority adapter for B2's offline fetch protocol.

The caller supplies a current A authority resolver and a transaction-scoped
operator policy repository. A redirect target is a fresh candidate, not a grant
inherited from the initial URL. No network or DB connection is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .candidate_policy_repository import DiscoveryAccessDecision
from .contracts import SourceCandidate, revalidate
from .safe_fetch import _validated_url


class CandidateProbePolicy(Protocol):
    def check_probe(self, candidate: SourceCandidate, request: AccessRequest, *,
                    gates: AutonomousGates | None,
                    authority_resolver: AuthorityResolver | None,
                    now: datetime) -> DiscoveryAccessDecision: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CandidateHopPolicy:
    """Recheck the exact destination against A and operator policy each time.

    A's resolver must return current generation/actor/budget, and the policy
    repository must reread the current host/path rule. No cached decisions.
    """

    candidate: SourceCandidate
    request: AccessRequest
    gates: AutonomousGates | None
    authority_resolver: AuthorityResolver | None
    policy_repository: CandidateProbePolicy | None
    now_factory: Callable[[], datetime] = _utc_now

    def allows(self, url: str, *, initial: bool) -> bool:
        if self.policy_repository is None or self.authority_resolver is None:
            return False
        try:
            canonical, _ = _validated_url(url)
            original = revalidate(self.candidate, SourceCandidate)
            if initial and canonical != _validated_url(original.url)[0]:
                return False
            candidate = original.model_copy(update={"url": canonical})
            request = revalidate(self.request, AccessRequest)
            if request.action != "probe":
                return False
            return self.policy_repository.check_probe(
                candidate, request, gates=self.gates,
                authority_resolver=self.authority_resolver,
                now=self.now_factory(),
            ).allowed is True
        except Exception:
            # Resolver/DB failures, malformed URL or stale context cannot grant.
            return False
