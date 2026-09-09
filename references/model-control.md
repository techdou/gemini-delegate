# Gemini model selectors, probing, and thinking control

## Discovery is intentionally two-tier

Gemini CLI Headless mode currently has no authoritative account-level `--list-models` command. The interactive `/model` picker exposes model choices, but it is not a stable headless automation interface.

Therefore:

```bash
python scripts/run.py --list-models --cwd <workspace>
```

returns:

1. official stable selectors: `auto`, `pro`, `flash`, `flash-lite`;
2. custom aliases/model definitions found in local user/project settings;
3. the best-effort explicitly configured model.

To verify actual availability in the current auth context:

```bash
python scripts/run.py --probe-model <model-or-selector> --cwd <workspace>
```

This deliberately makes one minimal read-only model call, so it can consume a very small amount of quota.

## Model/profile selection

```bash
--model <selector-or-model-id>
```

Intent profiles are deliberately simple and based on Google's public selector semantics:

```text
fast     -> flash
balanced -> auto
deep     -> pro
```

An explicit `--model` overrides the profile's model selector.

## Thinking control

```bash
--thinking auto|none|minimal|low|medium|high
```

`auto` preserves Gemini CLI/model defaults and is required for routing selectors such as `auto`, `pro`, `flash`, and `flash-lite`.

For a concrete Gemini 2.5 model, the wrapper maps the abstract levels to Google's documented reasoning-effort compatibility budgets:

```text
none    -> 0
minimal -> 1024
low     -> 1024
medium  -> 8192
high    -> 24576
```

For a concrete Gemini 3.x model, it uses `thinkingLevel` with `MINIMAL`, `LOW`, `MEDIUM`, or `HIGH`. Full `none` is rejected for Gemini 3.x because thinking cannot be reliably disabled there.

Gemini's supported thinking levels differ by exact model. If a selected model rejects a level, switch to one advertised by that model or return to `auto`; do not silently substitute a stronger level.

## How the wrapper injects per-run thinking

Gemini CLI exposes model config aliases through settings rather than a dedicated headless `--thinking` flag. The wrapper creates a temporary unique custom alias in a temporary **system-defaults** file, preserving and merging any existing system-defaults content, then selects that alias with the normal `--model` CLI flag. Higher-precedence user/project/system settings and CLI policy still remain in effect. The temporary file is not written into the user's project.
