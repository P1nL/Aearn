"""Fixed server-owned KC counterexample DATA; never admission authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID
from pydantic import Field
from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import LearningItemKnowledgeCheckContentV1, LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

CONTROLLED_EXPERIMENT_KEY = "kc-rebinding-wrong-explanation-v1"
CONTROLLED_WRONG_EXPLANATION: Final = "执行 price = 8 后，price 会自动恢复成先前的 6，当前 price 仍为 6；变量再次赋值不会改变当前绑定值。"
CONTROLLED_PROGRAM = "price = 6\nqty = 3\ntotal = price * qty\nprice = 8\nreceipt = total + 1\nprint(total, receipt)"


class ControlledCounterexampleContextV1(StorageContract):
    schema_version: Literal["controlled_kc_counterexample_context_v1"] = "controlled_kc_counterexample_context_v1"
    experiment_key: Literal["kc-rebinding-wrong-explanation-v1"] = "kc-rebinding-wrong-explanation-v1"
    rule_version: Literal["kc_rebinding_wrong_explanation_v1"] = "kc_rebinding_wrong_explanation_v1"
    target: Literal["python-kc-binding-v1"] = "python-kc-binding-v1"
    slot: Literal["practice-1"] = "practice-1"
    seed: Literal[24] = 24
    wrong_explanation: Literal["执行 price = 8 后，price 会自动恢复成先前的 6，当前 price 仍为 6；变量再次赋值不会改变当前绑定值。"] = CONTROLLED_WRONG_EXPLANATION
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False

    @property
    def context_hash(self) -> str:
        return canonical_hash(checked_model(self,ControlledCounterexampleContextV1).model_dump(mode="json"))

    @property
    def rule_hash(self) -> str:
        return canonical_hash({"rule":self.rule_version,"field":"/private/content/answer_explanation_markdown",
            "program":CONTROLLED_PROGRAM,"wrong_explanation":self.wrong_explanation})

    def check_request(self, request: GenerationRequestV2) -> None:
        from app.services.learning.item_supply.finite_candidate_factory import (
            FLEXIBLE_FACTORY_VERSION, allocation_from_blueprint, check_finite_public_request,
        )
        from app.services.learning.item_supply.shared_pipeline_contracts import native_request
        context = checked_model(self,ControlledCounterexampleContextV1)
        request,target = native_request(request)
        check_finite_public_request(request)
        allocation,seed = allocation_from_blueprint(request.blueprint,target.target_id)
        if (target.target_id != context.target or request.blueprint.version != FLEXIBLE_FACTORY_VERSION
                or allocation.variant_id != context.target+":practice-1" or allocation.family_id != context.target+":diagnose"
                or seed != 24 or request.public_template is None or request.public_template.kind.value != "knowledge_check"
                or CONTROLLED_PROGRAM not in getattr(request.public_template.content,"prompt_markdown","")
                or request.demand_binding is not None or request.profile.values.discussion_rounds < 2
                or request.profile.values.revision_rounds < 1 or request.profile.values.investigation_rounds < 1
                or request.limits.max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS):
            raise ValueError("controlled exact public KC seed24/program required")

    def check_source(self, source: LearningItemSourceV1) -> None:
        if getattr(source.private.content,"answer_explanation_markdown",None) != self.wrong_explanation:
            raise ValueError("controlled original output constraint not preserved")

    @property
    def provider_payload(self) -> dict[str,object]:
        return {"context_version":self.schema_version,"experiment_key":self.experiment_key,
            "rule_version":self.rule_version,"rule_hash":self.rule_hash,"context_hash":self.context_hash,
            "fixed_field":"/private/content/answer_explanation_markdown","fixed_value":self.wrong_explanation,
            "purpose":"controlled_counterexample_not_production_acceptance","publication_enabled":False}


CONTROLLED_V2_EXPERIMENT_KEY = "kc-linked-name-refutation-wrong-rationale-v2"
CONTROLLED_V2_WRONG_EXPLANATION: Final = "对整数执行 saved = source 会建立两个名字的永久联动；source 从 4 重绑定到 9 后，saved 必须同步变为 9，程序实际输出 9 9。"
CONTROLLED_V2_PROGRAM = "source = 4\nsaved = source\nsource = 9\nprint(source, saved)"


class ControlledCounterexampleContextV2(StorageContract):
    """Independent closed V2; neither widens nor subclasses the historical V1."""
    schema_version: Literal["controlled_kc_counterexample_context_v2"] = "controlled_kc_counterexample_context_v2"
    experiment_key: Literal["kc-linked-name-refutation-wrong-rationale-v2"] = "kc-linked-name-refutation-wrong-rationale-v2"
    rule_version: Literal["kc_linked_name_refutation_wrong_rationale_v2"] = "kc_linked_name_refutation_wrong_rationale_v2"
    target: Literal["python-kc-binding-v1"] = "python-kc-binding-v1"
    slot: Literal["practice-1"] = "practice-1"
    seed: Literal[0] = 0
    wrong_explanation: Literal["对整数执行 saved = source 会建立两个名字的永久联动；source 从 4 重绑定到 9 后，saved 必须同步变为 9，程序实际输出 9 9。"] = CONTROLLED_V2_WRONG_EXPLANATION
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False

    @property
    def context_hash(self) -> str:
        return canonical_hash(checked_model(self,ControlledCounterexampleContextV2).model_dump(mode="json"))

    @property
    def rule_hash(self) -> str:
        return canonical_hash({"rule":self.rule_version,"field":"/private/content/answer_explanation_markdown",
            "program":CONTROLLED_V2_PROGRAM,"wrong_explanation":self.wrong_explanation})

    def check_request(self, request: GenerationRequestV2) -> None:
        from app.services.learning.item_supply.finite_candidate_factory import (
            FLEXIBLE_FACTORY_VERSION, allocation_from_blueprint, check_finite_public_request,
        )
        from app.services.learning.item_supply.shared_pipeline_contracts import native_request
        context = checked_model(self,ControlledCounterexampleContextV2)
        request,target = native_request(request)
        check_finite_public_request(request)
        allocation,seed = allocation_from_blueprint(request.blueprint,target.target_id)
        public = request.public_template
        if (target.target_id!=context.target or request.blueprint.version!=FLEXIBLE_FACTORY_VERSION
                or request.blueprint.blueprint_key!="finite.python-kc-binding-v1.practice-1.family-counterexample.s0"
                or allocation.variant_id!=context.target+":practice-1"
                or allocation.family_id!=context.target+":counterexample" or seed!=0
                or public is None or public.kind.value!="knowledge_check"
                or not isinstance(public.content,LearningItemKnowledgeCheckContentV1)
                or not any(CONTROLLED_V2_PROGRAM in option.label for option in public.content.options)
                or request.demand_binding is not None or request.profile.values.discussion_rounds<2
                or request.profile.values.revision_rounds<1 or request.profile.values.investigation_rounds<1
                or request.limits.max_output_tokens!=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS):
            raise ValueError("controlled exact registered counterexample practice1 seed0/program required")

    def check_source(self, source: LearningItemSourceV1) -> None:
        if getattr(source.private.content,"answer_explanation_markdown",None)!=self.wrong_explanation:
            raise ValueError("controlled original output constraint not preserved")

    @property
    def provider_payload(self) -> dict[str,object]:
        return {"context_version":self.schema_version,"experiment_key":self.experiment_key,
            "rule_version":self.rule_version,"rule_hash":self.rule_hash,"context_hash":self.context_hash,
            "fixed_field":"/private/content/answer_explanation_markdown","fixed_value":self.wrong_explanation,
            "purpose":"controlled_counterexample_not_production_acceptance","publication_enabled":False}


CONTROLLED_V3_EXPERIMENT_KEY = "kc-multiscenario-repair-constant-generalization-v3"
CONTROLLED_V3_WRONG_EXPLANATION: Final = "入口x=3和8时，先保存old，再把x增加2；此后new=10与new=x*2在两个场景都等价，固定10同时满足new为更新后x两倍的约束。"
CONTROLLED_V3_PROGRAM = "old = x\nx = x + 2\nnew = x * 2"


class ControlledCounterexampleContextV3(StorageContract):
    """Closed two-scenario repair; historical V1/V2 remain independent."""
    schema_version: Literal["controlled_kc_counterexample_context_v3"] = "controlled_kc_counterexample_context_v3"
    experiment_key: Literal["kc-multiscenario-repair-constant-generalization-v3"] = "kc-multiscenario-repair-constant-generalization-v3"
    rule_version: Literal["kc_multiscenario_repair_constant_generalization_v3"] = "kc_multiscenario_repair_constant_generalization_v3"
    target: Literal["python-kc-binding-v1"] = "python-kc-binding-v1"
    slot: Literal["assessment-1"] = "assessment-1"
    seed: Literal[0] = 0
    wrong_explanation: Literal["入口x=3和8时，先保存old，再把x增加2；此后new=10与new=x*2在两个场景都等价，固定10同时满足new为更新后x两倍的约束。"] = CONTROLLED_V3_WRONG_EXPLANATION
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False

    @property
    def context_hash(self) -> str:
        return canonical_hash(checked_model(self,ControlledCounterexampleContextV3).model_dump(mode="json"))

    @property
    def rule_hash(self) -> str:
        return canonical_hash({"rule":self.rule_version,"field":"/private/content/answer_explanation_markdown",
            "program":CONTROLLED_V3_PROGRAM,"wrong_explanation":self.wrong_explanation})

    def check_request(self, request: GenerationRequestV2) -> None:
        from app.services.learning.item_supply.finite_candidate_factory import (
            FLEXIBLE_FACTORY_VERSION, allocation_from_blueprint, check_finite_public_request,
        )
        from app.services.learning.item_supply.shared_pipeline_contracts import native_request
        context = checked_model(self,ControlledCounterexampleContextV3)
        request,target = native_request(request)
        check_finite_public_request(request)
        allocation,seed = allocation_from_blueprint(request.blueprint,target.target_id)
        public = request.public_template
        if (target.target_id!=context.target or request.blueprint.version!=FLEXIBLE_FACTORY_VERSION
                or request.blueprint.blueprint_key!="finite.python-kc-binding-v1.assessment-1.family-repair.s0"
                or allocation.variant_id!=context.target+":assessment-1" or allocation.slot!="assessment"
                or allocation.family_id!=context.target+":repair" or seed!=0
                or public is None or public.kind.value!="knowledge_check"
                or not isinstance(public.content,LearningItemKnowledgeCheckContentV1)
                or not any(CONTROLLED_V3_PROGRAM in option.label for option in public.content.options)
                or request.demand_binding is not None or request.profile.values.discussion_rounds<2
                or request.profile.values.revision_rounds<1 or request.profile.values.investigation_rounds<1
                or request.limits.max_output_tokens!=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS):
            raise ValueError("controlled exact registered repair assessment1 seed0/program required")

    def check_source(self, source: LearningItemSourceV1) -> None:
        if getattr(source.private.content,"answer_explanation_markdown",None)!=self.wrong_explanation:
            raise ValueError("controlled original output constraint not preserved")

    @property
    def provider_payload(self) -> dict[str,object]:
        return {"context_version":self.schema_version,"experiment_key":self.experiment_key,
            "rule_version":self.rule_version,"rule_hash":self.rule_hash,"context_hash":self.context_hash,
            "fixed_field":"/private/content/answer_explanation_markdown","fixed_value":self.wrong_explanation,
            "purpose":"controlled_counterexample_not_production_acceptance","publication_enabled":False}


ControlledCounterexampleContext = ControlledCounterexampleContextV1 | ControlledCounterexampleContextV2 | ControlledCounterexampleContextV3


def checked_controlled_context(value: object) -> ControlledCounterexampleContext:
    """Only exact server-owned V1/V2/V3 classes; dictionaries/subclasses are not dispatch inputs."""
    if type(value) is ControlledCounterexampleContextV1:
        return checked_model(value,ControlledCounterexampleContextV1)
    if type(value) is ControlledCounterexampleContextV2:
        return checked_model(value,ControlledCounterexampleContextV2)
    if type(value) is ControlledCounterexampleContextV3:
        return checked_model(value,ControlledCounterexampleContextV3)
    raise ValueError("explicit closed controlled context required")


class ControlledAuthorInputBindingV1(StorageContract):
    schema_version: Literal["controlled_author_input_binding_v1"] = "controlled_author_input_binding_v1"
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    messages_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_bytes: int = Field(ge=1,le=131072)


class ControlledAuthorTrace:
    """Only the original generator records this; JSON cannot restore an issuer."""
    def __init__(self, context: ControlledCounterexampleContext) -> None:
        checked_controlled_context(context)
        self.context = context
        self.binding: ControlledAuthorInputBindingV1 | None = None
        self.envelope: dict[str,object] | None = None

    def record(self, request: GenerationRequestV2, context: ControlledCounterexampleContext, *,
               messages: tuple[dict[str,str],...], output_schema: Mapping[str,object], input_bytes: int) -> None:
        context.check_request(request)
        if self.binding is not None or context is not self.context or input_bytes > request.limits.max_input_bytes:
            raise ValueError("original controlled envelope unavailable")
        self.envelope = {"messages":messages,"output_schema":output_schema}
        self.binding = ControlledAuthorInputBindingV1(request_hash=canonical_hash(request.model_dump(mode="json")),
            context_hash=context.context_hash,messages_hash=canonical_hash(messages),output_schema_hash=canonical_hash(output_schema),
            envelope_hash=canonical_hash(self.envelope),input_bytes=input_bytes)


@dataclass(frozen=True,repr=False)
class PreparedControlledCounterexample:
    preparation_id: UUID
    root_id: UUID
    lease: JobLeaseV1
    request: GenerationRequestV2
    context: ControlledCounterexampleContext
    sources: tuple[SourceReceiptV2,...]
    producer_binding: tuple[str,str]
    evidence_policy_hash: str
    deadline_at: datetime

    def payload(self) -> dict[str,object]:
        return {"schema_version":"controlled_counterexample_preparation_v1","preparation_id":str(self.preparation_id),
            "root_id":str(self.root_id),"lease":self.lease.model_dump(mode="json"),
            "request":self.request.model_dump(mode="json"),"request_hash":canonical_hash(self.request.model_dump(mode="json")),
            "context":self.context.model_dump(mode="json"),"context_hash":self.context.context_hash,"rule_hash":self.context.rule_hash,
            "sources":[s.model_dump(mode="json") for s in self.sources],"source_bindings_hash":canonical_hash([s.model_dump(mode="json") for s in self.sources]),
            "producer_binding":list(self.producer_binding),"evidence_policy_hash":self.evidence_policy_hash,
            "deadline_at":self.deadline_at.isoformat(),"publication_enabled":False,"admission_eligible":False}
