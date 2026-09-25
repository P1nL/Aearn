# RAG B isolated egress / signed attestor (default off)

This directory is deployment source, not a production approval or an application
feature flag. Nothing runs on import or image build. Do not use the ignored lab
logs, credentials, copied provider responses, or one-off lab IPs as deployment
configuration. The single authorized live Tavily Search and public-document fetch
have already happened; do not repeat either while validating this artifact.

## Operator-owned inputs and startup

1. Provision a dedicated container network namespace with no untrusted process
   or sidecar. Review and pin an immutable Linux base image with Python 3,
   cryptography, one reviewed iptables/ip6tables backend, and util-linux
   setpriv. Build this Dockerfile from repository root with
   --build-arg AEARN_EGRESS_BASE=...@sha256:<digest>. It installs no packages
   and deliberately does not bundle the API/worker application.
2. Create a root-owned, non-group/world-writable JSON file outside Git from
   config.example.json. Replace every placeholder: an operator-reviewed
   deployment ID, the exact IPv4 address of the approved DNS resolver, and an
   explicit host -> resolved public IPv4 mapping for the approved purpose.
   No IP, resolver, API host, or repository absolute path is assumed. Do not put
   tokens, request queries, content, credentials, or private URLs in this file.
   The resolver is the sole private-address network exception, only TCP/UDP 53.
   It must be trusted and access-controlled; it remains a potential DNS-channel
   exfiltration surface. IPv6 output has no exception.
3. Mount the config read-only in the container, a root-owned /run tmpfs
   (mode 0755), rootfs read-only, no-new-privileges, drop all capabilities
   except NET_ADMIN for the bootstrap/signer, and provide no host networking,
   ambient proxy, Docker socket, secrets to the signer, or untrusted co-tenants.
   Set RAG_EGRESS_CONFIG to the absolute container path and set
   RAG_EGRESS_OPERATOR_APPROVED=yes only after separate approval. Pass a
   reviewed worker command after the image name. Without these inputs startup
   fails; there is no implicit provider call or fallback. The application must
   be installed separately in the reviewed image and keep all four RAG feature
   gates closed until independently authorized.
4. Startup closes IPv4 and IPv6 OUTPUT before flushing rules, then allows
   only the configured DNS IP on TCP/UDP 53 and configured public IPv4 IPs on
   TCP 443. The root signer checks the exact installed rules, snapshots their
   digest, and creates an ephemeral Ed25519 key. It creates a root-owned
   0750 directory, root-owned 0660 Unix socket with the dedicated trusted GID,
   and root-owned public-key/policy files. The launcher uses setpriv to run the
   worker as the configured non-root UID/GID, sole supplementary trusted GID,
   with all capability bounding bits dropped and no-new-privileges. The worker
   preflight checks CapEff/CapBnd/NoNewPrivs, ownership, and socket modes.
   Run this launcher as container PID 1 so its failure destroys the namespace.
5. Wire the application LiveEgressAttestor explicitly to that socket,
   root-owned public key and policy SHA-256, deployment ID, and trusted GID.
   The launcher provides the non-authoritative RAG_EGRESS_* path/identity
   pointers to the worker; the application must independently read/pin them
   through its explicit composition, not treat environment variables as proof.
   The application still controls source authorization, per-hop DNS/pinned TLS,
   redirect, byte/retention limits, and its default-off gates. The attestor
   accepts a bounded exact JSON challenge and signs only when deployment,
   exact host/IP, namespace inode, fresh 48-hex nonce, pinned policy digest,
   current IPv4/IPv6 rules, and kernel SO_PEERCRED worker UID/GID and actual
   peer network namespace match. Each receipt expires in four seconds;
   the client verifies the signature and request echo. Neither signer nor
   launcher logs host/query/body/key/request bytes; diagnostic codes only.

The signer itself requires root/NET_ADMIN to maintain and inspect rules. A root
attacker, a process with NET_ADMIN in the same namespace, a malicious container
runtime, or a resolver allowed on port 53 is outside this artifact's trust
boundary. An operator must pin/review the image and verify the chosen iptables
backend matches the actual kernel datapath, with no alternate nft/legacy chain,
route, host firewall override, or unexpected namespace peer. Destroy the
container after any startup failure or policy drift; do not reuse its namespace.
A new instance generates a new key/digest; pins are only trusted when supplied
from this root-owned, reviewed deployment, never from worker-controlled files.

## Offline verification only

From this directory, with Python 3 and cryptography already installed:

    python -m unittest discover -s tests -v

Tests mock firewall commands and namespace state; they do not start Docker,
perform DNS/TLS, call Tavily, read dotenv, contact a database, or prove a live
firewall. Before any production enablement, an independent operator must
verify rules and socket ownership in the deployed namespace, prove IPv4/IPv6
loopback, RFC1918/ULA/link-local and metadata are unreachable including
redirect attempts, confirm pinned TLS/actual peer, approved DNS behavior and
storage license, and record production-specific review. The one-off lab proof
is not portable production evidence. Until then, live fetching remains off.
