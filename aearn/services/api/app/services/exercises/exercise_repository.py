from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from psycopg import Connection

from app.services.exercises import adaptive_exercise_service
from app.services.curriculum.teaching_chunks import index_current_knowledge_point_chunks


def get_or_create_exercise_for_knowledge_point(
    conn: Connection[dict[str, object]],
    *,
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    existing = _load_exercise_row(conn, knowledge_point_id=str(knowledge_point["id"]))
    if existing is not None:
        return _serialize_exercise(conn, existing)

    template = _exercise_template(knowledge_point, runtime_profile)
    template = cast(
        dict[str, Any],
        adaptive_exercise_service.build_adaptive_exercise_template(
            conn,
            knowledge_point=knowledge_point,
            runtime_profile=runtime_profile,
            fallback_template=template,
        ),
    )
    created = conn.execute(
        """
        INSERT INTO exercises (
          slug, knowledge_point_id, runtime_profile_id, title, exercise_type,
          prompt_markdown, starter_code, solution_reference, visible_test_policy,
          difficulty, estimated_minutes, requires_explanation, metadata_json
        )
        VALUES (
          %(slug)s, %(knowledge_point_id)s, %(runtime_profile_id)s, %(title)s, %(exercise_type)s,
          %(prompt_markdown)s, %(starter_code)s, %(solution_reference)s, %(visible_test_policy)s,
          %(difficulty)s, %(estimated_minutes)s, %(requires_explanation)s, %(metadata_json)s::jsonb
        )
        RETURNING id
        """,
        {
            **template,
            "knowledge_point_id": str(knowledge_point["id"]),
            "runtime_profile_id": str(runtime_profile["id"]),
            "metadata_json": json.dumps(template["metadata_json"]),
        },
    ).fetchone()
    if created is None:
        raise RuntimeError("exercise insert returned no row")

    exercise_id = str(created["id"])
    for blank in template["code_blanks"]:
        conn.execute(
            """
            INSERT INTO code_blanks (
              exercise_id, blank_key, placeholder, expected_concept,
              acceptable_patterns_json, is_core, order_index
            )
            VALUES (
              %(exercise_id)s, %(blank_key)s, %(placeholder)s, %(expected_concept)s,
              %(acceptable_patterns_json)s::jsonb, %(is_core)s, %(order_index)s
            )
            """,
            {
                **blank,
                "exercise_id": exercise_id,
                "acceptable_patterns_json": json.dumps(blank["acceptable_patterns_json"]),
            },
        )

    for test_case in template["test_cases"]:
        conn.execute(
            """
            INSERT INTO test_cases (
              exercise_id, case_type, input_json, expected_output_json, assertion_code,
              weight, is_critical, timeout_ms, order_index
            )
            VALUES (
              %(exercise_id)s, %(case_type)s, %(input_json)s::jsonb, %(expected_output_json)s::jsonb,
              %(assertion_code)s, %(weight)s, %(is_critical)s, %(timeout_ms)s, %(order_index)s
            )
            """,
            {
                **test_case,
                "exercise_id": exercise_id,
                "input_json": json.dumps(test_case["input_json"]),
                "expected_output_json": json.dumps(test_case["expected_output_json"]),
            },
        )

    created_row = _load_exercise_row(conn, exercise_id=exercise_id)
    if created_row is None:
        raise RuntimeError("created exercise could not be loaded")
    exercise = _serialize_exercise(conn, created_row)
    index_current_knowledge_point_chunks(conn, str(knowledge_point["id"]))
    return exercise


def get_or_create_exercise_from_review_seed(
    conn: Connection[dict[str, object]],
    *,
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    seed: Mapping[str, object],
) -> dict[str, object]:
    existing = _load_exercise_row(
        conn,
        knowledge_point_id=str(knowledge_point["id"]),
        review_seed_id=str(seed["id"]),
    )
    if existing is not None:
        return _serialize_exercise(conn, existing)

    template = _exercise_template_from_review_seed(knowledge_point, runtime_profile, seed)
    created = conn.execute(
        """
        INSERT INTO exercises (
          slug, knowledge_point_id, runtime_profile_id, title, exercise_type,
          prompt_markdown, starter_code, solution_reference, visible_test_policy,
          difficulty, estimated_minutes, requires_explanation, metadata_json
        )
        VALUES (
          %(slug)s, %(knowledge_point_id)s, %(runtime_profile_id)s, %(title)s, %(exercise_type)s,
          %(prompt_markdown)s, %(starter_code)s, %(solution_reference)s, %(visible_test_policy)s,
          %(difficulty)s, %(estimated_minutes)s, %(requires_explanation)s, %(metadata_json)s::jsonb
        )
        RETURNING id
        """,
        {
            **template,
            "knowledge_point_id": str(knowledge_point["id"]),
            "runtime_profile_id": str(runtime_profile["id"]),
            "metadata_json": json.dumps(template["metadata_json"], ensure_ascii=False),
        },
    ).fetchone()
    if created is None:
        raise RuntimeError("review exercise insert returned no row")

    exercise_id = str(created["id"])
    for blank in template["code_blanks"]:
        conn.execute(
            """
            INSERT INTO code_blanks (
              exercise_id, blank_key, placeholder, expected_concept,
              acceptable_patterns_json, is_core, order_index
            )
            VALUES (
              %(exercise_id)s, %(blank_key)s, %(placeholder)s, %(expected_concept)s,
              %(acceptable_patterns_json)s::jsonb, %(is_core)s, %(order_index)s
            )
            """,
            {
                **blank,
                "exercise_id": exercise_id,
                "acceptable_patterns_json": json.dumps(blank["acceptable_patterns_json"], ensure_ascii=False),
            },
        )

    for test_case in template["test_cases"]:
        conn.execute(
            """
            INSERT INTO test_cases (
              exercise_id, case_type, input_json, expected_output_json, assertion_code,
              weight, is_critical, timeout_ms, order_index
            )
            VALUES (
              %(exercise_id)s, %(case_type)s, %(input_json)s::jsonb, %(expected_output_json)s::jsonb,
              %(assertion_code)s, %(weight)s, %(is_critical)s, %(timeout_ms)s, %(order_index)s
            )
            """,
            {
                **test_case,
                "exercise_id": exercise_id,
                "input_json": json.dumps(test_case["input_json"], ensure_ascii=False),
                "expected_output_json": json.dumps(test_case["expected_output_json"], ensure_ascii=False),
            },
        )

    created_row = _load_exercise_row(conn, exercise_id=exercise_id)
    if created_row is None:
        raise RuntimeError("created review exercise could not be loaded")
    exercise = _serialize_exercise(conn, created_row)
    index_current_knowledge_point_chunks(conn, str(knowledge_point["id"]))
    return exercise


def get_exercise(
    conn: Connection[dict[str, object]],
    exercise_id: str,
) -> dict[str, object] | None:
    row = _load_exercise_row(conn, exercise_id=exercise_id)
    if row is None:
        return None
    return _serialize_exercise(conn, row)


def _load_exercise_row(
    conn: Connection[dict[str, object]],
    *,
    exercise_id: str | None = None,
    knowledge_point_id: str | None = None,
    review_seed_id: str | None = None,
) -> Mapping[str, object] | None:
    conditions = [
        "exercises.archived_at IS NULL",
        "exercises.deleted_at IS NULL",
    ]
    params: dict[str, object] = {}
    if exercise_id is not None:
        conditions.append("exercises.id::text = %(exercise_id)s")
        params["exercise_id"] = exercise_id
    if knowledge_point_id is not None:
        conditions.append("exercises.knowledge_point_id::text = %(knowledge_point_id)s")
        params["knowledge_point_id"] = knowledge_point_id
    if review_seed_id is not None:
        conditions.append("exercises.metadata_json->>'review_seed_id' = %(review_seed_id)s")
        params["review_seed_id"] = review_seed_id

    if not params:
        return None

    return conn.execute(
        f"""
        SELECT
          exercises.*,
          runtime_profiles.slug AS runtime_profile_slug,
          runtime_profiles.runtime_tier,
          runtime_profiles.language AS runtime_language,
          runtime_profiles.runner,
          runtime_profiles.supports_realtime_preview,
          runtime_profiles.supports_stdout,
          runtime_profiles.supports_tests,
          runtime_profiles.compile_required,
          runtime_profiles.timeout_ms,
          runtime_profiles.memory_limit_mb,
          runtime_profiles.sandbox_policy
        FROM exercises
        JOIN runtime_profiles ON runtime_profiles.id = exercises.runtime_profile_id
        WHERE {" AND ".join(conditions)}
        ORDER BY exercises.created_at
        LIMIT 1
        """,
        params,
    ).fetchone()


def _serialize_exercise(
    conn: Connection[dict[str, object]],
    row: Mapping[str, object],
) -> dict[str, object]:
    exercise_id = str(row["id"])
    code_blanks = conn.execute(
        """
        SELECT *
        FROM code_blanks
        WHERE exercise_id = %s
        ORDER BY order_index
        """,
        (exercise_id,),
    ).fetchall()
    test_cases = conn.execute(
        """
        SELECT *
        FROM test_cases
        WHERE exercise_id = %s AND archived_at IS NULL
        ORDER BY order_index
        """,
        (exercise_id,),
    ).fetchall()
    return {
        "id": exercise_id,
        "knowledge_point_id": str(row["knowledge_point_id"]),
        "runtime_profile_id": str(row["runtime_profile_id"]),
        "title": row["title"],
        "exercise_type": row["exercise_type"],
        "prompt_markdown": row["prompt_markdown"],
        "starter_code": row["starter_code"],
        "solution_reference": row["solution_reference"],
        "visible_test_policy": row["visible_test_policy"],
        "difficulty": row["difficulty"],
        "estimated_minutes": row["estimated_minutes"],
        "requires_explanation": row["requires_explanation"],
        "metadata_json": row["metadata_json"],
        "runtime_profile": {
            "id": str(row["runtime_profile_id"]),
            "slug": row["runtime_profile_slug"],
            "runtime_tier": row["runtime_tier"],
            "language": row["runtime_language"],
            "runner": row["runner"],
            "supports_realtime_preview": row["supports_realtime_preview"],
            "supports_stdout": row["supports_stdout"],
            "supports_tests": row["supports_tests"],
            "compile_required": row["compile_required"],
            "timeout_ms": row["timeout_ms"],
            "memory_limit_mb": row["memory_limit_mb"],
            "sandbox_policy": row["sandbox_policy"],
        },
        "code_blanks": [_serialize_code_blank(blank) for blank in code_blanks],
        "test_cases": [_serialize_test_case(test_case) for test_case in test_cases],
    }


def _serialize_code_blank(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "blank_key": row["blank_key"],
        "placeholder": row["placeholder"],
        "expected_concept": row["expected_concept"],
        "acceptable_patterns_json": row["acceptable_patterns_json"],
        "is_core": row["is_core"],
        "order_index": row["order_index"],
    }


def _serialize_test_case(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "case_type": row["case_type"],
        "input_json": row["input_json"],
        "expected_output_json": row["expected_output_json"],
        "assertion_code": row["assertion_code"],
        "weight": _decimal_to_float(row["weight"]),
        "is_critical": row["is_critical"],
        "timeout_ms": row["timeout_ms"],
        "order_index": row["order_index"],
    }


def _exercise_template(
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, Any]:
    language = str(runtime_profile["language"])
    knowledge_point_id = str(knowledge_point["id"])
    title = str(knowledge_point["title"])
    description = str(knowledge_point.get("description") or "")

    if language == "python":
        return {
            "slug": f"m3-python-{knowledge_point_id}",
            "title": f"{title}：函数返回与 stdout",
            "exercise_type": "code_blank",
            "prompt_markdown": (
                f"围绕知识点 **{title}** 完成一个最小 Python 练习。\n\n"
                "要求：保留 `print` 输出，并让函数返回正确结果。"
                f"{' 当前知识点提示：' + description if description else ''}"
            ),
            "starter_code": (
                "def summarize_scores(scores):\n"
                "    total = sum(scores)\n"
                "    print(f\"total={total}\")\n"
                "    return __BLANK_1__\n\n"
                "result = summarize_scores([2, 3, 4])\n"
            ),
            "solution_reference": (
                "def summarize_scores(scores):\n"
                "    total = sum(scores)\n"
                "    print(f\"total={total}\")\n"
                "    return total\n\n"
                "result = summarize_scores([2, 3, 4])\n"
            ),
            "visible_test_policy": "visible_and_hidden_summary",
            "difficulty": 1,
            "estimated_minutes": 8,
            "requires_explanation": False,
            "metadata_json": {
                "required_patterns": ["print(", "return total"],
                "stdout_success": "total=9",
            },
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "total",
                    "expected_concept": "返回已经计算出的 total，而不是再次 print。",
                    "acceptable_patterns_json": [
                        {"type": "literal", "value": "total"},
                        {"type": "regex", "value": r"return\s+total"},
                    ],
                    "is_core": True,
                    "order_index": 0,
                },
            ],
            "test_cases": [
                {
                    "case_type": "visible",
                    "input_json": {"scores": [2, 3, 4]},
                    "expected_output_json": {"return": 9},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": True,
                    "timeout_ms": 5000,
                    "order_index": 0,
                },
                {
                    "case_type": "visible",
                    "input_json": {"stdout": "total=9"},
                    "expected_output_json": {"stdout": "total=9"},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": False,
                    "timeout_ms": 5000,
                    "order_index": 1,
                },
            ],
        }

    if language == "html_css":
        return {
            "slug": f"m3-htmlcss-{knowledge_point_id}",
            "title": f"{title}：补全交互态 class",
            "exercise_type": "code_blank",
            "prompt_markdown": (
                f"围绕知识点 **{title}** 完成一个最小浏览器预览练习。\n\n"
                "要求：让按钮带上 `.active` 状态类，便于在预览里确认交互态。"
            ),
            "starter_code": (
                "<button class=\"pill __BLANK_1__\">Preview ready</button>\n"
                "<style>\n"
                "  .pill { padding: 8px 14px; border-radius: 999px; background: #dbeafe; color: #1e3a8a; }\n"
                "  .pill.active { background: #0f766e; color: white; }\n"
                "</style>\n"
            ),
            "solution_reference": (
                "<button class=\"pill active\">Preview ready</button>\n"
                "<style>\n"
                "  .pill { padding: 8px 14px; border-radius: 999px; background: #dbeafe; color: #1e3a8a; }\n"
                "  .pill.active { background: #0f766e; color: white; }\n"
                "</style>\n"
            ),
            "visible_test_policy": "visible_only",
            "difficulty": 1,
            "estimated_minutes": 6,
            "requires_explanation": False,
            "metadata_json": {
                "required_patterns": ["active"],
                "preview_html": {
                    "success": "<button class=\"pill active\">Preview ready</button>",
                    "failure": "<button class=\"pill\">Preview missing active class</button>",
                },
            },
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "active",
                    "expected_concept": "把 active 类名补到按钮上。",
                    "acceptable_patterns_json": [
                        {"type": "literal", "value": "active"},
                        {"type": "regex", "value": r"active"},
                    ],
                    "is_core": True,
                    "order_index": 0,
                },
            ],
            "test_cases": [
                {
                    "case_type": "preview_assertion",
                    "input_json": {"selector": ".pill.active"},
                    "expected_output_json": {"exists": True},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": True,
                    "timeout_ms": 5000,
                    "order_index": 0,
                },
            ],
        }

    if language == "java":
        return {
            "slug": f"m3-java-{knowledge_point_id}",
            "title": f"{title}：Java 方法返回值",
            "exercise_type": "code_blank",
            "prompt_markdown": (
                f"围绕知识点 **{title}** 完成一个最小 Java 方法练习。\n\n"
                "要求：保留 `public class Main` 和 `public static int increment(int value)`，让方法返回加一后的结果。"
            ),
            "starter_code": (
                "public class Main {\n"
                "    public static int increment(int value) {\n"
                "        return __BLANK_1__;\n"
                "    }\n"
                "}\n"
            ),
            "solution_reference": (
                "public class Main {\n"
                "    public static int increment(int value) {\n"
                "        return value + 1;\n"
                "    }\n"
                "}\n"
            ),
            "visible_test_policy": "visible_and_hidden_summary",
            "difficulty": 1,
            "estimated_minutes": 8,
            "requires_explanation": False,
            "metadata_json": {
                "entry_function": "increment",
                "required_patterns": ["public class Main", "public static int increment", "return value + 1"],
                "managed_compiled": {
                    "source_file": "Main.java",
                    "class_name": "Main",
                    "unsupported": ["maven", "gradle", "external_dependencies", "arbitrary_project"],
                },
            },
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "value + 1",
                    "expected_concept": "返回加一后的结果。",
                    "acceptable_patterns_json": [
                        {"type": "literal", "value": "value + 1"},
                        {"type": "regex", "value": r"value\s*\+\s*1"},
                    ],
                    "is_core": True,
                    "order_index": 0,
                },
            ],
            "test_cases": [
                {
                    "case_type": "visible",
                    "input_json": {"args": [1]},
                    "expected_output_json": {"return": 2},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": True,
                    "timeout_ms": 5000,
                    "order_index": 0,
                },
                {
                    "case_type": "hidden",
                    "input_json": {"args": [-2]},
                    "expected_output_json": {"return": -1},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": False,
                    "timeout_ms": 5000,
                    "order_index": 1,
                },
            ],
        }

    if language == "sql":
        return {
            "slug": f"m3-sql-{knowledge_point_id}",
            "title": f"{title}：SQLite SELECT 查询",
            "exercise_type": "code_blank",
            "prompt_markdown": (
                f"围绕知识点 **{title}** 完成一个只读 SQL 查询练习。\n\n"
                "要求：从 `learners` 表中筛选 `track` 为 `sql` 的学习者，并按 `id` 排序返回 `name` 列。"
                f"{' 当前知识点提示：' + description if description else ''}"
            ),
            "starter_code": (
                "SELECT name\n"
                "FROM learners\n"
                "WHERE __BLANK_1__\n"
                "ORDER BY id;\n"
            ),
            "solution_reference": (
                "SELECT name\n"
                "FROM learners\n"
                "WHERE track = 'sql'\n"
                "ORDER BY id;\n"
            ),
            "visible_test_policy": "visible_and_hidden_summary",
            "difficulty": 1,
            "estimated_minutes": 7,
            "requires_explanation": False,
            "metadata_json": {
                "required_patterns": ["SELECT name", "FROM learners", "WHERE", "ORDER BY id"],
                "sql": {
                    "dialect": "sqlite",
                    "comparison": "ordered",
                    "max_rows": 20,
                    "setup_sql": [
                        (
                            "CREATE TABLE learners ("
                            "id INTEGER PRIMARY KEY, "
                            "name TEXT NOT NULL, "
                            "track TEXT NOT NULL"
                            ");"
                        ),
                        (
                            "INSERT INTO learners (name, track) VALUES "
                            "('Ada', 'python'), "
                            "('Grace', 'sql'), "
                            "('Linus', 'systems');"
                        ),
                    ],
                },
            },
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "track = 'sql'",
                    "expected_concept": "用 WHERE 条件筛选 track 为 sql 的记录。",
                    "acceptable_patterns_json": [
                        {"type": "literal", "value": "track = 'sql'"},
                        {"type": "regex", "value": r"track\s*=\s*'sql'"},
                    ],
                    "is_core": True,
                    "order_index": 0,
                },
            ],
            "test_cases": [
                {
                    "case_type": "visible",
                    "input_json": {},
                    "expected_output_json": {
                        "columns": ["name"],
                        "rows": [{"name": "Grace"}],
                    },
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": True,
                    "timeout_ms": 5000,
                    "order_index": 0,
                },
                {
                    "case_type": "hidden",
                    "input_json": {},
                    "expected_output_json": {
                        "columns": ["name"],
                        "rows": [{"name": "Grace"}],
                    },
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": False,
                    "timeout_ms": 5000,
                    "order_index": 1,
                },
            ],
        }

    if language == "cpp":
        starter_code = (
            "#include <iostream>\n\n"
            "int increment(int value) {\n"
            "    return __BLANK_1__;\n"
            "}\n"
        )
        return {
            "slug": f"m3-cpp-{knowledge_point_id}",
            "title": f"{title}：C++ 静态补全占位题",
            "exercise_type": "code_blank",
            "prompt_markdown": (
                f"围绕知识点 **{title}** 做一次静态补全。\n\n"
                "C++ 的完整编译运行沙箱不在当前范围内，此题只用于展示能力边界。"
            ),
            "starter_code": starter_code,
            "solution_reference": starter_code.replace("__BLANK_1__", "value + 1"),
            "visible_test_policy": "visible_only",
            "difficulty": 1,
            "estimated_minutes": 5,
            "requires_explanation": False,
            "metadata_json": {},
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "value + 1",
                    "expected_concept": "返回加一后的结果。",
                    "acceptable_patterns_json": [
                        {"type": "literal", "value": "value + 1"},
                        {"type": "regex", "value": r"value\s*\+\s*1"},
                    ],
                    "is_core": True,
                    "order_index": 0,
                },
            ],
            "test_cases": [
                {
                    "case_type": "visible",
                    "input_json": {"value": 1},
                    "expected_output_json": {"return": 2},
                    "assertion_code": None,
                    "weight": 1,
                    "is_critical": True,
                    "timeout_ms": 5000,
                    "order_index": 0,
                },
            ],
        }

    return {
        "slug": f"m3-browser-{knowledge_point_id}",
        "title": f"{title}：事件绑定与共享状态",
        "exercise_type": "code_blank",
        "prompt_markdown": (
            f"围绕知识点 **{title}** 完成一个最小浏览器练习。\n\n"
            "要求：绑定按钮点击事件，递增共享状态，并把结果写回页面。"
            f"{' 当前知识点提示：' + description if description else ''}"
        ),
        "starter_code": (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n\n"
            "button.__BLANK_1__(\"click\", () => {\n"
            "  __BLANK_2__;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        ),
        "solution_reference": (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        ),
        "visible_test_policy": "visible_and_hidden_summary",
        "difficulty": 1,
        "estimated_minutes": 8,
        "requires_explanation": True,
        "metadata_json": {
            "required_patterns": ["addEventListener", "count += 1", "output.textContent"],
            "preview_html": {
                "success": (
                    "<section class=\"preview-card\">"
                    "<button id=\"counter-button\">Clicked</button>"
                    "<p id=\"counter-output\">1</p>"
                    "</section>"
                ),
                "failure": (
                    "<section class=\"preview-card preview-card--error\">"
                    "<button id=\"counter-button\">Clicked</button>"
                    "<p id=\"counter-output\">0</p>"
                    "</section>"
                ),
            },
        },
        "code_blanks": [
            {
                "blank_key": "blank_1",
                "placeholder": "addEventListener",
                "expected_concept": "把点击监听器绑定到按钮上。",
                "acceptable_patterns_json": [
                    {"type": "literal", "value": "addEventListener"},
                    {"type": "regex", "value": r"addEventListener"},
                ],
                "is_core": True,
                "order_index": 0,
            },
            {
                "blank_key": "blank_2",
                "placeholder": "count += 1",
                "expected_concept": "在回调里递增共享状态。",
                "acceptable_patterns_json": [
                    {"type": "literal", "value": "count += 1"},
                    {"type": "regex", "value": r"count\s*\+=\s*1"},
                ],
                "is_core": True,
                "order_index": 1,
            },
        ],
        "test_cases": [
            {
                "case_type": "visible",
                "input_json": {"event": "click"},
                "expected_output_json": {"textContent": "1"},
                "assertion_code": None,
                "weight": 1,
                "is_critical": True,
                "timeout_ms": 5000,
                "order_index": 0,
            },
            {
                "case_type": "hidden",
                "input_json": {"event": "three_clicks"},
                "expected_output_json": {"textContent": "3"},
                "assertion_code": None,
                "weight": 1,
                "is_critical": False,
                "timeout_ms": 5000,
                "order_index": 1,
            },
            {
                "case_type": "preview_assertion",
                "input_json": {"selector": "#counter-output"},
                "expected_output_json": {"textContent": "1"},
                "assertion_code": None,
                "weight": 1,
                "is_critical": False,
                "timeout_ms": 5000,
                "order_index": 2,
            },
        ],
    }


def _exercise_template_from_review_seed(
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    seed: Mapping[str, object],
) -> dict[str, Any]:
    knowledge_point_id = str(knowledge_point["id"])
    seed_id = str(seed["id"])
    exercise_type = str(seed["exercise_type"])
    seed_metadata_value = seed.get("metadata")
    seed_metadata = cast(Mapping[str, object], seed_metadata_value) if isinstance(seed_metadata_value, Mapping) else {}
    metadata_json = {
        **dict(seed_metadata),
        "review_seed_id": seed_id,
        "target_misconception": seed.get("target_misconception"),
        "seed_generator_version": "review_seed_bank_v1",
    }
    starter_code = str(seed.get("starter_code") or "")
    code_blanks = _review_seed_code_blanks(seed)
    solution_reference = _solution_from_seed(starter_code, code_blanks)
    if exercise_type == "review_ai_patch":
        solution_reference = None
        metadata_json["review_ai_patch"] = {
            "requirement": metadata_json.get("requirement"),
            "original_code": metadata_json.get("original_code"),
            "ai_diff": metadata_json.get("ai_diff"),
            "review_focus": metadata_json.get("review_focus"),
            "expected_risk": metadata_json.get("expected_risk"),
            "expected_verdict": metadata_json.get("expected_verdict"),
            "expected_next_action": metadata_json.get("expected_next_action"),
            "rubric": seed.get("rubric") if isinstance(seed.get("rubric"), Mapping) else {},
        }
    return {
        "slug": f"review-{seed_id}-{knowledge_point_id}",
        "title": f"{knowledge_point['title']}：复习变体",
        "exercise_type": exercise_type,
        "prompt_markdown": str(seed.get("prompt_markdown") or ""),
        "starter_code": starter_code,
        "solution_reference": solution_reference,
        "visible_test_policy": "visible_only",
        "difficulty": seed.get("difficulty") or 2,
        "estimated_minutes": 10 if exercise_type == "review_ai_patch" else 8,
        "requires_explanation": exercise_type in {"explain_code", "review_ai_patch"},
        "metadata_json": metadata_json,
        "code_blanks": code_blanks,
        "test_cases": _review_seed_test_cases(seed),
    }


def _review_seed_code_blanks(seed: Mapping[str, object]) -> list[Mapping[str, object]]:
    blanks = seed.get("code_blanks")
    if not isinstance(blanks, list):
        return []
    return [blank for blank in blanks if isinstance(blank, Mapping)]


def _review_seed_test_cases(seed: Mapping[str, object]) -> list[Mapping[str, object]]:
    cases = seed.get("test_cases")
    if not isinstance(cases, list):
        return []
    return [case for case in cases if isinstance(case, Mapping)]


def _solution_from_seed(starter_code: str, code_blanks: Sequence[Mapping[str, object]]) -> str | None:
    if not starter_code:
        return None
    solution = starter_code
    for blank in code_blanks:
        blank_key = str(blank.get("blank_key") or "")
        placeholder = str(blank.get("placeholder") or "")
        if blank_key and placeholder:
            solution = solution.replace(f"__{blank_key.upper()}__", placeholder)
    return solution


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0
