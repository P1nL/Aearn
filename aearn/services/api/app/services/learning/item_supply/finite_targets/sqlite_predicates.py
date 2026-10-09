"""Closed SQL declarations and PRIVATE fixtures, never SQL execution or authority.

Counterexample outputs are finite predictions, not execution receipts. Source
admission, six family-pair reviews, sealed execution and integration are pending.
"""
from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast

from pydantic import Field, TypeAdapter

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

SQLITE_PROGRAM_TARGET_ID = "sqlite-predicate-order-v1"
SQLITE_RUNTIME_PROFILE = "sqlite-query-v1"
SQLITE_CLAUSE_IDS = ("SQL-C1", "SQL-C2", "SQL-C3")
SqliteTaskKind = Literal["conjunction", "override_fallback", "exclusive", "keyset_after"]
_Parameter = Annotated[int, Field(ge=-999_990, le=999_990)]


class _Target(StorageContract):
    schema_version: Literal["sqlite_predicate_target_v1"] = "sqlite_predicate_target_v1"
    program_target_id: Literal["sqlite-predicate-order-v1"] = "sqlite-predicate-order-v1"
    table_name: Literal["entries"] = "entries"
    projection: tuple[Literal["name"]] = ("name",)
    null_order: Literal["last"] = "last"


class ConjunctionTargetV1(_Target):
    task_kind: Literal["conjunction"] = "conjunction"
    min_score: _Parameter = 60


class OverrideFallbackTargetV1(_Target):
    task_kind: Literal["override_fallback"] = "override_fallback"


class ExclusiveTargetV1(_Target):
    task_kind: Literal["exclusive"] = "exclusive"


class KeysetAfterTargetV1(_Target):
    task_kind: Literal["keyset_after"] = "keyset_after"
    cut_score: _Parameter = 70
    cut_id: _Parameter = 4


SqlitePredicateTargetV1: TypeAlias = Annotated[
    ConjunctionTargetV1 | OverrideFallbackTargetV1 | ExclusiveTargetV1 | KeysetAfterTargetV1,
    Field(discriminator="task_kind"),
]
_TARGET_ADAPTER: TypeAdapter[SqlitePredicateTargetV1] = TypeAdapter(SqlitePredicateTargetV1)
_TARGET_TYPES = (ConjunctionTargetV1, OverrideFallbackTargetV1, ExclusiveTargetV1, KeysetAfterTargetV1)
_FAMILY_IDS: dict[SqliteTaskKind, str] = {
    "conjunction": "sqlite-predicate-order-v1:conjunction",
    "override_fallback": "sqlite-predicate-order-v1:override_fallback",
    "exclusive": "sqlite-predicate-order-v1:exclusive",
    "keyset_after": "sqlite-predicate-order-v1:keyset_after",
}
SqliteFamilyId = Literal[
    "sqlite-predicate-order-v1:conjunction", "sqlite-predicate-order-v1:override_fallback",
    "sqlite-predicate-order-v1:exclusive", "sqlite-predicate-order-v1:keyset_after",
]
_Cell = int | str | None
_Row = tuple[_Cell, ...]
_Record = dict[str, _Cell]
SqliteFault = Literal[
    "or_instead_of_and", "strict_cutoff", "ignores_override", "missing_fallback",
    "inclusive_or", "null_propagation", "score_only", "includes_cursor",
    "distinct", "reverse_order", "reverse_tie", "primary_ascending",
]


class SqlitePublicTaskV1(StorageContract):
    """No reference query, hidden cases or expected tables in this projection."""

    target: SqlitePredicateTargetV1
    instruction: str
    content: LearningItemSqlContentV2


class SqliteCounterexampleV1(StorageContract):
    fault: SqliteFault
    query: str
    failing_case_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    execution_status: Literal["pending"] = "pending"


class SqlitePrivateFixtureV1(StorageContract):
    """PRIVATE API-side answer catalog, never public/blind input."""

    target: SqlitePredicateTargetV1
    family_id: SqliteFamilyId
    public_task: SqlitePublicTaskV1
    equivalent_queries: tuple[str, str]
    private_cases: tuple[LearningItemSqlTestCaseV2, ...] = Field(min_length=1, max_length=8)
    counterexamples: tuple[SqliteCounterexampleV1, ...] = Field(min_length=1, max_length=8)
    execution_status: Literal["pending"] = "pending"
    family_independence_status: Literal["pending"] = "pending"


def parse_sqlite_target(value: object) -> SqlitePredicateTargetV1:
    if type(value) in _TARGET_TYPES:
        target = cast(SqlitePredicateTargetV1, value)
        return checked_model(target, type(target))
    if not isinstance(value, dict):
        raise ValueError("unsupported finite SQLite target")
    return _TARGET_ADAPTER.validate_python(value, strict=True)


def sqlite_target_hash(target: SqlitePredicateTargetV1) -> str:
    return canonical_hash(parse_sqlite_target(target).model_dump(mode="json"))


def sqlite_tables(target: SqlitePredicateTargetV1) -> tuple[LearningItemSqlTableV2, ...]:
    target = parse_sqlite_target(target)
    columns = [
        LearningItemSqlColumnV2(name="id", data_type="INTEGER", nullable=False, primary_key=True),
        LearningItemSqlColumnV2(name="name", data_type="TEXT", nullable=False),
    ]
    names = {
        "conjunction": ("active", "score"),
        "override_fallback": ("override_flag", "default_flag", "priority"),
        "exclusive": ("flag_a", "flag_b", "score"),
        "keyset_after": ("score",),
    }[target.task_kind]
    columns.extend(LearningItemSqlColumnV2(name=name, data_type="INTEGER") for name in names)
    return (LearningItemSqlTableV2(name="entries", columns=tuple(columns)),)


def _records(target: SqlitePredicateTargetV1, dataset: LearningItemSqlDatasetV2) -> list[_Record]:
    dataset = checked_model(dataset, LearningItemSqlDatasetV2)
    tables = sqlite_tables(target)
    _validate_sql_dataset(tables, dataset, maximum_rows=200)
    columns = tables[0].columns
    records: list[_Record] = []
    for row in dataset.tables[0].rows:
        for column, cell in zip(columns, row, strict=True):
            if cell is None or column.name == "name":
                continue
            if type(cell) is not int or not -1_000_000 <= cell <= 1_000_000:
                raise ValueError("finite SQLite integer outside declared domain")
            if column.name in {"active", "override_flag", "default_flag", "flag_a", "flag_b"} and cell not in (0, 1):
                raise ValueError("finite SQLite flag must be 0, 1 or NULL")
        records.append(dict(zip((column.name for column in columns), cast(_Row, row), strict=True)))
    return records


def _selected(target: SqlitePredicateTargetV1, row: _Record) -> bool:
    if isinstance(target, ConjunctionTargetV1):
        score = row["score"]
        return row["active"] == 1 and type(score) is int and score >= target.min_score
    if isinstance(target, OverrideFallbackTargetV1):
        effective = row["override_flag"] if row["override_flag"] is not None else row["default_flag"]
        return effective == 1
    if isinstance(target, ExclusiveTargetV1):
        a = 0 if row["flag_a"] is None else row["flag_a"]
        b = 0 if row["flag_b"] is None else row["flag_b"]
        return (a, b) in ((1, 0), (0, 1))
    score = row["score"]
    return type(score) is int and (
        score < target.cut_score or (score == target.cut_score and cast(int, row["id"]) > target.cut_id)
    )


def _order_key(target: SqlitePredicateTargetV1, row: _Record, *, reverse_tie: bool = False) -> tuple[int, int, int]:
    identity = cast(int, row["id"])
    if isinstance(target, ConjunctionTargetV1):
        return (0, 0, identity)
    value = row["priority" if isinstance(target, OverrideFallbackTargetV1) else "score"]
    return (int(value is None), -cast(int, value) if value is not None else 0, -identity if reverse_tie else identity)


def _project(rows: list[_Record]) -> SafeTableResultPresentationV1:
    return SafeTableResultPresentationV1(columns=("name",), rows=tuple((row["name"],) for row in rows))


def sqlite_oracle(target: SqlitePredicateTargetV1, dataset: LearningItemSqlDatasetV2) -> SafeTableResultPresentationV1:
    """Direct finite data traversal. No SQL parser, eval or execution."""
    target = parse_sqlite_target(target)
    rows = [row for row in _records(target, dataset) if _selected(target, row)]
    return _project(sorted(rows, key=lambda row: _order_key(target, row)))


def _dataset(rows: tuple[_Row, ...]) -> LearningItemSqlDatasetV2:
    return LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(table="entries", rows=rows),))


def sqlite_public_task(target: SqlitePredicateTargetV1) -> SqlitePublicTaskV1:
    target = parse_sqlite_target(target)
    if isinstance(target, ConjunctionTargetV1):
        instruction = f"仅选择 active 为 1 且 score 至少为 {target.min_score} 的行；NULL 不满足比较。按 id 升序。"
        rows: tuple[_Row, ...] = ((2, "Birch", 0, target.min_score + 1), (1, "Ash", 1, target.min_score))
    elif isinstance(target, OverrideFallbackTargetV1):
        instruction = "override_flag 非 NULL 时用它，否则用 default_flag；有效值为 1 才入选，双 NULL 不入选。按 priority 降序（NULL 最后），同值按 id 升序。"
        rows = ((2, "Birch", None, 1, 2), (1, "Ash", 0, 1, 3))
    elif isinstance(target, ExclusiveTargetV1):
        instruction = "flag_a 与 flag_b 恰好一个为 1 才入选；各自 NULL 当作 0。按 score 降序（NULL 最后），同值按 id 升序。"
        rows = ((2, "Birch", 1, 1, 8), (1, "Ash", 1, None, 8))
    else:
        instruction = f"全序为 score 降序、同分 id 升序；只选严格在游标 (score={target.cut_score}, id={target.cut_id}) 之后的行，不包含游标。游标不必是实体行；NULL score 不入选。"
        rows = ((target.cut_id + 1, "Birch", target.cut_score), (target.cut_id - 1, "Ash", target.cut_score + 1))
    instruction += " 仅返回名为 name 的一列，保留同名的每条匹配行；不得去重。整数范围为 -1000000 到 1000000，资格标志只允许 0、1、NULL。使用一条只读单表 SELECT，不使用 JOIN、GROUP BY 或窗口函数。"
    return SqlitePublicTaskV1(
        target=target, instruction=instruction,
        content=LearningItemSqlContentV2(
            starter_query="SELECT name FROM entries WHERE 1 = 0;",
            tables=sqlite_tables(target), public_dataset=_dataset(rows), comparison="ordered", max_rows=200,
        ),
    )


def _queries(target: SqlitePredicateTargetV1) -> tuple[tuple[str, str], tuple[tuple[SqliteFault, str], ...]]:
    """PRIVATE query literals. No parser or query execution lives here."""
    if isinstance(target, ConjunctionTargetV1):
        predicate = f"active = 1 AND score >= {target.min_score}"
        equivalent = f"CASE WHEN active = 1 THEN CASE WHEN score >= {target.min_score} THEN 1 ELSE 0 END ELSE 0 END = 1"
        order = "id ASC"
        faults: tuple[tuple[SqliteFault, str], ...] = (
            ("or_instead_of_and", f"active = 1 OR score >= {target.min_score}"),
            ("strict_cutoff", f"active = 1 AND score > {target.min_score}"),
        )
    elif isinstance(target, OverrideFallbackTargetV1):
        predicate = "COALESCE(override_flag, default_flag) = 1"
        equivalent = "CASE WHEN override_flag IS NOT NULL THEN override_flag ELSE default_flag END = 1"
        order = "priority DESC NULLS LAST, id ASC"
        faults = (("ignores_override", "default_flag = 1"), ("missing_fallback", "override_flag = 1"))
    elif isinstance(target, ExclusiveTargetV1):
        predicate = "(COALESCE(flag_a, 0) = 1 AND COALESCE(flag_b, 0) = 0) OR (COALESCE(flag_a, 0) = 0 AND COALESCE(flag_b, 0) = 1)"
        equivalent = "COALESCE(flag_a, 0) + COALESCE(flag_b, 0) = 1"
        order = "score DESC NULLS LAST, id ASC"
        faults = (("inclusive_or", "COALESCE(flag_a, 0) = 1 OR COALESCE(flag_b, 0) = 1"), ("null_propagation", "flag_a + flag_b = 1"))
    else:
        predicate = f"score < {target.cut_score} OR (score = {target.cut_score} AND id > {target.cut_id})"
        equivalent = f"CASE WHEN score < {target.cut_score} THEN 1 WHEN score = {target.cut_score} AND id > {target.cut_id} THEN 1 ELSE 0 END = 1"
        order = "score DESC NULLS LAST, id ASC"
        faults = (("score_only", f"score < {target.cut_score}"), ("includes_cursor", f"score < {target.cut_score} OR (score = {target.cut_score} AND id >= {target.cut_id})"))

    def query(where: str, ordering: str = order, projection: str = "name") -> str:
        return f"SELECT {projection} FROM entries WHERE ({where}) ORDER BY {ordering};"

    bad = tuple((fault, query(where)) for fault, where in faults)
    bad += (("distinct", query(predicate, projection="DISTINCT name")),)
    if isinstance(target, ConjunctionTargetV1):
        bad += (("reverse_order", query(predicate, "id DESC")),)
    else:
        bad += (("reverse_tie", query(predicate, order.replace("id ASC", "id DESC"))),)
        bad += (("primary_ascending", query(predicate, order.replace("DESC", "ASC"))),)
    return (query(predicate), query(equivalent)), bad


def sqlite_counterexample_output(target: SqlitePredicateTargetV1, dataset: LearningItemSqlDatasetV2, fault: SqliteFault) -> SafeTableResultPresentationV1:
    """PRIVATE finite fault prediction, not evaluation of arbitrary candidate SQL."""
    target = parse_sqlite_target(target)
    if fault not in {kind for kind, _ in _queries(target)[1]}:
        raise ValueError("fault not declared for this finite target")

    def selected(row: _Record) -> bool:
        if isinstance(target, ConjunctionTargetV1):
            score = row["score"]
            if fault == "or_instead_of_and":
                return row["active"] == 1 or (type(score) is int and score >= target.min_score)
            if fault == "strict_cutoff":
                return row["active"] == 1 and type(score) is int and score > target.min_score
        elif isinstance(target, OverrideFallbackTargetV1):
            if fault == "ignores_override":
                return row["default_flag"] == 1
            if fault == "missing_fallback":
                return row["override_flag"] == 1
        elif isinstance(target, ExclusiveTargetV1):
            if fault == "inclusive_or":
                return row["flag_a"] == 1 or row["flag_b"] == 1
            if fault == "null_propagation":
                return row["flag_a"] is not None and row["flag_b"] is not None and row["flag_a"] != row["flag_b"]
        else:
            score = row["score"]
            if fault == "score_only":
                return type(score) is int and score < target.cut_score
            if fault == "includes_cursor":
                return type(score) is int and (score < target.cut_score or (score == target.cut_score and cast(int, row["id"]) >= target.cut_id))
        return _selected(target, row)

    rows = sorted((row for row in _records(target, dataset) if selected(row)), key=lambda row: _order_key(target, row, reverse_tie=fault == "reverse_tie"))
    if fault == "reverse_order":
        rows.reverse()
    if fault == "primary_ascending":
        # Retain NULL LAST and id ASC, changing only the primary direction.
        rows.sort(key=lambda row: (_order_key(target, row)[0], -_order_key(target, row)[1], _order_key(target, row)[2]))
    if fault == "distinct":
        # SQL may choose a different representative for unprojected sort keys.
        # Missing multiplicity alone is enough; this is not an execution claim.
        seen: set[_Cell] = set()
        unique: list[_Record] = []
        for row in rows:
            if row["name"] not in seen:
                seen.add(row["name"])
                unique.append(row)
        rows = unique
    return _project(rows)


def _private_datasets(target: SqlitePredicateTargetV1) -> tuple[tuple[str, LearningItemSqlDatasetV2], ...]:
    if isinstance(target, ConjunctionTargetV1):
        score = target.min_score
        rows: tuple[_Row, ...] = (
            (9, "Later", 1, score + 1), (4, "Twin", 1, score), (3, "Twin", 1, score + 1),
            (1, "Early", 1, score), (2, "Inactive", 0, score + 1), (5, "Low", 1, score - 1),
            (6, "NullScore", 1, None), (7, "NullFlag", None, score), (8, "BothNull", None, None),
        )
        no_match: tuple[_Row, ...] = ((1, "None", 0, score + 1), (2, "Null", 1, None))
    elif isinstance(target, OverrideFallbackTargetV1):
        rows = (
            (8, "NullLast", 1, 0, None), (4, "Twin", None, 1, 5), (3, "Twin", 1, None, 5),
            (2, "Second", 1, 0, 5), (1, "First", 1, 1, 5), (5, "OverrideZero", 0, 1, 9),
            (6, "BothNull", None, None, 8), (7, "DefaultZero", None, 0, 7), (9, "NullLastTwo", None, 1, None),
            (12, "High", 1, 0, 9), (0, "LowRank", None, 1, 1),
        )
        no_match = ((1, "None", 0, 1, 3), (2, "Null", None, None, None))
    elif isinstance(target, ExclusiveTargetV1):
        rows = (
            (9, "NullLast", 1, 0, None), (4, "Twin", 0, 1, 10), (3, "Twin", 1, 0, 10),
            (2, "Second", None, 1, 10), (1, "First", 1, None, 10), (5, "Both", 1, 1, 11),
            (6, "Neither", 0, 0, 11), (7, "BothNull", None, None, 12), (8, "NullZero", None, 0, 12),
            (10, "ZeroNull", 0, None, 12), (11, "NullLastTwo", 0, 1, None),
            (12, "High", 1, 0, 12), (0, "LowRank", 0, 1, 5),
        )
        no_match = ((1, "Both", 1, 1, 3), (2, "Null", None, None, None))
    else:
        score, identity = target.cut_score, target.cut_id
        rows = (
            (identity + 4, "Twin", score - 1), (identity + 3, "Twin", score - 1),
            (identity + 2, "Second", score), (identity + 1, "First", score),
            (identity, "Cursor", score), (identity - 1, "Before", score),
            (identity - 2, "Higher", score + 1), (identity + 5, "Null", None),
        )
        no_match = ((identity - 1, "Before", score), (identity, "Cursor", score), (identity + 1, "Null", None))
    result: tuple[tuple[str, LearningItemSqlDatasetV2], ...] = (
        ("boundaries", _dataset(rows)), ("empty_result", _dataset(no_match)), ("empty_table", _dataset(())),
    )
    if isinstance(target, KeysetAfterTargetV1):
        result += (("absent_cursor", _dataset(tuple(row for row in rows if row[0] != target.cut_id))),)
    return result


def sqlite_private_fixture(target: SqlitePredicateTargetV1) -> SqlitePrivateFixtureV1:
    target = parse_sqlite_target(target)
    queries, faults = _queries(target)
    cases = tuple(LearningItemSqlTestCaseV2(
        id=f"{target.task_kind}.{name}", case_type="hidden", dataset=dataset,
        expected_output=sqlite_oracle(target, dataset), is_critical=True, order_index=index,
    ) for index, (name, dataset) in enumerate(_private_datasets(target)))
    negatives = tuple(SqliteCounterexampleV1(
        fault=fault, query=query,
        failing_case_ids=tuple(case.id for case in cases if sqlite_counterexample_output(target, case.dataset, fault) != case.expected_output),
    ) for fault, query in faults)
    return SqlitePrivateFixtureV1(
        target=target, family_id=cast(SqliteFamilyId, _FAMILY_IDS[target.task_kind]),
        public_task=sqlite_public_task(target), equivalent_queries=queries, private_cases=cases, counterexamples=negatives,
    )


def sqlite_fixture_hash(fixture: SqlitePrivateFixtureV1) -> str:
    fixture = checked_model(fixture, SqlitePrivateFixtureV1)
    if fixture != sqlite_private_fixture(fixture.target):
        raise ValueError("fixture does not match the finite target declaration")
    return canonical_hash(fixture.model_dump(mode="json"))
