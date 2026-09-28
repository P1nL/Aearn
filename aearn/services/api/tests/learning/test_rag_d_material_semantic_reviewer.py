"""D reviewer standalone import and one-shot protocol with no real provider."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_clean_interpreter_reviewer_and_lazy_tutor_exports() -> None:
    code = """
from app.core.config import Settings
from app.services.learning.material_semantics import MaterialReviewRequest, PrimaryMaterialSemanticReviewer
from app.services.llm.llm_client import LLMJsonResponse

class Fake:
    def complete_json(self, messages, **kwargs):
        assert kwargs['max_tokens'] == 256 and kwargs['thinking_mode'] == 'disabled'
        return LLMJsonResponse(content={'verdict':'consistent','reason_code':'supported'}, model='fake')

request = MaterialReviewRequest.build(run_id='00000000-0000-0000-0000-000000000001',
    input_revision=1, selection_digest='a'*64, parent_content_hash='b'*64,
    candidate_digest='c'*64, authority={'facet':'where_details','meaning':'SQL filtering'},
    candidate={'pace_summary':'Practice SQL WHERE filtering.'})
receipt = PrimaryMaterialSemanticReviewer(Settings(llm_type='disabled'), Fake()).review(request)
assert receipt.verdict.verdict == 'consistent'
from app.services.tutor import PrimaryTutorProviderGateway, TutorHarnessService, TutorRunLoop
assert PrimaryTutorProviderGateway.__name__ == 'PrimaryTutorProviderGateway'
assert TutorHarnessService.__name__ == 'TutorHarnessService'
assert TutorRunLoop.__name__ == 'TutorRunLoop'
print('standalone reviewer ok')
"""
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "LLM_TYPE": "disabled"}
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "standalone reviewer ok" in result.stdout


def test_deepseek_chat_wire_has_closed_verdict_contract_without_schema_transport() -> None:
    import json
    from typing import Any

    from app.core.config import Settings
    from app.services.learning.material_semantics import (
        MaterialReviewRequest, PrimaryMaterialSemanticReviewer, ReviewVerdict,
    )
    from app.services.llm.llm_client import OpenAICompatibleClient

    captured: dict[str, Any] = {}

    def transport(_url: str, _headers: Any, payload: Any, _timeout: float) -> dict[str, object]:
        captured.update(payload)
        return {"choices": [{"message": {"content": json.dumps({
            "verdict": "inconsistent", "reason_code": "facet_meaning_mismatch",
        })}}], "model": "deepseek-flash", "usage": {
            "prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
        }}

    settings = Settings(llm_type="deepseek", deepseek_api_key="test-key",
                        deepseek_base_url="https://api.deepseek.com/v1",
                        deepseek_model="deepseek-chat")
    request = MaterialReviewRequest.build(
        run_id="00000000-0000-0000-0000-000000000001", input_revision=1,
        selection_digest="a" * 64, parent_content_hash="b" * 64,
        candidate_digest="c" * 64,
        authority={"subject": "route.sql", "facet": "where_details",
                   "meaning": "SQL filtering clause"},
        candidate={"pace_summary": "Missing the learner location for WHERE details"},
    )
    client = OpenAICompatibleClient(settings, transport=transport, max_http_attempts=1)
    receipt = PrimaryMaterialSemanticReviewer(settings, client).review(request)
    assert receipt.verdict.verdict is ReviewVerdict.INCONSISTENT
    assert receipt.usage is not None and receipt.usage.total_tokens == 17
    wire = captured["messages"]
    assert isinstance(wire, list)
    system = wire[0]["content"]
    assert "consistent/supported" in system
    assert "inconsistent/facet_meaning_mismatch" in system
    assert "uncertain/insufficient_context" in system
    assert '{"verdict":"uncertain","reason_code":"insufficient_context"}' in system
    assert captured["response_format"] == {"type": "json_object"}
