# Container Executor Image Sources

`runtime-catalog.json` names exactly the seven approved runtime protocol
entries. `image-locks.json` is intentionally empty until reviewed immutable
`repository@sha256:<64-hex>` images are published. A missing lock is an
unavailable runtime, never a tag or host-process fallback.

Each `runtimes/<runtime-id>/Dockerfile` is a build definition only. It requires
an explicitly supplied prebuilt toolchain base via `AEARN_RUNTIME_BASE_IMAGE`,
installs no packages, and exposes the fixed in-image bridge. A reviewed image
must include the matching `/opt/aearn/runtime-adapter`; otherwise the bridge
returns a safe unavailable result.
