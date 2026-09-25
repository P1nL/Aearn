"""Offline per-hop actor/operator-policy checks; no DNS, DB or live egress."""
from __future__ import annotations

import pytest

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.hop_policy import CandidateHopPolicy
from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied, SafeFetcher
from tests.grounding.rag_material_helpers import Authority, NOW, access
from tests.grounding.test_rag_b_candidate_policy import CANDIDATE, FakeConnection, resolver
from tests.grounding.test_rag_b_safe_fetch import Connector, Egress, Resolver, response


class CurrentAuthority(Authority):
    generation = 2

    def resolve(self, request):
        return super().resolve(request).model_copy(update={"policy_generation": self.generation})


def rig(monkeypatch, *responses, authority=None, gates=None, policy=True):
    conn = FakeConnection()
    repo = resolver(monkeypatch, conn) if policy else None
    current = authority or CurrentAuthority()
    hop = CandidateHopPolicy(
        candidate=CANDIDATE, request=access("probe"),
        gates=gates if gates is not None else AutonomousGates(discovery=True),
        authority_resolver=current, policy_repository=repo, now_factory=lambda: NOW,
    )
    dns, connector, egress = Resolver(), Connector(*responses), Egress()
    fetcher = SafeFetcher(resolver=dns, connector=connector, egress=egress,
                          hop_policy=hop, offline_protocol_test=True)
    return fetcher, dns, connector, conn, current


async def denied(fetcher):
    with pytest.raises(SafeFetchDenied) as error:
        await fetcher.fetch(CANDIDATE.url)
    assert "https://" not in str(error.value)
    return error.value.code


@pytest.mark.asyncio
async def test_initial_target_and_authorized_redirect_are_rechecked(monkeypatch):
    fetcher, dns, connector, conn, authority = rig(
        monkeypatch, response(status=302, headers={"location": "/docs/next"}), response(),
    )
    result = await fetcher.fetch(CANDIDATE.url)
    assert result.hops == (CANDIDATE.url, "https://example.org/docs/next")
    assert dns.calls == ["example.org", "example.org"]
    assert len(connector.calls) == connector.closed == 2
    assert conn.calls >= 4 and authority.calls == 4  # before DNS and before connect


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["/private", "https://other.org/docs/next",
                                            "/docs/%2e%2e/private"])
async def test_redirect_outside_exact_host_path_is_rejected_before_dns(monkeypatch, location):
    fetcher, dns, connector, _, authority = rig(
        monkeypatch, response(status=302, headers={"location": location}),
    )
    assert await denied(fetcher) == "PROBE_POLICY_DENIED"
    assert dns.calls == ["example.org"]
    assert len(connector.calls) == connector.closed == 1
    assert authority.calls >= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "generation", "actor"])
async def test_policy_change_between_hops_fails_before_second_dns(monkeypatch, change):
    fetcher, dns, connector, conn, authority = rig(
        monkeypatch, response(status=302, headers={"location": "/docs/next"}),
    )
    original = connector.open

    async def changing_open(**kwargs):
        result = await original(**kwargs)
        if change == "revoked":
            conn.rules[0]["revoked_at"] = NOW
        elif change == "generation":
            authority.generation = 3
        else:
            conn.policy["enabled"] = False
        return result

    connector.open = changing_open
    assert await denied(fetcher) == "PROBE_POLICY_DENIED"
    assert dns.calls == ["example.org"]
    assert len(connector.calls) == connector.closed == 1


@pytest.mark.asyncio
async def test_initial_request_cannot_relabel_another_candidate(monkeypatch):
    fetcher, dns, connector, _, _ = rig(monkeypatch, response())
    with pytest.raises(SafeFetchDenied, match="PROBE_POLICY_DENIED"):
        await fetcher.fetch("https://example.org/docs/different")
    assert not dns.calls and not connector.calls


@pytest.mark.asyncio
async def test_revocation_during_dns_blocks_connection(monkeypatch):
    fetcher, dns, connector, conn, _ = rig(monkeypatch, response())
    original = dns.resolve

    async def changing_dns(hostname):
        addresses = await original(hostname)
        conn.rules[0]["revoked_at"] = NOW
        return addresses

    dns.resolve = changing_dns
    assert await denied(fetcher) == "PROBE_POLICY_DENIED"
    assert dns.calls == ["example.org"] and not connector.calls


@pytest.mark.asyncio
async def test_closed_or_missing_or_failing_authority_never_resolves_dns(monkeypatch):
    for options in ({"policy": False}, {"gates": AutonomousGates()}):
        fetcher, dns, connector, _, _ = rig(monkeypatch, response(), **options)
        assert await denied(fetcher) == "PROBE_POLICY_DENIED"
        assert not dns.calls and not connector.calls

    class BrokenAuthority:
        def resolve(self, request):
            raise RuntimeError("private-token-and-url")

    fetcher, dns, connector, _, _ = rig(monkeypatch, response(), authority=BrokenAuthority())
    assert await denied(fetcher) == "PROBE_POLICY_DENIED"
    assert not dns.calls and not connector.calls


@pytest.mark.asyncio
async def test_live_entry_stays_closed_before_any_policy_or_network(monkeypatch):
    fetcher, dns, connector, conn, authority = rig(monkeypatch, response())
    fetcher.offline_protocol_test = False
    assert await denied(fetcher) == "LIVE_EGRESS_UNVERIFIED"
    assert not dns.calls and not connector.calls and not conn.calls and not authority.calls
