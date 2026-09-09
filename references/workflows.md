# Gemini delegation workflows

## Diagnose authentication before delegation

```bash
python scripts/run.py --auth-status --cwd .
python scripts/run.py --doctor --cwd .
```

For a third-party Agent, prefer API key or Vertex:

```bash
python scripts/run.py --auth api-key --mode review --cwd . --task "Review this project."
python scripts/run.py --auth vertex --mode review --cwd . --task "Review this project."
```

If old settings select `oauth-personal`, do not retry the personal Google login loop. `--auth auto` will prefer `GEMINI_API_KEY`/Vertex and can apply a temporary child-process override without changing persistent settings. Use `--auth google` only for an explicitly organization-managed Code Assist account.

## Inspect selectors and verify availability

```bash
python scripts/run.py --list-models --cwd .
python scripts/run.py --probe-model pro --cwd .
python scripts/run.py --probe-model <exact-model-id> --cwd .
```

Use `--probe-model` when the caller needs to know whether a specific model/version is actually usable with the current Gemini authentication.

## Let Gemini route automatically

```bash
python scripts/run.py --mode ask --profile balanced --cwd . --task "Draft the requested answer."
```

Equivalent intent: `--model auto`.

## Prefer speed

```bash
python scripts/run.py --mode review --profile fast --cwd . --task "Quickly review the document for major issues."
```

## Prefer quality tier

```bash
python scripts/run.py --mode review --profile deep --cwd . --task "Perform a rigorous external review."
```

This selects the `pro` tier while leaving model-native thinking/routing behavior intact.

## Concrete Gemini 3 reasoning control

```bash
python scripts/run.py --mode review --model gemini-3.1-pro-preview --thinking high --cwd . --task "Deeply review the argument."
```

## Concrete Gemini 2.5 reasoning control

```bash
python scripts/run.py --mode ask --model gemini-2.5-flash --thinking medium --cwd . --task "Analyze the material."
```

## PDF reviewer

```bash
python scripts/run.py --mode review --cwd . --input paper.pdf --profile deep --task "Review argument, evidence, methodology, and writing quality."
```

## Coding worker

```bash
python scripts/run.py --mode agent --cwd . --profile balanced --task "Fix the bug, run tests, and report the verified result."
```

## Continue the same Gemini reviewer/writer

```bash
python scripts/run.py --session auto --session-key <host-key> --mode review --cwd . --input paper.pdf --task "Review the paper."
python scripts/run.py --session auto --session-key <same-host-key> --mode review --cwd . --task "Continue: focus on the methodology weaknesses."
```

The wrapper resumes the exact mapped Gemini UUID for this workspace.

## Inspect cache/session diagnostics

```bash
python scripts/run.py --session auto --session-key <host-key> --cwd . \
  --task "Continue the draft." --meta-output .gemini-meta.json
python scripts/run.py --session-info --session-key <host-key> --cwd .
```

For API-key/Vertex authentication, inspect provider-reported cached-token stats. OAuth sessions may legitimately report no cached tokens.

## Force a fresh independent session

```bash
python scripts/run.py --session new --session-key <host-key> --mode review --cwd . --task "Give an independent review from scratch."
```
