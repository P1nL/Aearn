# Environment Doctor and Install Guidance Design

## Scope

This child owns the first productized environment doctor surface. It should be a read-only diagnostic layer with a stable API and desktop settings integration. It does not own runner implementation or automatic installation.

## Architecture

### Backend Service

Add `app/services/environment_doctor.py` as the source of truth for environment checks and static guidance.

The service owns:

- command/toolchain detection
- read-only version probes
- startup-script existence checks
- static guidance templates
- language capability to toolchain/runner matrix composition

It should reuse:

- `language_capabilities.py` for language states, execution modes, disclosures, and runner keys
- `runner_registry.py` for runner capability and support flags

It should not import route handlers, repositories, database code, or agent clients.

### Backend Route

Add `app/routes/environment.py` with:

```text
GET /api/environment/doctor
```

The route returns the service report directly. Expected version-check failures are represented in the payload, not as HTTP errors.

### Desktop UI

Extend the settings diagnostics page to fetch and render the doctor report:

- summary status
- toolchain/component cards
- language runner matrix
- static guidance cards
- manual refresh action

The desktop UI remains display-only. It must not execute install commands or mutate local settings.

## API Contract

The response shape is:

```json
{
  "generated_at": "2026-06-02T00:00:00Z",
  "platform": {
    "system": "Windows",
    "release": "10",
    "python_executable": "..."
  },
  "summary": {
    "overall_status": "ready|needs_attention|blocked",
    "ready_count": 0,
    "missing_required_count": 0,
    "planned_runner_count": 0
  },
  "components": [
    {
      "component_id": "python",
      "label": "Python",
      "kind": "runtime|package_manager|container|startup|compiled_toolchain|database_tooling",
      "status": "ready|missing|error|planned",
      "version": "Python 3.12.0",
      "executable_path": "...",
      "required_for": ["api", "python_runner"],
      "guidance_id": "python_uv_windows",
      "message": "..."
    }
  ],
  "language_runners": [
    {
      "language_id": "typescript",
      "display_name": "TypeScript",
      "runner_key": "node",
      "execution": "node_later",
      "capability_state": "planned",
      "supports_execution": false,
      "toolchain_status": "ready|missing|error|planned",
      "product_status": "executable|planned|static_review|unsupported",
      "guidance_id": "node_typescript_windows",
      "disclosure": "..."
    }
  ],
  "guidance": [
    {
      "guidance_id": "node_typescript_windows",
      "title": "Install Node.js and TypeScript tooling on Windows",
      "applies_to": ["node", "typescript"],
      "severity": "recommended",
      "summary": "...",
      "windows_steps": ["..."],
      "verification_commands": ["node --version"],
      "safety_notes": ["..."],
      "source": "static_template"
    }
  ]
}
```

## Status Semantics

- `ready`: detected or known-good fact is present.
- `missing`: required or recommended local tool was not found.
- `error`: command exists but probing failed or timed out.
- `planned`: Aearn product support is planned even if the machine has the toolchain.

Language `product_status` semantics:

- `executable`: the current product and runner contract support execution.
- `planned`: the language/toolchain is planned or detected but not executable in Aearn yet.
- `static_review`: the product may teach/review statically but cannot execute.
- `unsupported`: not supported in this product phase.

## Safety Boundary

The doctor may run only read-only probes such as:

- `--version` checks
- static file existence checks
- current API route response

The doctor must not run:

- `winget install`
- `npm install -g`
- `corepack enable`
- Docker start/stop commands
- PATH or system configuration mutations
- WSL installation/configuration commands

Install guidance templates may show commands as manual steps, but execution is left to the user.

## Compatibility

- Do not change existing `RuntimeProfile` or course language contracts.
- Do not mark planned languages as public/executable.
- Do not require Docker, Node, Java, Go, .NET, or SQL tools for the API route to succeed.
- The settings page should degrade to an error/loading state if the doctor API is unavailable.

## Rollback

- Remove the environment route from `app/main.py`.
- Remove the service and focused tests.
- Revert the settings diagnostics fetch/render additions.
- Existing health, learning, review, notes, and runner flows should continue to operate without the doctor route.
