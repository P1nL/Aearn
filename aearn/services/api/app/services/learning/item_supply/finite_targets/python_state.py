"""Four immutable-version Python state declarations and API-private probes.

Pure definitions only: not course authority, published inventory, family evidence,
execution receipts, or a replacement for the original assignment/sum/print goal.
Never copy this module into an executor image: its programs are private probes.
"""
from __future__ import annotations

import keyword
import re
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.services.learning.item_bank.contracts import canonical_hash

PYTHON_STATE_GOAL_ID: Literal["python-state-update-v1"] = "python-state-update-v1"
PYTHON_STATE_CLAUSE_IDS = ("PY-C1", "PY-C2", "PY-C3")
PYTHON_STATE_CAPABILITIES = ("python.assignment",)
# Pin the exact public-rule module, not only a hand-maintained grammar label.
PYTHON_STATE_GRAMMAR_SHA256 = "7de81607860afe0944d10df96e32537a6b6faf4cd6ba0937b7bcb3656edf808a"
BoundedInt = Annotated[int, Field(strict=True, ge=-1000, le=1000)]
TaskKind = Literal["accumulate", "refresh", "swap", "transfer"]
_ROLES = {
    "accumulate": ({"total", "increase", "decrease"}, {"initial", "increase", "decrease"}),
    "refresh": ({"price", "qty", "subtotal", "saved"}, {"price", "initial_qty", "updated_qty"}),
    "swap": ({"left", "right", "saved"}, {"left", "right"}),
    "transfer": ({"source", "target", "amount", "total"}, {"source", "target", "amount"}),
}


class _StateTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")
    goal_contract_id: Literal["python-state-update-v1"] = PYTHON_STATE_GOAL_ID
    task_kind: TaskKind
    variables: dict[str, str]
    values: dict[str, BoundedInt]

    @model_validator(mode="after")
    def public_roles_only(self) -> Self:
        roles, values = _ROLES[self.task_kind]
        if set(self.variables) != roles or set(self.values) != values:
            raise ValueError("python_state_public_parameters_invalid")
        names = tuple(self.variables.values())
        if len(set(names)) != len(names) or any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name)
            or keyword.iskeyword(name) or name == "print" for name in names
        ):
            raise ValueError("python_state_variable_invalid")
        if self.task_kind == "transfer" and not (
            0 <= self.values["amount"] <= self.values["source"] and self.values["target"] >= 0
        ):
            raise ValueError("python_state_transfer_invalid")
        return self

    @property
    def target_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class AccumulateTarget(_StateTarget):
    task_kind: Literal["accumulate"] = "accumulate"


class RefreshTarget(_StateTarget):
    task_kind: Literal["refresh"] = "refresh"


class SwapTarget(_StateTarget):
    task_kind: Literal["swap"] = "swap"


class TransferTarget(_StateTarget):
    task_kind: Literal["transfer"] = "transfer"


PythonStateTarget = Annotated[
    AccumulateTarget | RefreshTarget | SwapTarget | TransferTarget,
    Field(discriminator="task_kind"),
]
_TARGET: TypeAdapter[PythonStateTarget] = TypeAdapter(PythonStateTarget)


def parse_python_state_target(value: object) -> PythonStateTarget:
    # Revalidate even model_copy/model_construct or a mutated nested dictionary.
    raw = value.model_dump(mode="python") if isinstance(value, _StateTarget) else value
    if not isinstance(raw, dict) or set(raw) != {"goal_contract_id", "task_kind", "variables", "values"}:
        raise ValueError("python_state_contract_invalid")
    return _TARGET.validate_python(raw, strict=True)


def python_state_expected_stdout(target: PythonStateTarget) -> str:
    """Arithmetic on trusted public parameters, never on candidate source."""
    target = parse_python_state_target(target)
    v = target.values
    if target.task_kind == "accumulate":
        return f"{v['initial'] + v['increase'] - v['decrease']}\n"
    if target.task_kind == "refresh":
        return f"{v['price'] * v['updated_qty']}\n"
    if target.task_kind == "swap":
        return f"{v['right']} {v['left']}\n"
    return f"{v['source'] - v['amount']} {v['target'] + v['amount']} {v['source'] + v['target']}\n"


def compile_python_state_tests(target: PythonStateTarget) -> tuple[dict[str, Any], ...]:
    """One exact public task, not secretly changed parameters in hidden cases."""
    target = parse_python_state_target(target)
    return ({"id": "python-state-final", "case_type": "visible",
             "input_json": {"goal_contract": target.model_dump(mode="json")},
             "expected_output_json": {"stdout": python_state_expected_stdout(target)}},)


@dataclass(frozen=True)
class PythonStateCounterexample:
    name: str
    submission: str
    expected_stdout: str
    reason: str


@dataclass(frozen=True)
class PythonStateFixture:
    target: PythonStateTarget
    family_id: str
    public_instruction: str
    starter_code: str
    reference: str
    equivalent: str
    wrong: tuple[PythonStateCounterexample, ...]
    boundary_target: PythonStateTarget
    boundary_reference: str
    boundary_equivalent: str
    boundary_expected_stdout: str

    @property
    def public_task_hash(self) -> str:
        return canonical_hash({"target": self.target.model_dump(mode="json"),
                               "instruction": self.public_instruction, "starter": self.starter_code})


_GRAMMAR_INSTRUCTION = (
    "仅使用题面命名变量、整数、顶层简单赋值、两项同时赋值或 +=/-=；"
    "表达式限单层加减乘，不使用分支、循环、函数、导入或其他调用。"
    "最后仅调用一次 print（不指定 keyword），按要求以空格分隔输出，不写死最终值。"
    "允许空白、注释、括号及加法/乘法交换律。"
)


def _programs(target: PythonStateTarget) -> tuple[str, str, str, str, tuple[PythonStateCounterexample, ...]]:
    """Render API-private finite probes; never executed by this compiler."""
    n, v = target.variables, target.values
    wrong: list[PythonStateCounterexample] = []
    expected = python_state_expected_stdout(target)
    if target.task_kind == "accumulate":
        t, add, sub = n["total"], n["increase"], n["decrease"]
        prefix = f"{t} = {v['initial']}\n{add} = {v['increase']}\n{sub} = {v['decrease']}\n"
        out = f"print({t})"
        reference = prefix + f"{t} = {t} + {add}\n{t} = {t} - {sub}\n" + out
        equivalent = prefix + f"{t} += {add}\n{t} -= {sub}\n" + out
        wrong.extend((
            PythonStateCounterexample("last_delta_only", prefix + f"{t} = {sub}\n" + out,
                                      f"{v['decrease']}\n", "覆盖累计值而非递推"),
            PythonStateCounterexample("restart_initial", prefix + f"{t} = {t} + {add}\n{t} = {v['initial']} - {sub}\n" + out,
                                      f"{v['initial'] - v['decrease']}\n", "第二步错误重用初值"),
        ))
        instruction = (f"初始化 {t}={v['initial']}、{add}={v['increase']}、{sub}={v['decrease']}。"
                       f"先将 {add} 纳入 {t}，再从更新后的 {t} 扣除 {sub}，每步都更新同一个累计变量。"
                       f"最后只输出 {t}。")
        starter = prefix + out
    elif target.task_kind == "refresh":
        p, q, total, saved = n["price"], n["qty"], n["subtotal"], n["saved"]
        prefix = f"{p} = {v['price']}\n{q} = {v['initial_qty']}\n"
        before = prefix + f"{total} = {p} * {q}\n{q} = {v['updated_qty']}\n"
        out = f"print({total})"
        reference = before + f"{total} = {p} * {q}\n" + out
        equivalent = before + f"{saved} = {q} * {p}\n{total} = {saved}\n" + out
        old = f"{v['price'] * v['initial_qty']}\n"
        wrong.extend((
            PythonStateCounterexample("stale_derived_value", before + out, old, "重绑定源变量不会刷新派生值"),
            PythonStateCounterexample("copy_stale_value", before + f"{saved} = {total}\n{total} = {saved}\n" + out,
                                      old, "复制旧值不等于重新求值"),
        ))
        instruction = (f"初始化 {p}={v['price']}、{q}={v['initial_qty']}，先以二者的乘积计算 {total}。"
                       f"然后把 {q} 改为 {v['updated_qty']}，用当前 {p} 和 {q} 重新计算 {total}，最后仅输出 {total}。"
                       f"可直接刷新，或先把新乘积存入 {saved} 再赋给 {total}，不得复制旧的 {total}。")
        starter = prefix + f"{total} = {p} * {q}\n" + out
    elif target.task_kind == "swap":
        left, right, saved = n["left"], n["right"], n["saved"]
        prefix = f"{left} = {v['left']}\n{right} = {v['right']}\n"
        out = f"print({left}, {right})"
        reference = prefix + f"{saved} = {left}\n{left} = {right}\n{right} = {saved}\n" + out
        equivalent = prefix + f"{left}, {right} = {right}, {left}\n" + out
        wrong.extend((
            PythonStateCounterexample("overwrite_before_save", prefix + f"{left} = {right}\n{right} = {left}\n" + out,
                                      f"{v['right']} {v['right']}\n", "覆盖后丢失原值"),
            PythonStateCounterexample("update_one_side", prefix + f"{left} = {right}\n" + out,
                                      f"{v['right']} {v['right']}\n", "只修改一侧不是交换"),
        ))
        instruction = (f"初始化 {left}={v['left']}、{right}={v['right']}，交换这两个变量中的原值。"
                       f"可用临时变量 {saved} 保存任一原值后顺序赋值，或用两项同时赋值。"
                       f"最后依次输出 {left}、{right}，必须保留两个原始值，不能直接打印常量。")
        starter = prefix + out
    else:
        source, dest, amount, total = n["source"], n["target"], n["amount"], n["total"]
        prefix = f"{source} = {v['source']}\n{dest} = {v['target']}\n{amount} = {v['amount']}\n"
        out = f"print({source}, {dest}, {source} + {dest})"
        reference = prefix + f"{source} = {source} - {amount}\n{dest} = {dest} + {amount}\n" + out
        equivalent = prefix + f"{source}, {dest} = {source} - {amount}, {dest} + {amount}\n{total} = {source} + {dest}\nprint({source}, {dest}, {total})"
        remaining = v["source"] - v["amount"]
        wrong.extend((
            PythonStateCounterexample("debit_only", prefix + f"{source} -= {amount}\n" + out,
                                      f"{remaining} {v['target']} {remaining + v['target']}\n", "只减不加违反守恒"),
            PythonStateCounterexample("credit_updated_source", prefix + f"{source} -= {amount}\n{dest} += {source}\n" + out,
                                      f"{remaining} {v['target'] + remaining} {2 * remaining + v['target']}\n", "两侧没有使用相同转移量"),
        ))
        instruction = (f"初始化 {source}={v['source']}、{dest}={v['target']}、{amount}={v['amount']}。"
                       f"从 {source} 向 {dest} 转移 {amount}，两侧都必须使用同一未改变的转移量，一减一加。"
                       "可依次更新（两侧次序不限），或两项同时赋值。"
                       f"最后依次输出 {source}、{dest} 及它们的最终总量，总量可直接求和或存入 {total} 后输出。")
        starter = prefix + out
    # Successful-runtime hardcoded stdout control: intentionally no goal process.
    literal_args = ", ".join(expected.strip().split())
    wrong.append(PythonStateCounterexample("hardcoded_stdout", f"print({literal_args})", expected,
                                          "stdout 相同但没有合法状态更新"))
    return instruction + _GRAMMAR_INSTRUCTION, starter, reference, equivalent, tuple(wrong)


def python_state_fixtures() -> tuple[PythonStateFixture, ...]:
    """Finite API-side declaration set, NOT a family-independence certificate."""
    declarations = (
        (AccumulateTarget(variables={"total": "total", "increase": "increase", "decrease": "decrease"},
                          values={"initial": 10, "increase": 4, "decrease": 3}),
         {"initial": -2, "increase": 0, "decrease": -2}),
        (RefreshTarget(variables={"price": "price", "qty": "qty", "subtotal": "subtotal", "saved": "refreshed"},
                       values={"price": 2, "initial_qty": 3, "updated_qty": 5}),
         {"price": 2, "initial_qty": 3, "updated_qty": 0}),
        (SwapTarget(variables={"left": "left", "right": "right", "saved": "saved"}, values={"left": 2, "right": 7}),
         {"left": 0, "right": -7}),
        (TransferTarget(variables={"source": "source", "target": "target", "amount": "amount", "total": "total"},
                        values={"source": 9, "target": 1, "amount": 3}),
         {"source": 3, "target": 0, "amount": 3}),
    )
    result = []
    for target, boundary_values in declarations:
        boundary = parse_python_state_target({**target.model_dump(mode="json"), "values": boundary_values})
        instruction, starter, reference, equivalent, wrong = _programs(target)
        _, _, boundary_reference, boundary_equivalent, _ = _programs(boundary)
        result.append(PythonStateFixture(
            target=target, family_id=f"{PYTHON_STATE_GOAL_ID}:{target.task_kind}", public_instruction=instruction,
            starter_code=starter, reference=reference, equivalent=equivalent, wrong=wrong,
            boundary_target=boundary, boundary_reference=boundary_reference,
            boundary_equivalent=boundary_equivalent, boundary_expected_stdout=python_state_expected_stdout(boundary),
        ))
    return tuple(result)


PYTHON_STATE_FIXTURE_HASH = canonical_hash([
    {"target": f.target.model_dump(mode="json"), "public_task_hash": f.public_task_hash,
     "family_id": f.family_id, "clauses": PYTHON_STATE_CLAUSE_IDS,
     "reference": f.reference, "equivalent": f.equivalent,
     "wrong": [asdict(case) for case in f.wrong],
     "boundary_target": f.boundary_target.model_dump(mode="json"),
     "boundary_reference": f.boundary_reference, "boundary_equivalent": f.boundary_equivalent,
     "boundary_stdout": f.boundary_expected_stdout}
    for f in python_state_fixtures()
])
