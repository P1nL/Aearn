"""Pre-arm B signer gate for the *current* staged live worker and signer.

No DNS, HTTP, C bridge, source dispatch or DB access. This requests only a B
nonce using the independently pinned root-owned worker config. Run negative
PID-isolation probe first, then positive shared-PID probe; never arm on failure.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import time


def run(expect_reject: bool) -> None:
    if os.environ.get('RAG_C_SIGNER_PREFLIGHT_ONLY') != 'yes':
        raise SystemExit('SIGNER_PREFLIGHT_DEFAULT_OFF')
    from worker_once import HOST, _identity, _pins, load_config
    from app.services.grounding.autonomous.live_egress import LiveEgressAttestor
    from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied

    config = load_config()
    _identity(config)
    key, _image = _pins(config)
    if (config['b_socket'] != '/run/rag-attestor/attest.sock'
            or config['b_trusted_gid'] not in config['supplementary_gids']
            or Path('/etc/rag-c-dsn').exists() or Path('/review').exists()):
        raise SystemExit('SIGNER_PREFLIGHT_ISOLATION_DENIED')
    attestor = LiveEgressAttestor(
        socket_path=Path(config['b_socket']), public_key=key,
        deployment_id=config['b_deployment_id'], policy_sha256=config['b_policy_sha256'],
        trusted_gid=config['b_trusted_gid'],
    )
    # No resolver: the IP is read only from the operator's exact pinned config.
    try:
        receipt = asyncio.run(attestor.attest_envelope(host=HOST, ip=config['allowed_ips'][0]))
    except SafeFetchDenied:
        if expect_reject:
            print('SIGNER_PREFLIGHT_EXPECTED_SEPARATE_PID_REJECTION', flush=True)
            return
        raise SystemExit('SIGNER_PREFLIGHT_POSITIVE_DENIED') from None
    if expect_reject:
        raise SystemExit('SIGNER_PREFLIGHT_SEPARATE_PID_ACCEPTED')
    value = receipt.as_envelope()['receipt']
    if type(value) is not dict:
        raise SystemExit('SIGNER_PREFLIGHT_RECEIPT_DENIED')
    if (value['namespace_inode'] != config['expected_namespace_inode']
            or value['host'] != HOST or value['ip'] != config['allowed_ips'][0]
            or value['policy_sha256'] != config['b_policy_sha256']
            or value['deployment_id'] != config['b_deployment_id']
            or value['isolation_verified'] is not True
            or not time.time() < value['expires_unix'] <= time.time() + 4):
        raise SystemExit('SIGNER_PREFLIGHT_RECEIPT_DENIED')
    print('SIGNER_PREFLIGHT_CURRENT_SIGNER_PINNED_SIGNATURE_PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expect-separate-pid-rejection', action='store_true')
    args = parser.parse_args()
    run(args.expect_separate_pid_rejection)
