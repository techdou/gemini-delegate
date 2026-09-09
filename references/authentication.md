# Gemini CLI authentication for Agent delegation

Reviewed against current Gemini CLI documentation and repository behavior on 2026-09-06.

Official references:

- Authentication: https://geminicli.com/docs/get-started/authentication/
- Configuration: https://geminicli.com/docs/reference/configuration/
- FAQ / third-party agent guidance: https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/faq.md
- Non-interactive auth validation: https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/validateNonInterActiveAuth.ts
- Auth environment precedence: https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/core/contentGenerator.ts
- Individual-account transition announcement: https://github.com/google-gemini/gemini-cli/discussions/categories/announcements

## Current boundary

Gemini CLI stopped serving requests through the former Gemini Code Assist for individuals / consumer Google-account path. The CLI can still present a Google sign-in option, and organization-managed Code Assist/Workspace entitlements may use Google auth, but a personal account can fail with `UNSUPPORTED_CLIENT` and an Antigravity migration message.

For this Skill's use case — a parent/third-party Agent invoking Gemini Headless — use either:

1. Gemini API Key from Google AI Studio (`GEMINI_API_KEY`), or
2. Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=true` plus the documented Vertex credentials/configuration).

The official Gemini CLI FAQ explicitly recommends Vertex AI or a Google AI Studio API key for third-party coding agents.

## Wrapper auth policy

```text
--auth auto     -> prefer GEMINI_API_KEY; then Vertex; refuse legacy individual OAuth
--auth api-key  -> use gemini-api-key
--auth vertex   -> use vertex-ai
--auth google   -> explicit organization-managed Code Assist escape hatch only
```

`auto` never starts an interactive Google login flow.

## Why an API key can still lose to old OAuth settings

Current non-interactive Gemini CLI resolves configured `security.auth.selectedType` before environment-based detection. Environment detection itself checks roughly:

```text
GOOGLE_GENAI_USE_GCA=true
  -> Google/Code Assist
GOOGLE_GENAI_USE_VERTEXAI=true
  -> Vertex AI
GEMINI_API_KEY
  -> Gemini API key
```

Therefore a stale saved `oauth-personal` setting can keep winning even after `GEMINI_API_KEY` is exported. `GOOGLE_GENAI_USE_GCA=true` can also outrank the key.

The Skill detects both cases.

## Temporary per-run override

When API-key/Vertex auth is selected but a stale user/project setting points elsewhere, the wrapper can create a temporary `GEMINI_CLI_SYSTEM_SETTINGS_PATH` for the child process containing only the selected auth type. It does not change `~/.gemini/settings.json` or project settings.

Safety rule: if a real system-level Gemini settings file exists, the wrapper refuses to replace/bypass it. Administrator policy must be changed through the managed Gemini CLI configuration.

## API-key setup

Set the key outside prompts/artifacts:

```bash
# macOS/Linux
export GEMINI_API_KEY="..."

# PowerShell
$env:GEMINI_API_KEY="..."
```

Then verify without a model call:

```bash
python scripts/run.py --auth-status --cwd .
```

And with a tiny real model request if needed:

```bash
python scripts/run.py --auth api-key --probe-model flash --cwd .
```

Do not print or store the key in Skill metadata.

## Vertex AI setup

Vertex AI can use a Google Cloud API key or project/location plus ADC/service-account credentials. The wrapper checks for the documented project/location/API-key prerequisites but does not print credentials.

```bash
python scripts/run.py --auth vertex --auth-status --cwd .
```

## Failure handling

When CLI stderr/stdout contains the individual OAuth migration signature, the wrapper classifies it as an auth migration rather than a generic CLI failure and recommends API Key/Vertex. It does not retry the browser OAuth loop.

Use Antigravity separately if the user's goal is specifically Google's consumer-account CLI experience; this Gemini Skill remains a Gemini CLI Headless delegation capability.
