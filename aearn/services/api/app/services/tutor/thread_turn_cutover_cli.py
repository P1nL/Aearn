"""Operator CLI for the global Tutor thread/turn v2 cutover."""
from __future__ import annotations

import argparse
import json

from app.db.connection import connect
from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the Tutor thread/turn v2 global cutover")
    parser.add_argument("action", choices=("status", "dry-run", "prepare", "enable", "rollback"))
    parser.add_argument("--expected-generation", type=int, default=0)
    parser.add_argument("--summary-hash")
    parser.add_argument("--idempotency-key", default="operator-local")
    args = parser.parse_args()
    with connect() as conn:
        service = TutorThreadTurnCutoverService(conn)
        if args.action == "status":
            result = service.status()
        elif args.action == "dry-run":
            result = service.dry_run()
        elif args.action == "prepare":
            result = service.prepare(expected_generation=args.expected_generation, idempotency_key=args.idempotency_key)
        elif args.action == "enable":
            if not args.summary_hash:
                parser.error("enable requires --summary-hash")
            result = service.enable(expected_generation=args.expected_generation, summary_hash=args.summary_hash, idempotency_key=args.idempotency_key)
        else:
            result = service.rollback(expected_generation=args.expected_generation, idempotency_key=args.idempotency_key)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
