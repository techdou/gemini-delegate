# Gemini CLI compatibility notes

Verified against current `google-gemini/gemini-cli` documentation on 2026-09-06. Use this file when diagnosing CLI behavior or updating wrapper flags.

Official references:

- CLI reference: https://geminicli.com/docs/cli/cli-reference/
- Model selection: https://geminicli.com/docs/cli/model/
- Configuration: https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md
- Gemini thinking: https://ai.google.dev/gemini-api/docs/thinking

## Headless contract

The wrapper uses:

```text
-p <task>
--output-format stream-json
```

Streaming JSON is used because the documented `init` event exposes `session_id`, message/tool events allow final-output reconstruction, and the `result` event contains aggregate usage statistics. `--raw-output` therefore preserves JSONL rather than one JSON object.


## Authentication for third-party Headless use

The Skill treats Gemini API Key and Vertex AI as the normal Agent/Headless authentication paths. Gemini CLI individual Google/Code Assist accounts were migrated away from the former OAuth path and can return `UNSUPPORTED_CLIENT` with an Antigravity migration message. Organization-managed Code Assist may differ.

Current non-interactive auth precedence matters: a configured `security.auth.selectedType` is evaluated before environment detection, while environment auth detection checks Google Code Assist before Vertex before `GEMINI_API_KEY`. The wrapper therefore performs an auth preflight and can temporarily override stale user/project `oauth-personal` state for its child process, but it refuses to bypass a system-level settings policy. See `authentication.md`.

## Model selection

`--model <name>` / `-m <name>` chooses the model or selector for the session. The official model picker recommends `auto` for general use and exposes tier selectors such as `pro`, `flash`, and `flash-lite`.

The `/model` picker is interactive. Current Headless CLI documentation does not expose an authoritative account-level `--list-models`; therefore the skill separates local/known selectors from an actual `--probe-model` call.

Model settings support `modelConfigs` aliases and custom aliases. This is how the wrapper implements per-run thinking for concrete model ids without editing the user's project settings.

## Thinking

Gemini 2.5 uses `thinkingBudget`; Gemini 3.x uses `thinkingLevel`. Exact supported levels vary by model. The wrapper keeps `auto` as the default and only injects explicit thinking configuration when a concrete generation can be identified.

For Gemini 2.5 the wrapper uses Google's documented reasoning-effort compatibility mapping: none→0, minimal/low→1024, medium→8192, high→24576. For Gemini 3.x it uses MINIMAL/LOW/MEDIUM/HIGH and rejects full thinking-off.

## Approval mapping

```text
ask/review -> --approval-mode default
edit       -> --approval-mode auto_edit
agent      -> --approval-mode yolo + --sandbox
```

In Headless mode, actions requiring interactive confirmation cannot be approved interactively. `auto_edit` is reserved for controlled file edits; `agent` is for tasks requiring commands/tests/builds and is sandboxed.

On Windows, `agent` sets `GEMINI_SANDBOX=windows-native` only when the user has not already selected a sandbox backend.

## Session and token-cache behavior

Gemini CLI automatically saves conversations and supports `--resume latest`, index, or UUID. Native session history is project-specific. The wrapper adds a host-session/workspace mapping and uses exact UUID resume for affinity.

Gemini CLI's token-caching documentation states that automatic caching is available for Gemini API-key and Vertex AI authentication, while OAuth Personal/Enterprise Code Assist authentication does not currently support cached content creation. Headless result stats can expose cached token counts; the wrapper records them but does not implement its own response cache.

## Additional directories

`--include-directories` adds extra workspace roots and currently supports up to five. In write-capable modes these may broaden mutation scope, so external inputs outside `--cwd` require explicit `--extra-dir` authorization.

Keep credentials out of prompts and raw logs. Wrapper `--doctor` reports only non-secret authentication state hints.

## v1.5 compatibility/auth note (2026-09-06)

Gemini CLI exposes `gemini --version`; official documentation also supports `gemini update`, while npm installations can use `npm install -g @google/gemini-cli@latest`. Stable/preview/nightly are separate release channels.

The Skill intentionally does not run those CLI/package update commands. `skill.json` records the stable CLI documentation baseline reviewed for this Skill, and `--doctor` checks local version/capability signals. Skill self-update and Gemini CLI package update remain separate operations.
