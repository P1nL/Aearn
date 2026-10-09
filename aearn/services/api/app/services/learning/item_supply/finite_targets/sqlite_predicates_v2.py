"""Unregistered common-schema SQL V2 declarations; no IO or admission authority.

Expected tables come only from validated row traversal, never submitted/reference
SQL. Private fixtures are plans, not sealed execution or family-review evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import Field, model_validator

from aearn_shared.execution import SafeTableResultPresentationV1
from app.services.learning.item_bank.contracts import (
    LearningItemSqlColumnV2,
    LearningItemSqlContentV2,
    LearningItemSqlDatasetTableV2,
    LearningItemSqlDatasetV2,
    LearningItemSqlTableV2,
    LearningItemSqlTestCaseV2,
    _validate_sql_dataset,
    canonical_hash,
)
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

SQLITE_PROGRAM_TARGET_ID_V2 = "sqlite-predicate-order-v2"
SQLITE_PUBLIC_SPEC_VERSION_V2 = "finite-sql-common-spec-v1"
SQLITE_RUNTIME_PROFILE_V2 = "sqlite-query-v1"
SqliteTaskKindV2 = Literal["conjunction", "override_fallback", "exclusive", "keyset_after"]
SQLITE_TASK_KINDS_V2: tuple[SqliteTaskKindV2, ...] = (
    "conjunction", "override_fallback", "exclusive", "keyset_after",
)
SqliteFamilyIdV2 = Literal[
    "sqlite-predicate-order-v2:conjunction", "sqlite-predicate-order-v2:override_fallback",
    "sqlite-predicate-order-v2:exclusive", "sqlite-predicate-order-v2:keyset_after",
]
SqliteFaultV2 = Literal[
    "or_instead_of_and", "strict_cutoff", "ignores_override", "missing_fallback",
    "inclusive_or", "null_propagation", "score_only", "includes_cursor",
    "distinct", "reverse_order", "reverse_tie", "primary_ascending",
]
_Cell = int | str | None
_Row = tuple[_Cell, ...]


class SqlitePredicateTargetV2(StorageContract):
    """New target, not an alias/subclass of the V1 Literal contract."""

    schema_version: Literal["sqlite_predicate_target_v2"] = "sqlite_predicate_target_v2"
    program_target_id: Literal["sqlite-predicate-order-v2"] = "sqlite-predicate-order-v2"
    task_kind: SqliteTaskKindV2
    seed: int = Field(default=0, ge=0, le=255)
    table_name: Literal["entries"] = "entries"
    projection: tuple[Literal["name"]] = ("name",)
    null_order: Literal["last"] = "last"
    # ALL three parameters are public for ALL four tasks, even when unused.
    min_score: int = Field(default=60, ge=60, le=315)
    cut_score: int = Field(default=70, ge=70, le=325)
    cut_id: int = Field(default=4, ge=4, le=259)

    @model_validator(mode="after")
    def shared_parameter_roles(self) -> SqlitePredicateTargetV2:
        if (self.min_score, self.cut_score, self.cut_id) != (60 + self.seed, 70 + self.seed, 4 + self.seed):
            raise ValueError("sqlite_v2_parameters_must_match_seed")
        return self


class SqlitePublicTaskV2(StorageContract):
    """Only public schema/data/parameters; no answers or oracle tables."""

    schema_version: Literal["sqlite_public_task_v2"] = "sqlite_public_task_v2"
    blueprint_version: Literal["finite-sql-common-spec-v1"] = "finite-sql-common-spec-v1"
    target: SqlitePredicateTargetV2
    purpose: Literal["exercise", "remediation"] = "exercise"
    guided: bool = False
    instruction: str = Field(min_length=1, max_length=4000)
    content: LearningItemSqlContentV2

    @model_validator(mode="after")
    def assistance_scope(self) -> SqlitePublicTaskV2:
        if self.guided != (self.purpose == "remediation"):
            raise ValueError("sqlite_v2_guidance_purpose_mismatch")
        return self


class SqliteCounterexampleV2(StorageContract):
    fault: SqliteFaultV2
    query: str = Field(min_length=1, max_length=2000, repr=False)
    failing_case_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    construction: Literal["planned"] = "planned"
    execution_status: Literal["pending"] = "pending"


class SqlitePrivateFixtureV2(StorageContract):
    """PRIVATE reference/equivalent/wrong-semantic tasks, disabled by default."""

    schema_version: Literal["sqlite_private_fixture_v2"] = "sqlite_private_fixture_v2"
    target: SqlitePredicateTargetV2
    family_id: SqliteFamilyIdV2
    public_task: SqlitePublicTaskV2
    equivalent_queries: tuple[str, str] = Field(repr=False)
    private_cases: tuple[LearningItemSqlTestCaseV2, ...] = Field(min_length=4, max_length=4, repr=False)
    counterexamples: tuple[SqliteCounterexampleV2, ...] = Field(min_length=4, max_length=5, repr=False)
    execution_status: Literal["pending"] = "pending"
    family_independence_status: Literal["pending"] = "pending"
    authority: Literal["not_execution_or_family_evidence"] = "not_execution_or_family_evidence"
    publication_enabled: Literal[False] = False


def parse_sqlite_target_v2(value: object) -> SqlitePredicateTargetV2:
    if type(value) is SqlitePredicateTargetV2:
        return checked_model(cast(SqlitePredicateTargetV2, value), SqlitePredicateTargetV2)
    if not isinstance(value, dict):
        raise ValueError("unsupported finite SQLite V2 target")
    return SqlitePredicateTargetV2.model_validate(value, strict=True)


def sqlite_target_v2(task_kind: SqliteTaskKindV2, *, seed: int = 0) -> SqlitePredicateTargetV2:
    if type(seed) is not int or not 0 <= seed <= 255:
        raise ValueError("sqlite_v2_seed_domain")
    return SqlitePredicateTargetV2(task_kind=task_kind, seed=seed,
        min_score=60 + seed, cut_score=70 + seed, cut_id=4 + seed)


def sqlite_target_hash_v2(target: SqlitePredicateTargetV2) -> str:
    return canonical_hash(parse_sqlite_target_v2(target).model_dump(mode="json"))


def sqlite_tables_v2() -> tuple[LearningItemSqlTableV2, ...]:
    return (LearningItemSqlTableV2(name="entries", columns=(
        LearningItemSqlColumnV2(name="id", data_type="INTEGER", nullable=False, primary_key=True),
        LearningItemSqlColumnV2(name="name", data_type="TEXT", nullable=False),
        LearningItemSqlColumnV2(name="flag_a", data_type="INTEGER"),
        LearningItemSqlColumnV2(name="flag_b", data_type="INTEGER"),
        LearningItemSqlColumnV2(name="score", data_type="INTEGER"),
    )),)


@dataclass(frozen=True)
class _Record:
    identity: int
    name: str
    a: int | None
    b: int | None
    score: int | None


def _records(dataset: LearningItemSqlDatasetV2) -> tuple[_Record, ...]:
    dataset = checked_model(dataset, LearningItemSqlDatasetV2)
    # Reuse Item Bank's established schema/PK/nullability/payload validation seam.
    _validate_sql_dataset(sqlite_tables_v2(), dataset, maximum_rows=200)
    records = []
    for identity, name, a, b, score in dataset.tables[0].rows:
        for cell in (identity, a, b, score):
            if cell is not None and (type(cell) is not int or not -1_000_000 <= cell <= 1_000_000):
                raise ValueError("sqlite_v2_integer_domain")
        if a not in (None, 0, 1) or b not in (None, 0, 1):
            raise ValueError("sqlite_v2_flag_domain")
        records.append(_Record(cast(int, identity), cast(str, name), cast(int | None, a),
                               cast(int | None, b), cast(int | None, score)))
    return tuple(records)


def _selected(target: SqlitePredicateTargetV2, row: _Record) -> bool:
    if target.task_kind == "conjunction":
        return row.a == 1 and row.score is not None and row.score >= target.min_score
    if target.task_kind == "override_fallback":
        return (row.a if row.a is not None else row.b) == 1
    if target.task_kind == "exclusive":
        return (0 if row.a is None else row.a, 0 if row.b is None else row.b) in ((1, 0), (0, 1))
    return row.score is not None and (row.score < target.cut_score
        or (row.score == target.cut_score and row.identity > target.cut_id))


def _order_key(target: SqlitePredicateTargetV2, row: _Record) -> tuple[int, int, int]:
    if target.task_kind == "conjunction":
        return (0, 0, row.identity)
    return (int(row.score is None), -row.score if row.score is not None else 0, row.identity)


def _project(rows: list[_Record]) -> SafeTableResultPresentationV1:
    return SafeTableResultPresentationV1(columns=("name",), rows=tuple((row.name,) for row in rows))


def sqlite_oracle_v2(target: SqlitePredicateTargetV2, dataset: LearningItemSqlDatasetV2) -> SafeTableResultPresentationV1:
    """Independent relational truth: no SQL parsing, evaluation or execution."""
    target = parse_sqlite_target_v2(target)
    return _project(sorted((row for row in _records(dataset) if _selected(target, row)),
                           key=lambda row: _order_key(target, row)))


def _dataset(rows: tuple[_Row, ...]) -> LearningItemSqlDatasetV2:
    return LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(table="entries", rows=rows),))


def sqlite_comparison_dataset_v2(target: SqlitePredicateTargetV2) -> LearningItemSqlDatasetV2:
    """Common fifteen rows, including nine flag states, NULL, ties and duplicates."""
    seed = parse_sqlite_target_v2(target).seed
    rows: tuple[_Row, ...] = (
        (1, "Both", 1, 1, 60), (2, "Neither", 0, 0, 80), (3, "Fallback", None, 1, 70),
        (4, "Cursor", 1, 0, 70), (5, "After", 1, 0, 70), (6, "OnlyB", 0, 1, 69),
        (7, "NullB", 1, None, 71), (8, "Veto", 0, 1, 65), (9, "NullScore", 1, 0, None),
        (10, "NullNone", None, None, 68), (11, "Twin", 1, 0, 69), (12, "Twin", 1, 0, 69),
        (13, "Below", 1, 0, 59), (14, "NullA0", None, 0, 72), (15, "ZeroNull", 0, None, 66),
    )
    shifted = tuple((cast(int, identity) + seed, name, a, b,
        cast(int, score) + seed if score is not None else None) for identity, name, a, b, score in rows)
    # Fixed non-ordered input; the learner must implement the declared ordering.
    return _dataset(shifted[7:] + shifted[:7])


def sqlite_public_task_v2(target: SqlitePredicateTargetV2, *, guided: bool = False) -> SqlitePublicTaskV2:
    target = parse_sqlite_target_v2(target)
    instructions = {
        "conjunction": f"仅选择 flag_a 为 1 且 score 至少为 {target.min_score} 的行；NULL 不满足比较。按 id 升序。",
        "override_fallback": "flag_a 非 NULL 时用它，否则用 flag_b；有效值为 1 才入选，双 NULL 不入选。按 score 降序（NULL 最后），同值按 id 升序。",
        "exclusive": "flag_a 与 flag_b 恰好一个为 1 才入选；各自 NULL 当作 0。按 score 降序（NULL 最后），同值按 id 升序。",
        "keyset_after": f"全序为 score 降序、同分 id 升序；只选严格在游标 (score={target.cut_score}, id={target.cut_id}) 之后的行，不包含游标。游标不必是实体行；NULL score 不入选。",
    }
    instruction = instructions[target.task_kind] + (
        f" 公共参数为 min_score={target.min_score}、cut_score={target.cut_score}、cut_id={target.cut_id}；"
        "只有本题指定谓词使用的参数参与本题评分。五列全部可见，资格标志仅允许 0、1、NULL；"
        "所有整数范围为 -1000000 到 1000000，最多 200 行。仅返回名为 name 的一列，保留同名的每条匹配行；"
        "不得 DISTINCT 去重。使用一条只读单表 SELECT，不使用 JOIN、GROUP BY 或窗口函数。"
    )
    if guided:
        instruction += " 引导：先逐行确定资格与 NULL 的作用，再保留匹配行的 name，最后检查主排序和同值时的次排序；不要靠去重修复结果。"
    return SqlitePublicTaskV2(target=target, guided=guided, purpose="remediation" if guided else "exercise",
        instruction=instruction, content=LearningItemSqlContentV2(starter_query="SELECT name FROM entries WHERE 1 = 0;",
            tables=sqlite_tables_v2(), public_dataset=sqlite_comparison_dataset_v2(target), comparison="ordered", max_rows=200))


def _queries(target: SqlitePredicateTargetV2) -> tuple[tuple[str, str], tuple[tuple[SqliteFaultV2, str], ...]]:
    """Private complete lawful queries, not a query rewriting/interpreter framework."""
    if target.task_kind == "conjunction":
        predicate = f"flag_a = 1 AND score >= {target.min_score}"
        equivalent = f"CASE WHEN flag_a = 1 AND score >= {target.min_score} THEN 1 ELSE 0 END = 1"
        order = "id ASC"
        faults: tuple[tuple[SqliteFaultV2, str], ...] = (
            ("or_instead_of_and", f"flag_a = 1 OR score >= {target.min_score}"),
            ("strict_cutoff", f"flag_a = 1 AND score > {target.min_score}"),
        )
    elif target.task_kind == "override_fallback":
        predicate = "COALESCE(flag_a, flag_b) = 1"
        equivalent = "CASE WHEN flag_a IS NULL THEN flag_b ELSE flag_a END = 1"
        order = "score DESC NULLS LAST, id ASC"
        faults = (("ignores_override", "flag_b = 1"), ("missing_fallback", "flag_a = 1"))
    elif target.task_kind == "exclusive":
        predicate = "(COALESCE(flag_a, 0) = 1 AND COALESCE(flag_b, 0) = 0) OR (COALESCE(flag_a, 0) = 0 AND COALESCE(flag_b, 0) = 1)"
        equivalent = "COALESCE(flag_a, 0) + COALESCE(flag_b, 0) = 1"
        order = "score DESC NULLS LAST, id ASC"
        faults = (("inclusive_or", "COALESCE(flag_a, 0) = 1 OR COALESCE(flag_b, 0) = 1"), ("null_propagation", "flag_a + flag_b = 1"))
    else:
        predicate = f"score < {target.cut_score} OR (score = {target.cut_score} AND id > {target.cut_id})"
        equivalent = f"CASE WHEN score < {target.cut_score} THEN 1 WHEN score = {target.cut_score} AND id > {target.cut_id} THEN 1 ELSE 0 END = 1"
        order = "score DESC NULLS LAST, id ASC"
        faults = (("score_only", f"score < {target.cut_score}"),
                  ("includes_cursor", f"score < {target.cut_score} OR (score = {target.cut_score} AND id >= {target.cut_id})"))

    def query(where: str, ordering: str = order, projection: str = "name") -> str:
        return f"SELECT {projection} FROM entries WHERE ({where}) ORDER BY {ordering};"

    wrong = tuple((fault, query(where)) for fault, where in faults)
    wrong += (("distinct", query(predicate, projection="DISTINCT name")),)
    if target.task_kind == "conjunction":
        wrong += (("reverse_order", query(predicate, "id DESC")),)
    else:
        wrong += (("reverse_tie", query(predicate, order.replace("id ASC", "id DESC"))),
                  ("primary_ascending", query(predicate, order.replace("DESC", "ASC"))))
    return (query(predicate), query(equivalent)), wrong


def sqlite_counterexample_output_v2(target: SqlitePredicateTargetV2, dataset: LearningItemSqlDatasetV2,
                                   fault: SqliteFaultV2) -> SafeTableResultPresentationV1:
    """PRIVATE finite fault prediction; invalid schemas are never semantic negatives."""
    target = parse_sqlite_target_v2(target)
    if fault not in {name for name, _ in _queries(target)[1]}:
        raise ValueError("sqlite_v2_fault_not_declared")

    def selected(row: _Record) -> bool:
        if fault == "or_instead_of_and":
            return row.a == 1 or (row.score is not None and row.score >= target.min_score)
        if fault == "strict_cutoff":
            return row.a == 1 and row.score is not None and row.score > target.min_score
        if fault == "ignores_override":
            return row.b == 1
        if fault == "missing_fallback":
            return row.a == 1
        if fault == "inclusive_or":
            return row.a == 1 or row.b == 1
        if fault == "null_propagation":
            return row.a is not None and row.b is not None and row.a != row.b
        if fault == "score_only":
            return row.score is not None and row.score < target.cut_score
        if fault == "includes_cursor":
            return row.score is not None and (row.score < target.cut_score
                or (row.score == target.cut_score and row.identity >= target.cut_id))
        return _selected(target, row)

    def ordering(row: _Record) -> tuple[int, int, int]:
        null, metric, identity = _order_key(target, row)
        return (null, -metric if fault == "primary_ascending" else metric,
                -identity if fault in ("reverse_order", "reverse_tie") else identity)

    rows = sorted((row for row in _records(dataset) if selected(row)), key=ordering)
    if fault == "distinct":
        # Representative sort keys are unspecified for DISTINCT; lost multiplicity
        # alone predicts failure, not the exact SQLite terminal's representative.
        seen: set[str] = set()
        unique: list[_Record] = []
        for row in rows:
            if row.name not in seen:
                seen.add(row.name)
                unique.append(row)
        rows = unique
    return _project(rows)


def sqlite_private_fixture_v2(target: SqlitePredicateTargetV2, *, guided: bool = False) -> SqlitePrivateFixtureV2:
    target = parse_sqlite_target_v2(target)
    public = sqlite_public_task_v2(target, guided=guided)
    # Each hidden case owns independent row data, never the public answer table.
    boundary = _dataset(tuple((row.identity, "Private " + row.name, row.a, row.b, row.score)
        for row in reversed(_records(public.content.public_dataset))))
    no_match = _dataset(((1, "None", 0, 0, target.cut_score + 1), (2, "Null", None, None, None)))
    data = (("visible", public.content.public_dataset), ("boundary", boundary),
            ("no_match", no_match), ("empty_table", _dataset(())))
    cases = tuple(LearningItemSqlTestCaseV2(id=f"v2.{target.task_kind}.{name}",
        case_type="visible" if index == 0 else "hidden", dataset=dataset,
        expected_output=sqlite_oracle_v2(target, dataset), is_critical=True, order_index=index)
        for index, (name, dataset) in enumerate(data))
    references, faults = _queries(target)
    counterexamples = tuple(SqliteCounterexampleV2(fault=fault, query=query,
        failing_case_ids=tuple(case.id for case in cases
            if sqlite_counterexample_output_v2(target, case.dataset, fault) != case.expected_output))
        for fault, query in faults)
    return SqlitePrivateFixtureV2(target=target,
        family_id=cast(SqliteFamilyIdV2, f"{SQLITE_PROGRAM_TARGET_ID_V2}:{target.task_kind}"),
        public_task=public, equivalent_queries=references, private_cases=cases, counterexamples=counterexamples)


def sqlite_public_task_hash_v2(public: SqlitePublicTaskV2) -> str:
    public = checked_model(public, SqlitePublicTaskV2)
    if public != sqlite_public_task_v2(public.target, guided=public.guided):
        raise ValueError("sqlite_v2_public_task_not_exact")
    return canonical_hash(public.model_dump(mode="json"))


def sqlite_fixture_hash_v2(fixture: SqlitePrivateFixtureV2) -> str:
    fixture = checked_model(fixture, SqlitePrivateFixtureV2)
    if fixture != sqlite_private_fixture_v2(fixture.target, guided=fixture.public_task.guided):
        raise ValueError("sqlite_v2_fixture_not_exact")
    return canonical_hash(fixture.model_dump(mode="json"))
