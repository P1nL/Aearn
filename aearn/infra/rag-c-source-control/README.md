# RAG C source-control Unix bridge (default off, not deployed)

This is a **protocol artifact**, not a runnable production composition. It never
opens a PostgreSQL connection, HTTP listener, provider connection, or public
route. Importing these modules does nothing. `GrantServer.serve` refuses unless
an operator explicitly passes `approved=True` as root in a reviewed Linux
host/control container. No environment variable or example key enables it.
No application module/schema/worker is wired to it yet.

## Why two processes

The B egress namespace closes **all private TCP**, including PostgreSQL. Do not
add a DB firewall exception, share the host network, or move the fetch to an
unisolated host. A separate trusted control process may have a PostgreSQL
connection, but exposes only `grant` and `complete` on a root-owned Unix socket.
The egress worker gets a socket mount, never DB credentials, host networking,
Docker socket, or a general-purpose RPC/proxy/tunnel. The socket is **not** a
substitute for B's DNS/public-IP/TLS/peer and egress-attestor controls.

## Protocol and operator-owned wiring

1. Operator provisions a fresh root-owned directory (0750, dedicated trusted
   GID), `grant.sock` (0660, root:trusted-GID), `public.key` (0644, root:root)
   on a private mount shared only with the one egress worker. Every ancestor is
   root-owned and not group/world writable. Server creates a fresh Ed25519 key
   in memory. Mount key/socket read-only as appropriate in the worker, pin the
   public-key **SHA-256** and deployment ID from a separately reviewed root
   config (not worker-controlled env/path), and provide the expected worker
   UID/GID. Check Linux `SO_PEERCRED` on both sides; do not run in an
   unrestricted shared-UID namespace or reuse the mount after a crash.
2. Inject a host `resolver(Scope, now)` that reads the **current** policy,
   generation, root/lease, license/retention/storage/network rights and exact
   persisted one-shot dispatch. It must return `Decision(max_bytes, expires_at)`
   only for current authorization. The server signs only matching scope/nonce,
   bounded bytes and a <=4-second grant. The egress client verifies peer,
   file owner/modes, pinned key signature, nonce/scope/expiry. The grant must
   be checked immediately before the single dial; no redirect inherits it.
   `Scope` deliberately accepts only canonical HTTPS host/path with no query,
   fragment, encoded path or nondefault port; it is a narrower subset of the
   application `RegisteredSourceScope`. An adapter must convert/compare every
   field exactly and fail closed, never construct scope from a model URL.
3. **Completion is separate from the in-process `SafeFetcher` object token.**
   The worker can send at most one `complete` referencing that issued grant
   nonce within 60 seconds. It carries exact scope/dispatch UUID, final URL =
   registered URL, one-hop chain, allowed content type, SHA-256, <=1 MiB raw
   body as bounded base64, and a bounded signed B pre-dial attestor proof.
   The host `proof_verifier` independently validates the B pre-dial signer's
   key, deployment/policy digest, challenge freshness, exact host/public-IP and
   namespace. TLS/peer/body fields are a separately constrained **worker report**,
   authenticated by the reviewed immutable worker image and `SO_PEERCRED`, not
   cryptographically proven HTTP response bytes. `capture_store` receives the
   accepted peer socket as a seventh argument, then rechecks current
   policy/root/dispatch and atomically marks the dispatch settled and stores
   immutable capture metadata/body under the approved retention grant. The
   injected callback returns a capture UUID **only after commit**. Bridge
   `CaptureRecord` is signed back to the worker with exact scope/nonce/grant,
   digest/byte count, without echoing body. There is no implicit adapter to
   `RegisteredSourceRepository.settle_capture`: its in-memory `object` receipt
   cannot cross this process boundary. Do not forge it or relabel a prefix as
   full capture. The default-off host adapter still needs reviewed deployment
   composition, pinned keys and the same-process one-shot permit owner.
4. If proof verification, callback, policy, one-shot dispatch, license, or
   retention is unavailable, completion is **blocked**. A signed completion
   alone is not a publication/admission/claim-verification receipt. The
   pre-dial attestor proves constrained egress rules, **not** that worker-supplied
   bytes originated from HTTPS. The reviewed image, concrete pinned-TLS fetcher,
   no-redirect policy and process isolation remain independent obligations.
   If that end-to-end evidence cannot be established, report `not_executed` or
   `blocked` rather than claiming a real capture.

Both operations have exact JSON fields and canonical encoding; duplicate keys,
unknown operations, oversized frames, private/IP hosts, stale/replayed nonces,
wrong peer or signature fail closed. Server processes one bounded connection at
a time; callbacks need short DB timeouts and cannot hold transactions across
network I/O. A crash after host commit but before reply is an **unknown
completion**: query/reconcile the durable attempt offline, never retry the GET
or send a second completion. Body, URL, key, proof and raw errors must never be
logged. Only bounded fixed diagnostic codes are suitable for operator logs.

## Deployment limitation and proof still owed

Docker Desktop runs containers inside a Linux VM. Windows-host bind mounts and
UID/GID semantics may not provide the Linux root ownership, stable Unix socket,
`SO_PEERCRED`/user namespace mapping or mount isolation assumed here. A normal
Compose two-container network can also let the control process access private
TCP while accidentally making the egress container's Docker bridge/network
reach private TCP. **No Compose template or local Windows run is a proof.** The
operator must demonstrate a real two-container Linux/VM deployment with
independent namespaces, dedicated mount and UID/GID mapping, public-only
iptables/ip6tables, no private TCP in the egress namespace (including PG,
loopback, metadata, IPv6), exact DNS/public IP:443, B signed attestor, pinned
TLS/peer, and controlled cancellation. Never fall back to host networking or
add a private-TCP rule to make this bridge work. Production, provider, DB,
license and single-page live approval are separate gates; none is asserted here.

Offline checks (Python 3 + cryptography already installed):

    python -m unittest discover -s tests -v

Linux/WSL tests exercise AF_UNIX peer/frame behavior with fake callbacks. They
do not start Docker, reach PostgreSQL, resolve DNS, fetch SQLite, verify a live
B attestor, or prove the actual firewall/kernel namespace. Tests and this
artifact are not a production enablement.
