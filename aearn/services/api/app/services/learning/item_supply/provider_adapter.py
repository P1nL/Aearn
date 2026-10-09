"""One program-owned JSON call; transport retries are explicit reservation bounds."""
from __future__ import annotations

import math
from uuid import UUID, uuid4

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1
from app.services.learning.item_supply.generation_contracts import (
    GenerationLimitsV2, ProviderGenerationV2, ProviderReceiptV2, ProviderUsageV2,
)
from app.services.llm.contracts import LLMUsage
from app.services.llm.llm_client import (
    JsonTransport, LLMInvalidResponseError, OpenAICompatibleClient,
)

GENERATION_PROMPT_VERSION = "item_author.public_material.v2"
GENERATION_ADAPTER_VERSION = "openai_compatible.v2"


class ProviderGenerationFailed(RuntimeError):
    def __init__(self, receipt: ProviderReceiptV2) -> None:
        super().__init__("provider_failed")
        self.receipt = receipt


def response_usage(usage: LLMUsage | None, *, attempt_bound: int) -> ProviderUsageV2:
    # With retries the final response does not cover failed, potentially billed calls.
    return ProviderUsageV2(
        state=("known" if attempt_bound == 1 and usage is not None
               and usage.input_tokens is not None and usage.output_tokens is not None else "unknown"),
        input_tokens=usage.input_tokens if usage else None,
        cached_input_tokens=usage.cached_input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        reasoning_tokens=usage.reasoning_tokens if usage else None,
    )


class OpenAICompatibleGenerationProvider:
    def __init__(self, settings: Settings, *, max_http_attempts: int = 1,
                 transport: JsonTransport | None = None) -> None:
        self._client = OpenAICompatibleClient(
            settings, transport=transport, max_http_attempts=max_http_attempts,
        )
        self._attempt_bound = max_http_attempts
        self._settings = settings.model_copy(deep=True)
        self._transport = transport
        self._provider = str(settings.llm_provider_type)
        self._model = self._client.model
        # Validate program config before any IO; provider JSON cannot set these.
        self._receipt(model=self._model, usage=None, success=False)

    @property
    def provider_key(self) -> str:
        return self._provider

    @property
    def configured_model(self) -> str:
        return self._model

    @property
    def request_attempt_bound(self) -> int:
        return self._attempt_bound

    def _receipt(self, *, model: str, usage: LLMUsage | None,
                 success: bool, run_id: UUID | None = None) -> ProviderReceiptV2:
        return ProviderReceiptV2(
            provider=self._provider, provider_version=GENERATION_ADAPTER_VERSION,
            configured_model=self._model, model=model,
            prompt_version=GENERATION_PROMPT_VERSION,
            run_id=run_id if run_id is not None else uuid4(),
            request_attempt_bound=self.request_attempt_bound,
            actual_requests=1 if success and self.request_attempt_bound == 1 else None,
            usage=response_usage(usage, attempt_bound=self.request_attempt_bound), mode="provider",
        )

    def generate(self, *, messages: tuple[dict[str, str], ...], limits: GenerationLimitsV2,
                 timeout_seconds: float) -> ProviderGenerationV2:
        run_id = uuid4()
        try:
            if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                raise ValueError("invalid timeout")
            # Core resolves max(configured, requested), not min. Bound BOTH values
            # on a call-local client; do not mutate global Settings or LLM core.
            client = OpenAICompatibleClient(
                self._settings.model_copy(update={"llm_timeout_seconds": timeout_seconds}),
                transport=self._transport, max_http_attempts=self.request_attempt_bound,
            )
            response = client.complete_json(
                messages, temperature=0.0, max_tokens=limits.max_output_tokens,
                timeout_seconds=timeout_seconds,
                output_schema=LearningItemSourceV1.model_json_schema(),
                schema_name="item_candidate_source_v1", thinking_mode="disabled",
                capture_provider_body=False,
            )
            receipt = self._receipt(
                model=response.model, usage=response.usage, success=True, run_id=run_id,
            )
            return ProviderGenerationV2(payload=response.content, receipt=receipt)
        except LLMInvalidResponseError as exc:
            try:
                receipt = self._receipt(
                    model=exc.model or self._model, usage=exc.usage, success=False, run_id=run_id,
                )
            except ValueError:
                receipt = self._receipt(model=self._model, usage=None, success=False, run_id=run_id)
            raise ProviderGenerationFailed(receipt) from None
        except Exception:
            raise ProviderGenerationFailed(self._receipt(
                model=self._model, usage=None, success=False, run_id=run_id,
            )) from None
