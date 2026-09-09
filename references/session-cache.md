# Gemini session continuity and cache behavior

## Managed host-to-CLI affinity

Gemini CLI automatically saves native conversations and supports `--resume`. The wrapper maps one parent-Agent conversation to the correct native Gemini session:

```text
provider + resolved workspace + opaque host-session key -> Gemini session UUID
```

This complements Gemini's own project-scoped session storage and prevents an unrelated “latest” session from being selected accidentally.

Default wrapper state location:

- macOS/Linux: `$XDG_STATE_HOME/foreign-cli-skills/` or `~/.local/state/foreign-cli-skills/`
- Windows: `%LOCALAPPDATA%/foreign-cli-skills/state/`
- override: `FOREIGN_CLI_SKILL_STATE_DIR`

Only metadata is stored: session UUID, workspace, turn count, model/thinking/profile data, cache/token stats, timestamps, and a hash of the host key. Task text and model answers are not stored in the wrapper registry.

## Policies

```text
off       no managed mapping
auto      resume mapped UUID or create one
continue  require mapped UUID
new       force a fresh native session and replace mapping
```

Managed executions use `--output-format stream-json` because its documented `init` event includes `session_id` and the final `result` event includes aggregate stats. On resume the wrapper verifies that `init.session_id` equals the mapped UUID and fails closed if it differs.

A local lease prevents concurrent wrapper processes from mutating one managed session at the same time.

## Token caching

Gemini CLI documentation states that automatic token caching is available when using Gemini API-key authentication or Vertex AI, but cached content creation is not currently available through OAuth Google Personal/Enterprise Code Assist authentication.

The Headless structured result includes cached-token statistics when available. The wrapper exposes these through `--meta-output`:

```text
cache.cached_tokens
cache.input_tokens
cache.hit_ratio
```

Session reuse and stable prefixes are optimization signals, not proof of a hit. Only provider-reported cached token counts should be described as cache hits.

The wrapper keeps stable worker/permission instructions before the variable task, preserving a reusable prompt prefix across related turns.

## No response cache

The wrapper does not memoize final answers. This is intentional: mutable documents and code workspaces make result-level caching unsafe without a much stronger invalidation model.

## Rotation guidance

Continue the same session for a follow-up on the same document/review/project goal. Use `--session new` for an unrelated topic, an intentionally independent second opinion, or when accumulated context is no longer useful.

Changing from `auto`/`pro`/`flash` or between concrete model ids inside one resumed conversation can reduce cache affinity even though the conversational session continues.
