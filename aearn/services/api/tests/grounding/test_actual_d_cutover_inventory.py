"""Cutover retains its target-state blocker; no actual-D deletion shortcut."""
from uuid import uuid4

import pytest

from app.services.tutor import cutover


class _UserRows:
    def fetchone(self):
        return {}


class _InventoryConnection:
    def __init__(self):
        self.queries = []

    def execute(self, query, parameters):
        self.queries.append((query, parameters))
        return _UserRows()


@pytest.mark.parametrize("proofs,bridges,blocked", [(1, 0, True), (0, 1, True), (0, 0, False)])
def test_conditional_actual_d_rows_are_cutover_target_state(monkeypatch, proofs, bridges, blocked):
    conn, user = _InventoryConnection(), uuid4()
    seen = []

    def private_counts(connection, user_id):
        seen.append((connection, user_id))
        return {"rag_assessment_source_evidence": proofs, "rag_actual_d_private_provenance": bridges}

    monkeypatch.setattr(cutover, "actual_d_private_counts", private_counts)
    service = cutover.HarnessCutoverService(conn)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_count", lambda *_args: 0)
    monkeypatch.setattr(service, "_legacy_thread_ids", lambda *_args: ())
    monkeypatch.setattr(service, "_checkpoint_inventory", lambda threads: cutover.CheckpointInventory(
        "not_configured", {}, (), threads))
    inventory = service._inventory(str(user))
    assert seen == [(conn, user)]
    assert inventory.has_target_state is blocked
    assert inventory.target_counts["rag_assessment_source_evidence"] == proofs
    assert inventory.target_counts["rag_actual_d_private_provenance"] == bridges
    assert all("DELETE" not in query and "purge" not in query for query, _args in conn.queries)
    assert "rag_assessment_source_evidence" not in cutover.CUTOVER_TARGET_TUTOR_TABLES
