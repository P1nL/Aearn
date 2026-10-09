"""Finite opt-in routing only: no network, permissions, reviews or publication."""
from uuid import uuid4

import pytest

from tests.grounding.test_rag_c_owned_assessment_transport import control, control_config, host, scope, worker, Scope


def course_scopes():
    for url, hostname, path, subject, facets in host.OWNED_COURSE_TARGETS:
        yield Scope.from_wire({**scope().wire(), "policy_id": "source.course.test", "source_handle": "source.course.public",
            "dispatch_id": str(uuid4()), "url": url, "host": hostname, "path": path, "subject_id": subject, "facets": list(facets)})


def test_new_lane_is_five_exact_urls_with_separate_default_off_config(monkeypatch, tmp_path):
    monkeypatch.setattr(host.psycopg, "connect", lambda *a, **k: pytest.fail("pure transport test must not connect"))
    assert len(host.OWNED_COURSE_TARGETS) == 5
    for item in course_scopes():
        cfg = control_config(item, tmp_path, owned=False)
        cfg["owned_b1d_course_sources"] = True
        assert control.ControlRuntime(cfg, "dbname=" + host.OWNED_B1D_DATABASE).scope == item
        assert worker._scope_allowed(cfg, item)
        assert host.owned_course_scope_allowed(host._registered_scope(item))
        assert not host.owned_b1d_scope_allowed(host._registered_scope(item))
        assert not worker._scope_allowed({"owned_b1d_assessment": True}, item)
        with pytest.raises(ValueError, match="DATABASE_DENIED"):
            control.ControlRuntime({k: v for k, v in cfg.items() if k != "owned_b1d_course_sources"},
                                    "dbname=" + host.OWNED_B1D_DATABASE)
    assert not worker._scope_allowed({"owned_b1d_course_sources": True}, scope())


def test_community_capture_permission_does_not_become_assessment_or_quality_authority():
    wiki = next(t[0] for t in host.OWNED_COURSE_TARGETS if "wikibooks" in t[0])
    base = {"canonical_url": wiki, "origin": "community", "allowed_usages": ["main_teaching"]}
    assert host.owned_course_policy_allowed(base)
    for changed in ({"origin": "official"}, {"allowed_usages": ["assessment_evidence"]},
                    {"allowed_usages": ["main_teaching", "assessment_evidence"]},
                    {"canonical_url": wiki + "?oldid=other"}, {"allowed_usages": [[]]}):
        assert not host.owned_course_policy_allowed({**base, **changed})
    official = next(t[0] for t in host.OWNED_COURSE_TARGETS if "simple_stmts" in t[0])
    assert host.owned_course_policy_allowed({"canonical_url": official, "origin": "official", "allowed_usages": ["assessment_evidence"]})
    assert not host.owned_course_policy_allowed({"canonical_url": official, "origin": "community", "allowed_usages": ["main_teaching"]})
    alternative = {"canonical_url": "https://learnxinyminutes.com/python/", "origin": "tutorial", "allowed_usages": ["main_teaching"]}
    assert host.owned_course_policy_allowed(alternative)
    assert not host.owned_course_policy_allowed({**alternative, "allowed_usages": ["assessment_evidence"]})


def test_mutual_opt_ins_non_bool_wrong_db_and_mixed_scope_rejected():
    assert host.transport_database_allowed(host.OWNED_B1D_DATABASE, owned_b1d_course_sources=True)
    assert not host.transport_database_allowed("postgres", owned_b1d_course_sources=True)
    assert not host.transport_database_allowed(host.OWNED_B1D_DATABASE, owned_b1d_assessment=True, owned_b1d_course_sources=True)
    assert not host.transport_database_allowed(host.OWNED_B1D_DATABASE, owned_b1d_course_sources=1)
    item = next(course_scopes())
    for config in ({"owned_b1d_course_sources": 1}, {"owned_b1d_course_sources": True, "owned_b1d_assessment": True}):
        with pytest.raises(worker.WorkerDenied):
            worker._scope_allowed(config, item)
    changed = Scope.from_wire({**item.wire(), "subject_id": "route.sql" if item.subject_id == "route.python" else "route.python"})
    assert not worker._scope_allowed({"owned_b1d_course_sources": True}, changed)
