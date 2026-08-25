from __future__ import annotations

from app.services.learning.contracts import LearningPlan, LearningPlanModule, LearningPlanNode


def sample_plan(
    *,
    title: str = "Python Foundations",
    target_level: str = "beginner",
    generator_version: str = "learning-plan-test-v1",
    change_reason: str = "Create the initial confirmed learning route.",
    include_loops: bool = False,
    loops_prerequisites: tuple[str, ...] = ("python.variables",),
) -> LearningPlan:
    nodes = [
        LearningPlanNode(
            knowledge_key="python.variables",
            title="Variables",
            description="Bind and inspect values.",
            order_index=0,
            is_core=True,
            prerequisite_keys=(),
            required_capabilities=("python",),
        ),
        LearningPlanNode(
            knowledge_key="python.functions",
            title="Functions",
            description="Define and call functions.",
            order_index=1,
            is_core=True,
            prerequisite_keys=("python.variables",),
            required_capabilities=("python",),
        ),
    ]
    if include_loops:
        nodes.append(
            LearningPlanNode(
                knowledge_key="python.loops",
                title="Loops",
                description="Repeat bounded work.",
                order_index=2,
                is_core=True,
                prerequisite_keys=loops_prerequisites,
                required_capabilities=("python",),
            )
        )
    return LearningPlan(
        title=title,
        target_level=target_level,
        generator_version=generator_version,
        policy_version="learning-plan-policy-test-v1",
        change_reason=change_reason,
        modules=(
            LearningPlanModule(
                module_key="foundations",
                title="Foundations",
                description="Core language foundations.",
                order_index=0,
                is_core=True,
                is_skippable=False,
                nodes=tuple(nodes),
            ),
        ),
    )


def sample_plan_payload(**overrides: object) -> dict[str, object]:
    plan = sample_plan(
        title=str(overrides.pop("title", "Python Foundations")),
        target_level=str(overrides.pop("target_level", "beginner")),
        generator_version=str(overrides.pop("generator_version", "learning-plan-test-v1")),
        change_reason=str(overrides.pop("change_reason", "Create the initial confirmed learning route.")),
        include_loops=bool(overrides.pop("include_loops", False)),
    )
    payload = {
        "title": plan.title,
        "target_level": plan.target_level,
        "generator_version": plan.generator_version,
        "policy_version": plan.policy_version,
        "change_reason": plan.change_reason,
        "modules": [
            {
                "module_key": module.module_key,
                "title": module.title,
                "description": module.description,
                "order_index": module.order_index,
                "is_core": module.is_core,
                "is_skippable": module.is_skippable,
                "nodes": [
                    {
                        "knowledge_key": node.knowledge_key,
                        "title": node.title,
                        "description": node.description,
                        "order_index": node.order_index,
                        "is_core": node.is_core,
                        "prerequisite_keys": list(node.prerequisite_keys),
                        "required_capabilities": list(node.required_capabilities),
                    }
                    for node in module.nodes
                ],
            }
            for module in plan.modules
        ],
    }
    payload.update(overrides)
    return payload
