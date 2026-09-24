from app.core.config import Settings
from app.services.grounding.autonomous.access_policy import AutonomousGates, check_access
from tests.grounding.rag_material_helpers import Authority, NOW, access


def test_independent_default_false_flags(monkeypatch):
    for key in ("RAG_SOURCE_DISCOVERY_ENABLED", "RAG_AUTO_INTAKE_ENABLED",
                "RAG_AUTO_ACTIVATION_ENABLED", "RAG_EVIDENCE_CONSUMER_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert not settings.rag_source_discovery_enabled
    assert not settings.rag_auto_intake_enabled
    assert not settings.rag_auto_activation_enabled
    assert not settings.rag_evidence_consumer_enabled
    for key, field in (("RAG_SOURCE_DISCOVERY_ENABLED", "discovery"),
                       ("RAG_AUTO_INTAKE_ENABLED", "intake"),
                       ("RAG_AUTO_ACTIVATION_ENABLED", "activation"),
                       ("RAG_EVIDENCE_CONSUMER_ENABLED", "evidence_consumer")):
        monkeypatch.setenv(key, "true")
        state = Settings()
        assert getattr(state, f"rag_{'source_discovery' if field == 'discovery' else 'auto_' + field if field != 'evidence_consumer' else 'evidence_consumer'}_enabled")
        monkeypatch.delenv(key)


def test_closed_port_no_resolver_invocation():
    authority = Authority()
    for action in ("discover", "probe", "store", "activate", "consume"):
        assert not check_access(access(action), gates=AutonomousGates(), resolver=authority, now=NOW).allowed
    assert authority.calls == 0
