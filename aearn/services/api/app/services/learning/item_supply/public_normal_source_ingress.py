"""Versioned PUBLIC normal/source structural preflight. No IO outside caller PG.

Frozen528/repair remains historical. This preflight never grants a source or
restores a phase: it only requires the reviewed append530 owners before jobs.
"""
from __future__ import annotations
import hashlib
from typing import Any
from app.services.learning.item_supply.persistent_pack_repair import NORMAL_RECEIVER_PINS

PUBLIC_NORMAL_RECEIVER_PINS = dict(NORMAL_RECEIVER_PINS)
PUBLIC_NORMAL_RECEIVER_PINS.update({
    "public.enforce_item_supply_shared_candidate_continuation()": "368c07a1950a76d042fb9fa142620e4c9ccec37ccb5597fa185f424207a55ca1",
    "item_supply_internal.enforce_persistent_pack_journal_insert()": "6cb924d2b8a396cf2bb2c01f7315e659eadbc41bdcd0eea386190a5e8886580d",
    "item_supply_internal.assert_persistent_normal_repair(jsonb)": "ff5c3fbe5a46b010f34870d36cfe387e62f212748a1ae7c3694f5004eea0b87e",
    "item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint)": "f16fb7d1eb82deb33ce1492db4faa56c8ad43cfc3a4086df6665f637583e488d",
    "item_supply_internal.public_native_source_current(jsonb)": "82dcdf136055421ab5c7f60f0606308abdb23d57214bfa83e0d22c92ad4447e2",
})

def require_public_normal_receivers(conn: Any) -> None:
    for signature,digest in PUBLIC_NORMAL_RECEIVER_PINS.items():
        row=conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig FROM pg_proc p WHERE p.oid=to_regprocedure(%s)",
            (signature,)).fetchone()
        if (row is None or row["prosecdef"] is not True or row["prokind"]!="f"
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
                or hashlib.sha256(row["prosrc"].replace("\r\n","\n").encode()).hexdigest()!=digest):
            raise ValueError("public_normal_530_exact_receiver_required")

