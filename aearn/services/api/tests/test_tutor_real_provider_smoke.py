from __future__ import annotations

import os

import pytest

from app.services.tutor.context_eval_smoke import main


pytestmark = pytest.mark.real_provider


@pytest.mark.skipif(
    os.getenv("TUTOR_REAL_PROVIDER_SMOKE") != "1",
    reason="set TUTOR_REAL_PROVIDER_SMOKE=1 and configure the provider explicitly",
)
def test_tutor_context_governance_real_provider_smoke() -> None:
    assert main() == 0
