# Research: all-current-runtime-matrix

- Query: Translate the user-approved `All-current-runtimes` scope into a precise container image and runner protocol matrix without silently promoting unsupported runtimes.
- Scope: internal
- Date: 2026-07-27

## Scope Decision

**Confirmed on July 27, 2026:** Child 03 must define and test a container image
entry for every runtime tier that is currently executable in the formal Aearn
product. The future Harness remains feature-disabled until the complete image
lock, executor health, and policy gates pass.

This does **not** add Rust/C++ execution. Those languages remain
`compiled_sandbox_later` / not publicly executable in the current capability
registry and have no Child 03 image entry.

## Current-Executable Matrix

| Target runtime id | Current tier / languages | Container runner responsibility | Explicit exclusions |
| --- | --- | --- | --- |
| `python-stdout-v1` | `python_stdout_test` / Python | Run the existing bounded function-test protocol in an isolated Python image. | No pip, venv, package install, filesystem/API/network access. |
| `browser-preview-v1` | `browser_preview` / JavaScript and HTML/CSS | Execute only the reviewed browser-preview exercise protocol in a prebuilt headless-browser image; no arbitrary URL/navigation/download. | No external navigation, downloads, extension, user-selected browser flags. |
| `node-typescript-v1` | `node_typescript_test` / TypeScript | Compile/run one TypeScript submission plus generated function harness in an image with preinstalled pinned compiler/runtime. | No npm/yarn/pnpm install, package registry, project workspace, arbitrary Node command. |
| `sqlite-query-v1` | `sql_query_test` / SQL | Run the existing read-only SQLite teaching dialect in an ephemeral image-local database. | Never connect to Aearn PostgreSQL, attach extensions/files, or run DDL/DML. |
| `java-managed-v1` | `managed_compiled_test` / Java | Compile/run one single-file Java teaching harness using a prebuilt JDK image. | No Maven/Gradle/external dependencies/arbitrary project. |
| `go-managed-v1` | `managed_compiled_test` / Go | Run one package/harness with prebuilt Go toolchain and module download disabled. | No `go get`, module download, external dependencies/arbitrary project. |
| `dotnet-managed-v1` | `managed_compiled_test` / C# | Compile/run one single-file .NET teaching harness with pinned SDK/runtime. | No NuGet restore/network, solution/workload, arbitrary project. |

The evidence comes from `app/db/seeds.py:1-173`,
`app/services/runners/language_capabilities.py:65-279`, and the current runner
modules. Browser preview is included because it has an executable public tier,
but it is constrained to the existing course exercise protocol rather than
being generalized into an unbounded browser.

## Image and Protocol Consequences

1. The developer-owned image registry needs one immutable `repository@sha256:`
   entry per row plus exact runner protocol version, non-root user, fixed
   internal entrypoint, hard limits, and an enablement state. A tag or local
   image ID is not a production allowlist entry.
2. Runtime images must be prebuilt. Learner jobs never install dependencies or
   select an OS/toolchain command at runtime. Image publication/digest locking
   is a deployment prerequisite; capability exposure remains denied if any
   configured entry is absent, unpinned, unhealthy, or mismatched.
3. All runner input uses a versioned structured stdin protocol and a generated
   in-image harness. The executor does not bind-mount code, tests, paths, or
   host directories. Compiled runtime workspaces are writable tmpfs only.
4. Each image must emit a bounded structured result that maps into the existing
   `RuntimeExecutionResult` authority. Internal audit stores safe counters and
   references; public results never include container identifiers/digests,
   commands, paths, raw code, hidden test values, or Docker errors.
5. Every image has static launch-spec tests and opt-in Docker conformance tests.
   The conformance suite refuses a mutable tag and fails closed if Docker or the
   pinned image cannot be verified; it never falls back to current host runners.

## Architecture Decision Derived from Child 02

Use `tutor_execution_jobs` as the durable executor queue, inserted by the
registered `runner.execute` effect handler in the Child 02 transaction. The
executor service leases rows after commit and records attempts/audit/results.
A broker message may serve only as a wakeup optimization; it cannot be the
source of truth because a failed publish must not lose or duplicate the job.

The executor process is the only service configured with Docker Engine access.
It runs an allowlisted `ContainerRuntimeClient` and accepts no model/learner
image/command/network/mount values. API/legacy runner modules receive only a
normalized execution-result reader/adapter and static import tests forbid
Docker control in those packages.

## Deferred but Blocking Before Feature Enablement

- Each image must be built/published and its exact digest committed to the
  developer-owned registry. Child 03 may define the registry schema, Dockerfiles,
  build verification, and test fixtures; it must not enable a runtime with an
  unresolved tag or placeholder digest.
- Child 06 still owns public intent extraction, API/SSE delivery, and Desktop
  presentation. Child 03 defines the trusted `ExecutionIntentProof` contract
  but does not add route/UI behavior.
- Child 07 owns removing/retiring legacy subprocess execution after the
  clean-slate cutover verification; Child 03 only forbids it as a Harness
  fallback.