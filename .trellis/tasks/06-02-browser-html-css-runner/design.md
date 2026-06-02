# Browser HTML CSS Runner Design

## Boundary

This child creates an explicit deterministic browser-preview runner. It is a teaching runner for generated exercises, not a general browser automation system.

Supported input shape:

- `runtime_profile.runtime_tier = "browser_preview"`
- `runtime_profile.language` is `javascript`, `html_css`, `html`, or `css`
- `code_blanks[*].acceptable_patterns_json`
- `metadata_json.required_patterns`
- optional `metadata_json.preview_html.success` and `metadata_json.preview_html.failure`
- `test_cases[*].case_type` including `visible`, `hidden`, and `preview_assertion`

## Service Design

Add `app/services/browser_preview_runner.py` with:

- `execute_browser_preview_with_tests(...)`
- typed browser test/result dataclasses
- deterministic code/blank inspection
- bounded stdout/stderr/error text
- language-aware preview rule selection

The runner has two rule families:

- JavaScript event-flow preview: requires `addEventListener`, `output.textContent`, and shared `count` state before the listener for current counter-style exercises.
- HTML/CSS static preview: uses blank gates and required patterns without forcing JavaScript event-binding rules.

## Registry And Runtime Flow

- Keep `browser_preview` as the canonical execution mode.
- Change `BROWSER_PREVIEW_RUNNER.supports_stdout` to `True` to match the API contract and console-output disclosure.
- Add `RunnerRegistry.run_browser_preview(...)`.
- In `runtime_runner.run_exercise(...)`, dispatch `runner_key == "browser"` to the browser-preview runner.
- Keep non-browser fallback logic available for existing static paths.

## Safety

- No live browser automation.
- No network access.
- No package installation.
- No filesystem writes.
- No execution of arbitrary assertion code.
- Hidden test ids/messages are sanitized before public output.

## Compatibility

- JavaScript, HTML, and CSS capabilities remain executable through `browser_preview`.
- Public course ids remain `javascript` and `html_css`.
- Python and Node/TypeScript adapters remain separate runner boundaries.
- SQL and managed compiled runners remain planned until their child tasks execute.
