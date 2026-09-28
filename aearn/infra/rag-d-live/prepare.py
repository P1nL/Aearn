"""Explicit test-owned parent and pending target via existing public API and ordinary Tutor loop.

Default is an explicitly labelled fixture. --real-parent additionally opts into
the actual configured provider and a checked transport/DB provenance artifact.
Never inserts draft/selection/binding rows directly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import sys
from uuid import uuid4

API = Path(__file__).resolve().parents[2] / "services" / "api"
C = Path(__file__).resolve().parents[1] / "rag-c-live"
CONTROL = Path(__file__).resolve().parents[1] / "rag-c-source-control"
for path in (API, CONTROL, C):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi.testclient import TestClient  # noqa: E402
from app.agents.harness.contracts import TutorTerminalOutcome  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.main import app  # noqa: E402
import app.routes.tutor as tutor_route  # noqa: E402
from app.services.tutor.interactive import TutorInteractiveRunDispatcher  # noqa: E402
from control_runtime import CONFIG, _absolute, _root_file, _root_json  # noqa: E402
from tests.learning.test_rag_d_planning_consumer import SqlFeedbackProvider  # noqa: E402
from tests.support.tutor_public_api_support import (  # noqa: E402
    RecordingTutorDispatcher, action_payload, create_tutor_user,
)
from run import (  # noqa: E402
    Denied, WallDeadlineExceeded, db_guard, guarded_name, install_private_database, install_private_provider, guard,
)


def prepare(*, execute: bool, control_config: str | None = None,
            source_provider: str = "direct",
            fixture_source_dsn_file: str | None = None,
            fixture_database_name: str | None = None, real_parent: bool = False,
            provider_config: str | None = None, runtime_profile_path: str | None = None,
            profile: str = "formal", draft_output_tokens: int | None = None,
            input_limit_tokens: int | None = None, dynamic_target_tokens: int | None = None,
            parent_provenance_out: str | None = None,
            prior_http_attempts: int | None = None, cumulative_http_cap: int | None = None,
            wall_seconds: int = 240, max_http: int = 8) -> dict[str, object]:
    if not execute:
        raise Denied("DEFAULT_OFF")
    if real_parent and (not control_config or fixture_source_dsn_file is not None
                        or fixture_database_name is not None or not provider_config or not runtime_profile_path
                        or not parent_provenance_out):
        raise Denied("REAL_PARENT_OPT_IN_REQUIRED")
    if not real_parent and (provider_config is not None or runtime_profile_path is not None
                            or parent_provenance_out is not None or prior_http_attempts is not None
                            or cumulative_http_cap is not None or profile != "formal"
                            or draft_output_tokens is not None or input_limit_tokens is not None
                            or dynamic_target_tokens is not None):
        raise Denied("REAL_PARENT_OPT_IN_REQUIRED")
    if not 30 <= wall_seconds <= 300 or not 1 <= max_http <= 8:
        raise Denied("MODEL_BOUND_DENIED")
    if os.name != "posix" or os.geteuid() != 0:
        raise Denied("ROOT_OPERATOR_REQUIRED")
    if control_config is not None and fixture_source_dsn_file is None and fixture_database_name is None:
        if source_provider == "tavily":
            from tavily_acquire import load_tavily_config
            config, dsn, _ = load_tavily_config(_absolute(control_config))
        elif source_provider == "direct":
            config, _ = _root_json(_absolute(control_config))
            if set(config) != CONFIG or config["approved"] is not True:
                raise Denied("CONTROL_CONFIG_DENIED")
            dsn = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)[0].decode().strip()
        else:
            raise Denied("SOURCE_PROVIDER_DENIED")
        name = guarded_name(config["database_name"])
    elif control_config is None and fixture_source_dsn_file is not None and fixture_database_name is not None:
        # No C config, grants or admission involved: this is solely a learner
        # fixture in a different disposable database.
        name = guarded_name(fixture_database_name)
        if not name.startswith("aearn_rag260_c_d_fixture_"):
            raise Denied("FIXTURE_DATABASE_DENIED")
        source = _root_file(_absolute(fixture_source_dsn_file), limit=4096)[0].decode().strip()
        source_name = guarded_name(str(conninfo_to_dict(source).get("dbname", "")))
        if source_name == name:
            raise Denied("FIXTURE_DATABASE_DENIED")
        dsn = make_conninfo(source, dbname=name)
    else:
        raise Denied("CONFIG_MODE_DENIED")
    if conninfo_to_dict(dsn).get("dbname") != name:
        raise Denied("DATABASE_DENIED")
    install_private_database(dsn)
    if real_parent:
        install_private_provider(provider_config)
        from run import install_runtime_profile
        install_runtime_profile(runtime_profile_path, profile=profile,
                                output_tokens=draft_output_tokens, input_tokens=input_limit_tokens,
                                dynamic_target_tokens=dynamic_target_tokens)
        settings = Settings(tutor_thread_turn_v2_enabled=True, tutor_codex_plan_drafting_enabled=False)
        guard(True, name, dsn, settings, max_http, wall_seconds=wall_seconds)
        if (type(prior_http_attempts) is not int or prior_http_attempts < 0 or
                type(cumulative_http_cap) is not int or prior_http_attempts + max_http > cumulative_http_cap):
            raise Denied("CUMULATIVE_MODEL_BOUND_DENIED")
        db_guard(dsn, settings, name)
        from real_parent import prepare_real
        return prepare_real(config=config, settings=settings, provenance_out=parent_provenance_out,
                            profile=profile, prior_http_attempts=prior_http_attempts,
                            cumulative_http_cap=cumulative_http_cap,
                            wall_seconds=wall_seconds, max_http=max_http)
    settings = Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True,
                        tutor_codex_plan_drafting_enabled=False)
    db_guard(dsn, settings, name)
    previous_dispatcher = tutor_route.build_tutor_run_dispatcher
    previous_settings = tutor_route.get_settings
    tutor_route.build_tutor_run_dispatcher = lambda _: RecordingTutorDispatcher()
    tutor_route.get_settings = lambda: settings
    try:
        with TestClient(app) as client:
            user = create_tutor_user(client)  # public user route, isolated cutover fixture
            user_id = str(user["id"])
            session_response = client.post("/api/learning-plan-sessions", json={
                "user_id": user_id, "client_action_id": "rag-d-live-session-" + uuid4().hex,
                "preferred_language_id": "sql",
            })
            if session_response.status_code not in {200, 201}:
                raise Denied("SESSION_API_DENIED")
            session = session_response.json()["session"]
            conversation_id = str(session["conversation_id"])
            def input_run() -> dict[str, object]:
                response = client.post(f"/api/tutor/conversations/{conversation_id}/inputs", json=action_payload(
                    user_id, "rag-d-live-input-" + uuid4().hex,
                    content="Revise the SQL queries learning plan using exact admitted material and report gaps.",
                    learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
                ))
                if response.status_code != 202:
                    raise Denied("INPUT_API_DENIED")
                return response.json()
            first = input_run()
            result = TutorInteractiveRunDispatcher(
                settings=settings, provider_factory=lambda _: SqlFeedbackProvider(),
            ).dispatch(user_id=user_id, run_id=str(first["run_id"]))
            if result.terminal_outcome is not TutorTerminalOutcome.COMPLETED or result.capability_call_count != 1:
                raise Denied("PARENT_FIXTURE_FAILED")
            with connect() as conn:
                parent = conn.execute(
                    "SELECT id,source_input_revision FROM tutor_learning_plan_drafts WHERE user_id=%s AND source_run_id=%s",
                    (user_id, str(first["run_id"])),
                ).fetchone()
                if parent is None:
                    raise Denied("PARENT_FIXTURE_FAILED")
                parent_id = str(parent["id"])
            second = input_run()
            return {"status": "test_owned_parent_and_pending_target", "parent_kind": "test_owned_fixture",
                    "user_id": user_id, "session_id": str(session["session_id"]),
                    "conversation_id": conversation_id, "parent_draft_id": parent_id,
                    "target_run_id": str(second["run_id"]),
                    "target_input_revision": int(second["input_revision"]),
                    "real_parent": False, "real_successor": "not_yet_dispatched"}
    finally:
        tutor_route.build_tutor_run_dispatcher = previous_dispatcher
        tutor_route.get_settings = previous_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source-provider", choices=("tavily", "direct"), default="tavily")
    parser.add_argument("--real-parent", action="store_true", help="actual provider, never fixture relabelling")
    parser.add_argument("--provider-config")
    parser.add_argument("--runtime-profile", dest="runtime_profile_path")
    parser.add_argument("--profile", choices=("formal", "boundary-test"), default="formal")
    parser.add_argument("--draft-output-tokens", type=int, help="boundary-test only")
    parser.add_argument("--input-limit-tokens", type=int, help="boundary-test only")
    parser.add_argument("--dynamic-target-tokens", type=int, help="boundary-test only; optional")
    parser.add_argument("--prior-http-attempts", type=int)
    parser.add_argument("--cumulative-http-cap", type=int)
    parser.add_argument("--parent-provenance-out")
    parser.add_argument("--wall-seconds", type=int, default=240)
    parser.add_argument("--max-http", type=int, default=8, help="parent-only transport cap, 1..8; use 4 after four spent attempts")
    parser.add_argument("--control-config")
    parser.add_argument("--fixture-source-dsn-file")
    parser.add_argument("--fixture-database-name")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(execute=args.execute, control_config=args.control_config,
                                 source_provider=args.source_provider,
                                 fixture_source_dsn_file=args.fixture_source_dsn_file,
                                 fixture_database_name=args.fixture_database_name, real_parent=args.real_parent,
                                 provider_config=args.provider_config, runtime_profile_path=args.runtime_profile_path,
                                 profile=args.profile, draft_output_tokens=args.draft_output_tokens,
                                 input_limit_tokens=args.input_limit_tokens,
                                 dynamic_target_tokens=args.dynamic_target_tokens,
                                 parent_provenance_out=args.parent_provenance_out,
                                 prior_http_attempts=args.prior_http_attempts, cumulative_http_cap=args.cumulative_http_cap,
                                 wall_seconds=args.wall_seconds, max_http=args.max_http), sort_keys=True))
        return 0
    except (Exception, WallDeadlineExceeded) as exc:
        print(json.dumps({"status": "blocked", "code": str(exc) if type(exc) in {Denied, WallDeadlineExceeded} else "PREPARE_INCOMPLETE"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
