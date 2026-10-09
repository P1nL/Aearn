"""Four structural hypotheses per target, five allocation intents, six open pairs.

No answer catalog, runtime execution, course binding, source/proof or readiness.
"""
from itertools import combinations
from types import MappingProxyType

from .finite_course_targets import get_finite_course_target
from .finite_targets.contracts import (
    FiniteFamilyPairDeclarationV1,
    FiniteSlotAllocationV1,
    FiniteStructureV1,
    FiniteTaskFamilyV1,
    Slot,
    TargetId,
    TaskKind,
)


def _family(
    target_id: TargetId, task_kind: TaskKind, *, behavior: str, steps: tuple[str, ...],
    invariants: tuple[str, ...], failures: tuple[str, ...], task: str, fixtures: tuple[str, ...],
) -> FiniteTaskFamilyV1:
    target = get_finite_course_target(target_id)
    return FiniteTaskFamilyV1(
        target_id=target.target_id, family_id=f"{target_id}:{task_kind}", task_kind=task_kind,
        target_definition_hash=target.definition_hash,
        assessment_definition_hash=target.assessment.definition_hash, clause_refs=target.clause_refs,
        structure=FiniteStructureV1(
            behavior_id=behavior, steps=steps, invariants=invariants, semantic_failure_modes=failures,
        ), public_task=task, fixture_requirements=fixtures,
    )


_PYTHON = (
    _family(
        "python-state-update-v1", "accumulate", behavior="single-state-recurrence",
        steps=("Read the initialized accumulator.", "Apply each declared signed update in order.",
               "Observe the final accumulator."),
        invariants=("Every update depends on the preceding accumulator state.",
                    "Only the designated final variable is output."),
        failures=("Overwrite rather than accumulate.", "Restart each update from the initial value.",
                  "Print the correct literal without executing the required data dependency."),
        task="按题面给定的初值与两次有符号变动，依次更新同一累计变量并输出最终状态。",
        fixtures=("Positive and negative successive updates.", "A zero or cancelling update boundary.",
                  "Successful execution with correct stdout but missing state updates must fail semantics."),
    ),
    _family(
        "python-state-update-v1", "refresh", behavior="acyclic-dependency-refresh",
        steps=("Evaluate a derived value from two current inputs.", "Rebind one input.",
               "Refresh the dependent value before observing it."),
        invariants=("The final derived state reflects the rebound input, not the earlier evaluation.",
                    "Input rebinding does not automatically change a saved derived value."),
        failures=("Output the stale derived state.", "Copy the saved result instead of reevaluating.",
                  "Hardcode a coincidentally correct output."),
        task="先按单价与数量求小计；数量按题面变更后，更新小计并仅输出最终小计。",
        fixtures=("Changed input produces a different derived value.", "Zero input boundary.",
                  "A stale result must be distinguished even though the program runs successfully."),
    ),
    _family(
        "python-state-update-v1", "swap", behavior="two-state-permutation-with-preservation",
        steps=("Retain access to both original values.", "Exchange the two variable bindings.",
               "Observe both final states in the requested order."),
        invariants=("Each final variable contains the other original value.",
                    "Neither original value is lost before its required use."),
        failures=("Overwrite one original value and duplicate the other.", "Update only one side.",
                  "Output the expected literals without preserving and exchanging state."),
        task="交换题面指定的两个变量所保存的值，保留两份原值信息，按指定顺序输出交换后的值。",
        fixtures=("Distinct original values.", "Equal and zero-valued boundaries.",
                  "Equivalent preservation mechanisms require the same state/output checks."),
    ),
    _family(
        "python-state-update-v1", "transfer", behavior="two-state-conserved-transfer",
        steps=("Read both initial balances and the fixed transfer amount.",
               "Apply opposite changes to the designated balances using the same amount.",
               "Observe both final balances and their total."),
        invariants=("Combined balance is conserved.", "Both balances reflect the identical transfer amount."),
        failures=("Debit without credit.", "Credit the wrong variable.",
                  "Derive the transfer amount from an already updated balance.",
                  "Print a conserved total while actual state violates conservation."),
        task="将题面指定数量从源余额转入目标余额，输出两侧最终余额及总量，保持总量守恒。",
        fixtures=("Nonzero transfer between distinct balances.", "Zero and full-source transfer boundaries.",
                  "Correct-looking output with invalid balance state is a semantic negative."),
    ),
)

_SQL = (
    _family(
        "sqlite-predicate-order-v1", "conjunction", behavior="conjunctive-row-qualification",
        steps=("Require both the active flag and the inclusive score threshold.",
               "Keep every qualifying row and project its name.", "Order by the unique ascending id."),
        invariants=("Both conditions are necessary.", "Matching duplicate names retain multiplicity.",
                    "The id determines the complete output order."),
        failures=("Use disjunction instead of conjunction.", "Exclude the inclusive threshold boundary.",
                  "Deduplicate projected names.", "Reverse the requested order."),
        task="从单表选择active为1且score不低于60的name，按id升序，保留同名的不同匹配行。",
        fixtures=("Independent truth combinations for both conditions and score exactly 60.",
                  "Duplicate projected names and unsorted physical rows.", "Empty result."),
    ),
    _family(
        "sqlite-predicate-order-v1", "override_fallback", behavior="nullable-priority-fallback",
        steps=("Select the override when present, otherwise the default.",
               "Qualify only an effective value of one and retain each matching name.",
               "Order by descending priority and ascending unique id."),
        invariants=("An explicit zero override wins over a true default.",
                    "Two missing values do not qualify.", "Projection preserves multiplicity and total order."),
        failures=("Ignore the override.", "Treat missing as a truthy value.",
                  "Use equality to NULL rather than missing-value semantics.", "Omit the tie-break key."),
        task=("有override时以其为准，否则使用default；仅有效值为1的行入选，双NULL不入选。"
              "输出name，按priority降序、id升序，保留重复name。"),
        fixtures=("Zero override with a true default.", "Missing override and both values missing.",
                  "Equal priorities, duplicate names, shuffled rows and empty result."),
    ),
    _family(
        "sqlite-predicate-order-v1", "exclusive", behavior="exclusive-boolean-qualification",
        steps=("Interpret missing qualification flags as zero.", "Require exactly one of the two flags.",
               "Project every matching name in descending score and ascending id order."),
        invariants=("The two-true and two-false combinations do not qualify.",
                    "The explicit NULL-as-zero policy applies independently to each flag.",
                    "Duplicate names and tied scores retain row multiplicity and complete order."),
        failures=("Inclusive OR admits two-true rows.", "AND admits only two-true rows.",
                  "Omit the declared NULL policy.", "Discard duplicates or score ties."),
        task=("两个0/1资格标志恰好一个为1时入选，NULL按0处理；输出name，"
              "按score降序、id升序，保留同名匹配行。"),
        fixtures=("All four Boolean combinations.", "NULL on either or both flags.",
                  "Tied scores, repeated names, shuffled input and empty result."),
    ),
    _family(
        "sqlite-predicate-order-v1", "keyset_after", behavior="lexicographic-keyset-boundary",
        steps=("Interpret the cursor in descending score and ascending id order.",
               "Select all rows strictly after that boundary, not a physical offset.",
               "Project matching names in that same complete order."),
        invariants=("The cursor is excluded and later equal-score ids remain eligible.",
                    "Cursor coordinates need not identify a row in the dataset.",
                    "Multiplicity and full ordering are preserved."),
        failures=("Compare only scores and drop eligible ties.", "Reinclude the cursor.",
                  "Reverse the id tie direction.", "Conjoin incompatible boundary branches."),
        task=("按score降序、id升序定义顺序，选择严格位于给定游标之后的所有name，"
              "保留重复投影并按相同全序输出；不使用物理行偏移。"),
        fixtures=("Equal-score rows on both sides of the cursor.", "No physical cursor row.",
                  "Duplicate names, shuffled input and empty result."),
    ),
)

_KC = (
    _family(
        "python-kc-binding-v1", "trace", behavior="forward-binding-state-trace",
        steps=("Trace a three-name chain at each assignment time.", "Distinguish saved values from rebinding.",
               "Choose the unique final-state combination with its correct reason."),
        invariants=("Saved values do not follow later rebinding of their source name.",
                    "The selected response must explain the complete final state, not one lucky number."),
        failures=("Treat assignment as a permanent equality.", "Update all previously assigned names.",
                  "Select a correct number with a false causal explanation."),
        task="阅读三个名字先保存再重绑定的顺序程序，选择最终值组合与原因均正确的唯一选项。",
        fixtures=("Every option distinguishes RHS-time, saved value and observable outcome.",
                  "Exactly one correct combination and reason; distractors encode distinct misconceptions."),
    ),
    _family(
        "python-kc-binding-v1", "diagnose", behavior="first-causal-divergence-diagnosis",
        steps=("Evaluate a derived value before an input rebind.",
               "Locate the first incorrect causal step among candidate explanations.",
               "Choose the response with both correct diagnosis and final outcome."),
        invariants=("A previously evaluated expression is not a live formula.",
                    "The earliest divergence and the reported outcome must both be correct."),
        failures=("Link a saved expression permanently to its source.", "Identify a later symptom as first cause.",
                  "Pair the correct diagnosis with an incorrect final value."),
        task=("阅读派生值计算后源变量变化的程序及四份步骤解释，选择首个偏差定位和最终结果均正确的一项。"),
        fixtures=("The dependency graph differs from the simple saved-name tracing chain.",
                  "All four explanations require checking timing, saved derived value and final outcome."),
    ),
    _family(
        "python-kc-binding-v1", "repair", behavior="constrained-multiscenario-state-repair",
        steps=("Read the old/new output constraints for two explicit input scenarios.",
               "Check each minimal patch against preservation and refreshed-value requirements.",
               "Select the unique patch satisfying both scenarios and constraints."),
        invariants=("The old value remains available while the new value is computed.",
                    "One response satisfies both scenarios without hardcoded outcomes."),
        failures=("Overwrite before saving.", "Repair only one input scenario.",
                  "Hardcode the example outcome instead of satisfying the dependency constraints."),
        task=("根据old/new两项输出约束，在四个最小补丁中选择对两个给定输入场景都保存旧值且正确计算新值的一项。"),
        fixtures=("Two distinct scenarios rule out a one-value or one-scenario shortcut.",
                  "Every rejected patch has a concrete constraint violation; exactly one patch satisfies both."),
    ),
    _family(
        "python-kc-binding-v1", "counterexample", behavior="linked-name-misconception-refutation",
        steps=("Identify the universal linked-name claim.", "Inspect candidate programs and explanations.",
               "Select the unique actual rebinding counterexample with matching output and causal account."),
        invariants=("A valid refutation includes the claimed trigger but contradicts its predicted consequence.",
                    "The program, stated output and explanation agree."),
        failures=("Offer a program without rebinding.", "Rebind a different name than the claim requires.",
                  "Give an alleged counterexample whose output contradicts its explanation."),
        task=("从四段小程序与解释中，选择唯一能反驳源名字重绑定会改变所有先前赋出名字的有效反例，"
              "同时检查对应输出。"),
        fixtures=("One genuine counterexample and three semantically distinct invalid refutations.",
                  "Each option binds RHS timing, preserved values, output and claimed conclusion."),
    ),
)
_FAMILIES = MappingProxyType({
    "python-state-update-v1": _PYTHON, "sqlite-predicate-order-v1": _SQL,
    "python-kc-binding-v1": _KC,
})


def families_for_course(target_id: str) -> tuple[FiniteTaskFamilyV1, ...]:
    target = get_finite_course_target(target_id)
    return _FAMILIES[target.target_id]


def initial_slot_allocations(target_id: str) -> tuple[FiniteSlotAllocationV1, ...]:
    """Allocation intentions only: no candidate exists merely because of a variant ID."""
    target = get_finite_course_target(target_id)
    families = families_for_course(target_id)
    rows: tuple[tuple[int, str, Slot], ...] = (
        (0, "practice-1", "practice"), (1, "practice-2", "practice"),
        (2, "assessment-1", "assessment"), (3, "assessment-2", "assessment"),
        (1, "guided-remediation", "remediation"),
    )
    return tuple(FiniteSlotAllocationV1(
        target_id=target.target_id, family_id=families[index].family_id,
        family_definition_hash=families[index].definition_hash,
        variant_id=f"{target_id}:{role}", slot=slot,
        purpose="remediation" if slot == "remediation" else target.assessment.purpose,
        clause_refs=target.clause_refs,
        guidance="state_table_and_localization_hints" if slot == "remediation" else "unguided",
        binding_requirement="purpose_child_scope" if slot == "remediation" else "native_scope",
    ) for index, role, slot in rows)


def declared_family_pair_matrix(target_id: str) -> tuple[FiniteFamilyPairDeclarationV1, ...]:
    """Six pending comparisons, including practice/assessment and assessment/assessment.

    Legal symbol/constant alignment and successful-execution semantic counterexamples
    belong to the later evidence owner. Hash inequality proves none of that.
    """
    target = get_finite_course_target(target_id)
    return tuple(FiniteFamilyPairDeclarationV1(
        target_id=target.target_id, left_family_id=left.family_id, right_family_id=right.family_id,
        left_structure_signature=left.structure_signature, right_structure_signature=right.structure_signature,
    ) for left, right in combinations(families_for_course(target_id), 2))
