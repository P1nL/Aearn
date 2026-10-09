from hashlib import sha256
from pathlib import Path
import re

from app.db.schema import SCHEMA_FRAGMENT_NAMES


SCHEMA = Path(__file__).resolve().parents[2] / "app/db/schema"


def test_506_pins_full_bodies_and_only_renames_ambiguous_sql_alias():
    legacy = (SCHEMA / "503_rag_actual_d_private_lifecycle.sql").read_text(encoding="utf8")
    migration = (SCHEMA / "506_rag_actual_d_private_insert_alias.sql").read_text(encoding="utf8")
    old_match = re.search(
        r"CREATE OR REPLACE FUNCTION rag_actual_d_private_insert\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
        legacy, re.S,
    )
    new_match = re.search(r"repaired_source constant text := \$body\$(.*?)\$body\$;", migration, re.S)
    assert old_match is not None and new_match is not None
    old, new = old_match.group(1), new_match.group(1)
    ambiguous = (
        "JOIN rag_assessment_source_evidence e ON e.id=r.assessment_evidence_id\n"
        "      WHERE a.id=NEW.independent_admission_id AND e.private_user_id IS NOT NULL"
    )
    fixed = (
        "JOIN rag_assessment_source_evidence private_evidence ON private_evidence.id=r.assessment_evidence_id\n"
        "      WHERE a.id=NEW.independent_admission_id AND private_evidence.private_user_id IS NOT NULL"
    )
    assert old.count(ambiguous) == 1
    assert new == old.replace(ambiguous, fixed)
    assert sha256(old.encode()).hexdigest() in migration
    assert migration.count(sha256(new.encode()).hexdigest()) == 2
    assert "actual.prosecdef" in migration and "actual.proconfig IS NOT NULL" in migration


def test_506_is_additive_last_fragment():
    assert SCHEMA_FRAGMENT_NAMES[-2:] == (
        "505_learning_item_diagnostic_blind_admission.sql",
        "506_rag_actual_d_private_insert_alias.sql",
    )
