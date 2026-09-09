---
name: gemini
description: Delegate bounded work to the locally installed Google Gemini CLI, including model selection/probing, thinking control, session continuity, cache-aware repeated PDF/multimodal review/writing, workspace-scoped coding, auth-aware Headless execution, and explicit Skill health/update/rollback maintenance. Use only when the user or parent agent explicitly asks for Gemini/Gemini CLI/Antigravity CLI (agy), asks about Gemini models/thinking, or asks to continue/resume a prior Gemini delegation. Do not activate for generic writing, review, analysis, or coding that does not request Gemini.
---

# Gemini delegation — primary channel: Antigravity CLI (`agy`)

Delegate Gemini work to the locally installed Antigravity CLI (`agy`) by default. The
gemini-cli wrapper below (`scripts/run.py`) remains available as the fallback channel for
when its quota is healthy and you need session affinity, cache stats, or auth management.
The parent agent owns routing, authorization, verification, and the final user-facing answer.


## Primary: invoke agy directly

```bash
cd <workspace> && agy --dangerously-skip-permissions --print-timeout 15m --print="<bounded task text>"
```

Verified invocation notes (measured 2026-09-07):

- Attach the prompt with `--print="..."` (or place it last). A bare `--print "<next-flag>"`
  swallows the next flag as the prompt and silently drops the real task.
- Default `--print-timeout` is 5m — too short for multi-file reviews; raise it explicitly.
- Headless mode cannot show permission prompts: tool calls that need approval are
  auto-denied ("no output produced"). For read-only tasks,
  `--dangerously-skip-permissions` is acceptable when the task text itself forbids edits;
  otherwise configure `permissions.allow` rules in the CLI settings.
- Useful flags: `--model`, `--effort low|medium|high`, `--continue`/`-c` to resume the
  most recent conversation, `--mode plan|accept-edits`.
- Query `agy models` for the live model list (it spans Gemini Flash/Pro tiers plus Claude
  Sonnet/Opus and GPT-OSS variants) — never hard-code the catalog.
- The IDE command `antigravity chat` is a GUI panel (no stdout round-trip) — never use it
  for programmatic delegation.
- Treat a non-zero exit or an empty result as failure; do not fabricate an answer. Retry
  once only for a concrete safe fix (e.g. re-attaching the prompt correctly).

## Why agy first: gemini-cli quota reality (measured 2026-09-07)

The gemini-cli fallback has two failure modes the wrapper surfaces as non-zero exits; both
were reproduced locally:

1. **Untrusted directory (exit 55)**: non-interactive runs refuse untrusted workspaces.
   Fix without touching persistent settings: set `GEMINI_CLI_TRUST_WORKSPACE=true` for the
   child process only (prefix the `run.py` invocation). See
   https://geminicli.com/docs/cli/trusted-folders/#headless-and-automated-environments
2. **Quota exhaustion (exit 429, `TerminalQuotaError`)**: free-tier daily quotas apply per
   model (observed: `gemini-3.5-flash` requests/day exhausted; switching to `--model pro`
   reported `limit: 0`, i.e. that key has no free-tier Pro access at all — switching models
   is NOT a reliable workaround). agy runs on the Antigravity account quota and is immune
   to this. When the wrapper reports 429, do not retry the same day — use agy or report
   honestly.


## Fallback: gemini-cli wrapper (`scripts/run.py`)

Use the wrapper when gemini-cli quota is healthy and you need managed session continuity,
provider cache stats, or auth control. Everything below documents that wrapper.

## Use Agent-safe authentication

This Skill is a third-party Headless delegation wrapper. Do not rely on individual Google/Code Assist OAuth: that path no longer serves individual Gemini CLI accounts. Prefer:

- `--auth auto` (default): Gemini API Key when `GEMINI_API_KEY` is present, otherwise configured Vertex AI; refuses legacy individual OAuth.
- `--auth api-key`: require/use Google AI Studio Gemini API Key.
- `--auth vertex`: require/use Vertex AI.
- `--auth google`: explicit escape hatch only for organization-managed Code Assist/Workspace entitlement; never assume it works for a personal account.

Diagnose without a model call:

```bash
python3 <skill-dir>/scripts/run.py --auth-status --cwd <workspace>
python3 <skill-dir>/scripts/run.py --doctor --cwd <workspace>
```

If saved user/project settings still select `oauth-personal` while `GEMINI_API_KEY` is available, the wrapper may use a temporary highest-precedence auth override for the child process only; it does not rewrite persistent settings. It refuses to bypass an existing system-level Gemini settings policy.

Read [references/authentication.md](references/authentication.md) before changing authentication behavior.

## Preserve continuity when the task continues

For related Gemini turns in the same parent-agent conversation, use managed session affinity:

```bash
python3 <skill-dir>/scripts/run.py \
  --session auto \
  --session-key <stable-opaque-host-session-key> \
  --mode <ask|review|edit|agent> \
  --cwd <workspace> \
  --task "<bounded task>"
```

Generate/reuse one opaque `--session-key`, or rely on `GEMINI_SKILL_SESSION_KEY` / `FOREIGN_MODEL_SESSION_KEY` when available. Gemini native sessions are project-specific; the wrapper additionally scopes affinity by provider + resolved workspace + host session key.

Session policy:

- `auto`: resume the mapped Gemini UUID when present; otherwise create and record one.
- `continue`: require an existing mapping; do not silently start a fresh conversation.
- `new`: intentionally create a fresh native session and replace the mapping.
- `off`: one-shot behavior for unrelated work.

Do not use `latest` as automatic affinity. Managed runs use `stream-json` so the wrapper can capture the documented `init.session_id`, and resumed runs verify it matches the mapped UUID.

Use `--session-info`, `--list-sessions`, and `--forget-session` for local mapping management. The registry never stores task text or model answers.

## Keep provider cache-friendly

The wrapper puts invariant worker/permission instructions before changing task text and resumes the native Gemini session for related turns. Add:

```bash
--meta-output .gemini-run-meta.json
```

for `stats`, `cache.cached_tokens`, `cache.hit_ratio`, and `cache_affinity` without polluting stdout.

Gemini CLI token caching is provider/auth dependent: official CLI documentation says automatic token caching is available for Gemini API-key and Vertex AI authentication, but not OAuth Code Assist accounts. Never infer a hit from session reuse alone; use provider-reported cached-token stats. The wrapper does not memoize final answers.

## Maintain the Skill explicitly, never during ordinary delegation

Normal `ask/review/edit/agent` runs must not check the network for Skill updates. For health, compatibility, or upgrade requests use the maintenance interface instead:

```bash
python3 <skill-dir>/scripts/run.py --doctor
python3 <skill-dir>/scripts/run.py --update-info
python3 <skill-dir>/scripts/run.py --check-update [--manifest <source>]
```

Only run `--self-update` or `--rollback` when the user/parent explicitly authorizes changing the installed Skill. Both require the second opt-in `--allow-self-update`. The updater requires a trusted manifest, HTTPS for remote sources, SHA-256 verification, safe ZIP extraction, candidate validation, a pre-replacement runtime smoke check, and a local backup. It never upgrades the provider CLI itself.

Read [references/maintenance.md](references/maintenance.md) before publishing an update manifest or changing installed Skill files.

## Handle model questions first

Do not invent an account-wide model list. Headless CLI has no authoritative equivalent of Codex model catalog discovery.

```bash
python3 <skill-dir>/scripts/run.py --list-models --cwd <workspace>
python3 <skill-dir>/scripts/run.py --current-model --cwd <workspace>
python3 <skill-dir>/scripts/run.py --probe-model <model-or-selector> --cwd <workspace>
```

`--list-models` reports official stable selectors (`auto`, `pro`, `flash`, `flash-lite`) plus locally configured aliases/definitions. `--probe-model` makes a tiny Headless call to verify actual usability.

Use `--model <name>` for selector/alias/concrete id. Prefer `auto` when no tier/version is required. Profiles: `fast→flash`, `balanced→auto`, `deep→pro`.

Use `--thinking auto|none|minimal|low|medium|high` only when explicitly requested. Non-`auto` thinking requires a concrete Gemini 2.5 or 3.x model id; do not combine exact thinking with `auto/pro/flash` selectors whose underlying generation may change.

## Select the least-privileged work mode

- `ask`: answer/write/analyze without changing files.
- `review`: inspect files, PDFs, media, or projects without changes.
- `edit`: create/modify authorized workspace files; no arbitrary command loop required.
- `agent`: modify files and run commands/tests/builds in sandboxed mode.

Use repeatable `--input <path>` and `--task-file <file>`. In `edit`/`agent`, an input outside `--cwd` requires explicit `--extra-dir` authorization or must be copied into the workspace.

## Delegation and verification rules

- Give Gemini the actual bounded task, not routing meta-language.
- Reuse a managed session only for the same goal; rotate with `new` when the subject changes materially.
- Keep secrets out of prompts, raw logs, and artifacts.
- Treat non-zero wrapper exit codes as failure; never fabricate a result.
- Verify requested files/diffs after `edit`/`agent` before claiming success.
- Do not recursively invoke the Gemini skill from the delegated Gemini worker.
- Do not weaken approval/sandbox policy because an action was blocked.

Read [references/authentication.md](references/authentication.md) for authentication/migration behavior, [references/maintenance.md](references/maintenance.md) for self-maintenance, [references/session-cache.md](references/session-cache.md) for continuity/cache behavior, [references/model-control.md](references/model-control.md) for model/thinking behavior, [references/security.md](references/security.md) before changing permissions, [references/official-cli.md](references/official-cli.md) for compatibility, and [references/workflows.md](references/workflows.md) for examples.
