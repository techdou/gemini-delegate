# Proxy configuration and eligibility evidence

Use the installed native CLI only through this Skill's wrappers. The guard protects
both agy and the Gemini fallback. It never changes system environment variables,
PATH, shell profiles, Google credentials, browser settings or proxy group choices.

## Windows manual entry points

PowerShell:

```powershell
$skillDir = 'C:\Users\DouXiulu\.agents\skills\gemini-delegate'
python "$skillDir\scripts\agy.py" --doctor
python "$skillDir\scripts\agy.py" --interactive --cwd .
python "$skillDir\scripts\agy.py" --cwd . --task-file .\task.md --plan-mode
```

CMD interactive chat:

```cmd
"C:\Users\DouXiulu\.agents\skills\gemini-delegate\scripts\agy-safe.cmd"
```

`--proxy http://127.0.0.1:PORT` works for either Python wrapper. Configuration priority:
explicit option, `GEMINI_DELEGATE_PROXY`, upper/lowercase HTTPS then HTTP then ALL
proxy environment variables, finally `http://127.0.0.1:7890`. An explicit empty or
unsupported proxy fails validation. Both child NO_PROXY variants are cleared.
HTTP proxies may include Basic authentication; the guard never prints credentials.
Use a local HTTP mixed port rather than a subscription URL or SOCKS endpoint.

The original `agy.exe` is still the installed binary. Typing bare `agy` bypasses
the Skill's guard; the safe launcher does not silently replace it.

## Credentials and optional environment configuration

If keeping a private configuration file, its canonical location is
`~/.agents/skills/gemini-delegate/.env`. It is ignored by Git. Do not copy credentials
into tasks, logs, backups or commits. These wrappers **do not automatically load
that .env**: export the required values into the parent process through your private
shell setup, or use `--proxy` for the non-secret local endpoint.

- Optional proxy variable: `GEMINI_DELEGATE_PROXY`, or `HTTPS_PROXY`/`HTTP_PROXY`.
  No proxy variable is required for the default local `127.0.0.1:7890` endpoint.
- agy uses the native CLI's existing login/keyring; no API key is passed to agy.
- Gemini API-key mode requires `GEMINI_API_KEY`. Vertex configuration uses
  `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT` (or `GOOGLE_CLOUD_PROJECT_ID`),
  `GOOGLE_CLOUD_LOCATION`, and optionally `GOOGLE_APPLICATION_CREDENTIALS` or
  `GOOGLE_API_KEY` as appropriate to the chosen auth path. See
  [authentication.md](authentication.md) rather than guessing credentials.

## What the guard proves

1. The selected proxy port is reachable.
2. An explicit CONNECT tunnel, verified TLS and valid Cloudflare egress trace work.
   The implementation does not rely on urllib's proxy autodetection/NO_PROXY bypass.
3. Provider subprocesses receive one consistent proxy endpoint and no NO_PROXY rule.
4. Dead proxy or invalid preflight prevents provider launch. No direct fallback exists.
5. Remote Skill manifest/archive fetches also use CONNECT through this endpoint;
   every redirect must remain HTTPS and response size limits remain enforced.

It does **not** prove that an arbitrary CLI version or external tool always honors
the proxy environment, that the proxy never selects DIRECT, that all Google domains
use Cloudflare's exit, or that the account is eligible. For routing evidence inspect
the proxy connection log or a local CONNECT-only forwarding audit; record target
hostnames only, never decrypted requests or Authorization headers. OS-wide network
enforcement is a separate configuration and is not installed by this Skill.

## Service eligibility triage

Read the current [official FAQ](https://antigravity.google/docs/faq). It documents
availability, associated Google account country, age verification and account type.
Successful Google OAuth authentication is separate from Antigravity eligibility.

Do not infer “definitely banned”, “definitely not banned”, “all cloud IPs blocked”,
or “a past direct call caused the restriction” from a location rejection alone.
Old logs without network observations cannot prove which path was used.

Run the doctor first; correct a concrete configuration problem before making at
most one tiny tool-free service probe. On eligibility rejection stop and retain
local evidence. Do not automatically cycle nodes/accounts, repeatedly reauthenticate,
modify the service's eligibility response, or disable certificate verification.
If official account association is wrong, use the official correction/support path.

## Failure exits

agy print/model commands preserve a nonzero native exit. A native zero with
eligibility rejection becomes 4; an empty result/AGY_ERROR becomes 1; a partial or
hard timeout becomes 124. Wrapper misuse or proxy failure returns 2. Native process
launch failure returns 126/127. Interactive mode inherits the terminal and returns
the native exit (read any native eligibility error on screen).

`--allow-no-proxy` and `--skip-egress-check` are deliberately unsupported. The
doctor's preflight still requires a proxy; local `--help` and normal Gemini
metadata/dry-run queries do not invoke a provider model.
