"""Local-only corpus operator CLI. No schema bootstrap or remote control surface."""
from __future__ import annotations

import argparse
import json
from typing import Never, Sequence
from uuid import UUID

from app.db.connection import connect
from app.services.grounding.corpus_repository import CorpusConflict, CorpusNotFound
from app.services.grounding.corpus_service import CorpusOperationError, CorpusService


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid corpus id") from exc


def _generation(value: str) -> int:
    try:
        generation = int(value)
        if generation < 0:
            raise ValueError
        return generation
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected generation must be nonnegative") from exc


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CorpusOperationError("INVALID_REQUEST")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeParser(description="Operate the local, fixture-only RAG corpus")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--subject", required=True)
    reindex = sub.add_parser("reindex")
    reindex.add_argument("--subject", required=True)
    reindex.add_argument("--subject-version", required=True)
    reindex.add_argument("--mode", choices=("fixture", "fetch"), default="fixture")
    validate = sub.add_parser("validate")
    validate.add_argument("--corpus-id", type=_uuid, required=True)
    validate.add_argument("--expected-generation", type=_generation, required=True)
    diff = sub.add_parser("diff")
    diff.add_argument("--candidate-id", type=_uuid, required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--candidate-id", type=_uuid, required=True)
    activate.add_argument("--expected-generation", type=_generation, required=True)
    activate.add_argument("--summary-hash", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--subject", required=True)
    rollback.add_argument("--target-corpus-id", type=_uuid, required=True)
    rollback.add_argument("--expected-generation", type=_generation, required=True)
    retire = sub.add_parser("retire")
    retire.add_argument("--corpus-id", type=_uuid, required=True)
    for command in (reindex, validate, diff, activate, rollback, retire):
        command.add_argument("--idempotency-key", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        with connect() as conn:
            service = CorpusService(conn)
            if args.action == "status":
                result = service.status(args.subject)
            elif args.action == "reindex":
                result = service.reindex(args.subject, args.subject_version,
                                         mode=args.mode, idempotency_key=args.idempotency_key)
            elif args.action == "validate":
                result = service.validate(args.corpus_id, expected_generation=args.expected_generation,
                                          idempotency_key=args.idempotency_key)
            elif args.action == "diff":
                result = service.diff(args.candidate_id, idempotency_key=args.idempotency_key)
            elif args.action == "activate":
                result = service.activate(args.candidate_id, expected_generation=args.expected_generation,
                                          summary_hash=args.summary_hash, idempotency_key=args.idempotency_key)
            elif args.action == "rollback":
                result = service.rollback(args.subject, args.target_corpus_id,
                                          expected_generation=args.expected_generation,
                                          idempotency_key=args.idempotency_key)
            else:
                result = service.retire(args.corpus_id, idempotency_key=args.idempotency_key)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 2
    except CorpusOperationError as exc:
        code = exc.code
        exit_code = 2
    except CorpusConflict:
        code = "CORPUS_CONFLICT"
        exit_code = 3
    except CorpusNotFound:
        code = "CORPUS_NOT_FOUND"
        exit_code = 2
    except (ValueError, TypeError):
        code = "INVALID_REQUEST"
        exit_code = 2
    except Exception:
        # Never print a DB exception, DSN, fetched page, or provider body.
        code = "INTERNAL_ERROR"
        exit_code = 4
    print(json.dumps({"ok": False, "code": code}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
