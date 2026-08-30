"""Tutor persistence 的 diagnostics 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class DiagnosticsPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def export_diagnostics(self, *, user_id: str, run_id: str) -> dict[str, object]:
        """Return diagnostic evidence only; canonical message content is never read."""
        run = self._conn.execute(
            "SELECT id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise TutorRunNotFound("tutor run not found")
        safe_run = self._projector.export({"run_id": run_id})
        events = self._conn.execute(
            "SELECT * FROM tutor_run_events WHERE run_id = %s ORDER BY event_sequence ASC",
            (run_id,),
        ).fetchall()
        traces = self._conn.execute(
            "SELECT * FROM tutor_run_traces WHERE run_id = %s ORDER BY event_from_sequence ASC, created_at ASC",
            (run_id,),
        ).fetchall()
        outbox = self._conn.execute(
            "SELECT * FROM tutor_memory_curation_outbox WHERE run_id = %s ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        proposals = self._conn.execute(
            """
            SELECT proposals.*
            FROM tutor_curation_proposals AS proposals
            JOIN tutor_memory_curation_outbox AS outbox ON outbox.id = proposals.outbox_id
            WHERE outbox.run_id = %s
            ORDER BY proposals.created_at ASC
            """,
            (run_id,),
        ).fetchall()
        exported_outbox: list[dict[str, object]] = []
        for row in outbox:
            header = self._projector.export({"outbox_id": str(row["id"]), "state": row["state"]})
            exported_outbox.append(
                {
                    "outbox_id": str(header.get("outbox_id") or "invalid_outbox"),
                    "state": str(header.get("state") or "invalid_state"),
                    "envelope": self._projector.export(row.get("envelope_json")),
                    "source_ids": self._projector.export({"source_ids": _as_list(row.get("source_ids_json"))}),
                    "source_hashes": self._projector.export({"source_hashes": _as_list(row.get("source_hashes_json"))}),
                }
            )
        exported_proposals: list[dict[str, object]] = []
        for row in proposals:
            header = self._projector.export(
                {
                    "proposal_id": str(row["id"]),
                    "outbox_id": str(row["outbox_id"]),
                    "kind": row["kind"],
                    "state": row["state"],
                }
            )
            exported_proposals.append(
                {
                    "proposal_id": str(header.get("proposal_id") or "invalid_proposal"),
                    "outbox_id": str(header.get("outbox_id") or "invalid_outbox"),
                    "kind": str(header.get("kind") or "invalid_proposal"),
                    "state": str(header.get("state") or "invalid_state"),
                    "provenance": self._projector.export(row.get("provenance_json")),
                    "payload": self._projector.export(row.get("payload_json")),
                }
            )
        return {
            "redaction_version": self._projector.version,
            "run_id": str(safe_run.get("run_id") or "invalid_run"),
            "events": [
                {
                    "event_id": event.event_id,
                    "event_sequence": event.event_sequence,
                    "kind": event.kind,
                    "input_revision": event.input_revision,
                    "payload": event.payload,
                }
                for event in (_event_from_row(row, projector=self._projector) for row in events)
            ],
            "traces": [
                {
                    "trace_id": trace.trace_id,
                    "kind": trace.kind,
                    "event_from_sequence": trace.event_from_sequence,
                    "event_to_sequence": trace.event_to_sequence,
                    "payload": trace.payload,
                }
                for trace in (_trace_from_row(row, projector=self._projector) for row in traces)
            ],
            "outbox": exported_outbox,
            "proposals": exported_proposals,
        }
