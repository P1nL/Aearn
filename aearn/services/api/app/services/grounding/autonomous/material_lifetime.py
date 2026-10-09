"""Issuance bounds, not grants: never renew stored proof or transport authority.

The seven-day policy applies only to new finite course-material proofs. Every
deadline remains an independent upper bound; unknown/expired permission denies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

MaterialLifetimePolicy = Literal["source_material_24h_v1", "course_material_7d_v1"]
LEGACY_MATERIAL_POLICY: MaterialLifetimePolicy = "source_material_24h_v1"
COURSE_MATERIAL_POLICY: MaterialLifetimePolicy = "course_material_7d_v1"


def material_lifetime(policy: MaterialLifetimePolicy) -> timedelta:
    if policy == LEGACY_MATERIAL_POLICY:
        return timedelta(hours=24)
    if policy == COURSE_MATERIAL_POLICY:
        return timedelta(days=7)
    raise ValueError("unknown material lifetime policy")


def new_material_expiry(*, now: datetime, policy: MaterialLifetimePolicy,
                        policy_expires_at: datetime, policy_retention_until: datetime,
                        capture_retention_until: datetime, delegation_expires_at: datetime,
                        period_end: datetime) -> datetime:
    """Select the earliest known permission, retention, budget or policy bound.

    Inputs come from current, independently verified repository rows. This pure
    helper neither issues a grant nor bypasses provenance/current-source fences.
    All five bounds are mandatory: an absent permission must not mean infinity.
    """
    deadlines = (now, policy_expires_at, policy_retention_until,
                 capture_retention_until, delegation_expires_at, period_end)
    if any(not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None
           for d in deadlines):
        raise ValueError("material lifetime requires aware deadlines")
    now = now.astimezone(timezone.utc)
    expiry = min(now + material_lifetime(policy), *(d.astimezone(timezone.utc) for d in deadlines[1:]))
    if expiry <= now:
        raise ValueError("material permission expired")
    return expiry
