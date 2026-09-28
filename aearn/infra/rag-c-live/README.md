# RAG C disposable two-container boundary — DEFAULT OFF

**Status (2026-09-25): real capture → automated service review → supplementary admission → partial corpus activation verified in the disposable DB.** The 2,033,807-byte capture yields only two approved WHERE/LIMIT excerpts; this is not whole-page review, main-teaching approval, assessment evidence or full SQL coverage. The original unknown attempt is preserved. The separately approved two-extra-GET budget is exhausted (one diagnostic plus this settled GET); no automatic retry is allowed. This directory
provides a deliberately limited two-container *diagnostic* profile, plus explicit
operator-only `control_runtime.py` and `worker_once.py` entry points in a separate
`Dockerfile.runtime`. The diagnostic images still contain no DB adapter or
fetcher. Neither `docker compose up` nor a passing probe authorizes a live request. Do not
substitute a host `curl`, B's old one-time smoke, a mock receipt, or a network
exception to PostgreSQL. No credentials, keys, captured body, or resolved IPs
belong in Git, image layers, logs, or this directory.

## Boundary and inputs

- `compose.offline.yaml` starts only with `--profile offline-preflight`. Its
  `control-proof` service uses a distinct **internal** network and the fresh
  named Unix-socket volume. It does not connect to a database; for a later live
  deployment, only an independently verified disposable
  `aearn_rag260_c_*` PostgreSQL database may share that network. Confirm
  `SELECT current_database()` before schema bootstrap twice or any write.
  Audit all network members, routes, aliases, host gateway, and published ports:
  Compose `internal: true` alone does not prove "DB-only" access.
- `egress-proof` uses a different namespace/network. It has **no** DB URL,
  credentials, Docker socket, host network, shared PID/network namespace, or
  host-mounted application source. The approved pinned base and final image
  must be reviewed; B's `attestor.install` installs IPv4/IPv6 OUTPUT DROP
  before any probe, with only the configured DNS IPv4 TCP/UDP 53 and public
  target IPv4 TCP 443 exceptions. The probe drops to the configured non-root
  UID/GID with zero capabilities and `NoNewPrivs=1`. Root/NET_ADMIN is confined
  to the diagnostic launcher. Its bootstrap also needs SETUID/SETGID/SETPCAP
  to enter the worker identity and drop the bounding set; the worker must have
  zero effective/bounding capabilities. The control bootstrap needs only CHOWN
  to provision the dedicated socket group. The actual B signer is **not started** by this
  offline image; successful rules do not establish a signed pre-dial receipt.
- The named volume is fresh and Linux-owned. `control_peer.py` creates
  `root:trusted-GID` mode 0750 directory and 0660 socket. Both sides inspect
  `SO_PEERCRED` UID/GID and accept `pid=0` across PID namespaces, then exchange
  an unpredictable one-time challenge and compare network namespace inodes.
  The challenge is **not** a live C grant
  or signature; a successful mount handshake is not a firewall or DB proof.
  Windows bind mounts cannot stand in for these Linux ownership semantics.
- Egress config is a **separately reviewed root-owned file in the Linux VM**, in
  B's `config.example.json` format. Require exactly `www.sqlite.org` and
  operator-selected public IP(s); never use an IP copied from a previous lab.
  This repo supplies no DNS address, key, secret, image tag, or deployment ID.
  Both image variables in Compose must be immutable `@sha256:` references to
  built, reviewed final images; their bases must also be digest-pinned.
  `docker compose config` interpolation is not a pin/authenticity check.

To construct the **offline-only** images, review B's Dockerfile and attestor,
then build `Dockerfile.control` and `Dockerfile.egress` with reviewed
`AEARN_CONTROL_BASE`/`AEARN_EGRESS_BASE` image digest references from the repo
root. The egress base needs Python 3, cryptography, a reviewed iptables and
ip6tables backend, and util-linux `setpriv`; no installer downloads anything.
Place a new Linux-root-owned B config outside the repository. Supply its
absolute VM path plus `RAG_C_CONTROL_IMAGE`, `RAG_C_EGRESS_IMAGE`,
`RAG_C_WORKER_UID`, `RAG_C_WORKER_GID`, and `RAG_C_BRIDGE_GID` only to the
reviewed offline Compose invocation. These IDs must match the B config exactly.
Never promote this profile or its diagnostic images into the live service.

## Offline preflight and stop conditions

The offline probe checks actual `iptables`/`ip6tables` OUTPUT DROP rules via
B's installer/validator, then observes a DROP *counter increment for each*
non-root TCP probe: IPv4 loopback, RFC1918, link-local/metadata, DNS-IP:5432,
IPv6 loopback/ULA/link-local, and each pinned public target IPv4 on ports 80
and 8443. It never connects to target port 443 and never sends an HTTP request.
A route error/no counter delta is **inconclusive and fails closed**, even if
`connect()` failed. Root/worker identities, mount owner/mode, peer UID/GID,
capability bounds, and no-new-privileges must all pass. Review both container
logs for only `CONTROL_PEER_READY`, `CONTROL_PEER_ACCEPTED`, and
`OFFLINE_PREFLIGHT_ONLY; LIVE_NOT_AUTHORIZED`; any `*_DENIED` fails.

These checks are not sufficient for a live Docker Desktop claim. An operator
must independently inspect the **actual VM kernel datapath** (nft vs legacy,
other chains, route and namespace membership), target IP pin, DNS egress and
its exfiltration risk, IPv4/IPv6 policy, restart behavior, image provenance,
root UID mapping, socket mount, absence of private TCP including PG, and
positive TCP 443 restrictions **without any target GET**. Do not bypass an
unroutable IPv6 probe or alternate firewall backend by weakening the check.
A timed-out or ambiguous probe remains `not_executed` for the live request.
Run local script unit tests without Docker via
`python -m unittest discover -s aearn/infra/rag-c-live/tests -v` from repo root.

## Required LIVE staging (explicit entry points; acceptance still blocked)

The current B `run.py` starts the worker immediately after an ephemeral signer
becomes ready. That is **incompatible** with an independent pin handoff. Do
not start B `run.py` as the live C worker, and do not self-pin from its worker
variables or mounted key files. A separate reviewed runner and host adapter
must implement these sequential, durable operator-held phases before a single
GET may even be considered:

1. **Signer-only bootstrap:** start B firewall/signer in the final, dedicated
   egress namespace with worker dispatch physically disabled. Capture the
   ephemeral Ed25519 public key fingerprint, *actual* `policy_sha256`,
   deployment ID, namespace inode, reviewed DNS/target IP rules and image
   digest through an independent root/operator channel. Pin them in a
   root-owned control config; reject a signer restart/key rotation until a
   fresh review. The worker mount and environment are not a trust anchor.
2. **Control start:** load the reviewed B pin config into the trusted control
   adapter. It must compare B signature, policy digest, deployment, expected
   namespace, exact host/IP and freshness on every proof, and use only the
   verified disposable DB. Start C `GrantServer` with a real, current DB
   resolver/atomic settlement callback, not fakes. Independently capture its
   ephemeral public-key fingerprint/deployment ID, mapped peer UID/GID and
   socket owner/mode into a second root-owned worker pin config. `pid=0` is
   valid when UID/GID/signature match; a PID alone is not identity.
3. **Only then worker dispatch:** control calls
   `RegisteredSourceRepository.take_dispatch()` **once** and commits before
   worker startup. Its same process-local permit-owner instance must authorize
   exactly the two bounded pre-DNS/pre-dial bridge grant checks; a persisted
   `dispatched` row by itself is never a grant, and a control restart must not
   recreate the permit or re-arm. Launch the reviewed non-root, zero-capability
   worker from the staged pin config only after this arm; verify B and C
   signatures/nonce/TTL and exact scope. The real worker must use
   pinned TLS/peer, one exact URL/path, zero redirects, <=1 MiB compressed and
   decompressed, and one GET total including failures. Completion must bind
   signed B proof, body hash/bytes and dispatch to the current DB transaction.
   Loss of that permit, an unknown completion, timeout, or crash is terminal:
   reconcile read-only; never issue another grant or target GET. Never grant
   egress private TCP/PG, accept a key copied from a worker mount, or replace the
   actual one-shot receipt with a fabricated boolean.
4. **Independent admission gates:** register only
   `https://www.sqlite.org/lang_select.html` (no query or redirect) for
   `route.sql`/`queries`, with no Tavily or fabricated B receipt. Verify
   page-specific license/attribution, operator storage/use/retention grant,
   source review, trusted quality verifier, and expiry cleanup. `schema` and
   `assessment_evidence` stay gaps. Review the final host adapter, signer
   receipts, DB bootstrap/CAS, image and network proof with the user before
   *any* target request; blocked gates mean `not_executed`.

`control_runtime.py --serve` publishes the bridge but cannot dispatch without a
fresh root-only arm file binding the independently observed C key, B pins,
image and scope. `worker_once.py --once` accepts only the root-owned pinned
configuration and a non-root zero-capability identity, consumes two bridge
grants, checks the B proof again immediately before dial, and never retries.
The control stores the authenticated report/proof atomically; it does not grant
quality admission or activate a corpus.

The 2026-09-25 staged deployment passed actual two-container peer and IPv4/IPv6
DROP-counter preflight (with IPv6 routes and a link-local interface scope). It
initially stopped before dispatch because the signer could not stat the worker's
`/proc/<pid>/ns/net`. After explicit operator approval, temporary signer-only
SYS_PTRACE resolved that check; the worker retained zero capabilities. Fresh
keys/pins and preflight passed. The sole armed worker invocation then failed:
one dispatch, zero captures, zero active corpora. Target TCP traffic does not
establish HTTP completion. The attempt is terminal `unknown`, not retryable.
All three containers were stopped and the arm removed; the failure stage of
that historical invocation cannot be reconstructed from its generic CLI code.
A stored prior pin or a passing diagnostic namespace is never a live permit.

## Host-side offline input check

Before even rendering Compose, run `python aearn/infra/rag-c-live/check_inputs.py`
**as root inside the reviewed Linux environment** with the four base/final
image digest refs, three IDs, and B config path in its environment. This checks
only shape, Linux ownership and scope; it cannot prove that the digest was
reviewed, the image was built from the declared base, or the config grant is
current. Then inspect `docker compose -f aearn/infra/rag-c-live/compose.offline.yaml
config` and explicitly run the `offline-preflight` profile with
`--abort-on-container-exit --exit-code-from egress-proof` on a fresh Compose
project/volume. Never turn a passing static input check into live permission.









## Approved body ceiling (2026-09-25)

The formal registered-source full-body ceiling is now **8 MiB (8,388,608 bytes)**,
independently applied to wire/compressed and expanded bytes. A source policy may
set a lower limit. This is a ceiling, not a target size or permission to retry.
The base64 completion frame must separately allow encoding plus bounded metadata;
ordinary grant messages and signed proof limits do not grow with the body.
Existing policies and database CHECK constraints are not silently upgraded by
changing Python code: apply the dedicated migration and explicitly provision
approved policy configuration before live use. Keep the historical unknown attempt.
Historical supplemental dispatches remain spent after unknown outcomes. Review/admission
operate on a retained capture and never refetch; changing a byte ceiling grants no requests.

## Optional per-worker deadline and final-credit boundary (2026-09-28)

The root-owned worker JSON may additionally contain `deadline_seconds`. Omission
retains the 10-second default; an explicit finite numeric value must be greater
than zero and at most 300 seconds for the C registered full GET only. Booleans
and invalid values are rejected before identity/grant/DNS/transport work. The
underlying B `FetchLimits` remains capped at 30 seconds, zero redirects and the
8-MiB compressed/expanded ceilings remain in force, and B's signed pre-dial
grant still expires after four seconds. C's one-use completion nonce allows at
most 360 seconds from its grant; bridge connection/peer checks still use two
seconds, while only the complete-frame send and settlement-response wait use a
30-second socket timeout. A report must arrive within 60 seconds after it is
created, not within 60 seconds of the pre-dial signature.

No parameter change grants another GET. Schema 400 requires an independently
approved, exact final-followup allowance in the same disposable database: two
existing unknown attempts remain spent; at most one new generation-3 dispatch
can be issued for the same URL and original chain, with a hard total of three.
The consumed final authorization cannot be corrected or replayed. Rebuild and
re-pin the reviewed worker image and re-probe actual isolation before any live
operation. Code/offline tests alone are not operator approval or source acceptance.

## Mandatory B signature topology gate before any new source dispatch (2026-09-28)

The final spent gen3 worker shared the signer's network namespace but not its
PID namespace. B's signer requires a visible positive `SO_PEERCRED` PID and
`/proc/<pid>/ns/net` identity; a static socket/firewall check cannot establish
that the actual worker can obtain a signature. Do **not** replay that dispatch,
reuse its old pins, or infer that PID topology was the only historical failure.

1. Run the functional **offline-only** diagnostic from the repository root:
   `python aearn/infra/rag-c-live/signature_topology_preflight.py host`.
   It requires the locally available reviewed r2 image digest hard-pinned in the
   script (no build/pull). The test creates its own random-name container and
   volume, starts the real B signer with an ephemeral *test-only* key and real
   OUTPUT DROP in Docker `--network none`, then launches same-image workers with
   UID/GID 65534, supplementary 23456, cap-drop ALL, NoNewPrivs, and read-only
   mounts. It must report separate-PID rejection, shared-net+PID fresh nonce
   signature verified by the actual pinned client, and wrong-public-key
   rejection, followed by `OFFLINE_SIGNER_GATE_PASS`. The test never mounts a
   live key/socket/config or invokes DNS, C grants, a DB or target HTTP. Its
   signer needs **only** NET_ADMIN (install DROP), CHOWN (socket ownership) and
   the already-reviewed signer-only SYS_PTRACE (read peer `/proc`). No worker
   capability is added. This is a topology/protocol regression, not live proof.

2. For each new reviewed deployment, independently pin the new signer/public
   key, policy, namespace and immutable **same worker image** in a fresh
   root-owned worker config. Before any ARM, allowance or source dispatch,
   verify the **current actual signer** with the two commands below (PowerShell
   7, from repo root). Set variables to independently inspected current names,
   not historical gen3-r2 values. Do not mount C bridge, DSN, reviewer key,
   resolver config or any source credential into this preflight. It imports
   current `worker_once` identity/pin checks and calls only the actual B Unix
   signer; the signed nonce expires under the unmodified 4-second B TTL. The
   negative check must reject across separate PID namespaces, the positive
   check must succeed only when sharing **both** namespaces. Both commands
   must exit 0 with their exact respective marker, otherwise stop before any
   source allowance is spent. Inspect the actual Docker `NetworkMode`,
   `PidMode`, UID/GID, CapEff/CapBnd, NoNewPrivs and mounts again before
   launching the one-shot worker; the probe cannot transfer its authority.

```powershell
$signer = '<new-reviewed-running-signer-container-name>'
$image = 'sha256:<independently-reviewed-immutable-current-image-digest>'
$bVolume = '<new-signer-run-volume>' # same volume signer mounts at /run
$workerVolume = '<new-root-owned-worker-config-volume>' # mounted at /etc/rag-c
$bGid = '<current-B-trusted-GID>' # read from independently pinned worker config
$cGid = '<current-C-trusted-GID>' # may differ from B; exact supplementary_gids required
$groupArgs = @($bGid, $cGid) | Sort-Object -Unique | ForEach-Object { @('--group-add', $_) }
$probe = (Resolve-Path 'aearn/infra/rag-c-live/live_signer_preflight.py').Path
$common = @('--rm', '--network', "container:$signer", '--user', '65534:65534') +
  @($groupArgs) + @('--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
  '--read-only', '--env', 'RAG_C_SIGNER_PREFLIGHT_ONLY=yes',
  '--mount', "type=volume,src=$bVolume,dst=/run,readonly",
  '--mount', "type=volume,src=$workerVolume,dst=/etc/rag-c,readonly",
  '--mount', "type=bind,src=$probe,dst=/preflight.py,readonly")
docker run @common $image /preflight.py --expect-separate-pid-rejection
if ($LASTEXITCODE -ne 0) { throw 'B_SIGNER_NEGATIVE_GATE_FAILED' }
$shared = @('--pid', "container:$signer") + $common
docker run @shared $image /preflight.py
if ($LASTEXITCODE -ne 0) { throw 'B_SIGNER_POSITIVE_GATE_FAILED' }
```

The actual one-shot worker must likewise specify **both**
`--network container:<same signer>` and `--pid container:<same signer>` plus
its existing root-owned B/C mounts, UID/GID 65534, supplementary group, all
capabilities dropped, NoNewPrivs and read-only filesystem. Signer-only
NET_ADMIN/CHOWN/SYS_PTRACE remain on the signer, never the worker. Do not
relax the signer peer predicate, policy pin, nonce, or 4-second TTL. Any signer
restart/key rotation or image rebuild invalidates the observed proof and pins;
repeat the independent review and both gates. A passing preflight never
authorizes a C grant, extra source request, admission or D binding.
