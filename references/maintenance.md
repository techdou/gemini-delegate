# Self-maintenance and compatibility

Normal Gemini delegation never checks the network for Skill updates. Maintenance is explicit and separate from task execution.

## Local health and compatibility

```bash
python3 scripts/run.py --doctor
python3 scripts/run.py --update-info
```

`--doctor` checks the installed CLI path/version/auth hints and reports the Skill's locally verified compatibility boundary. A CLI newer than `tested_through_cli` is a warning, not an automatic failure. Capability behavior matters more than version numbers.

Gemini CLI exposes `gemini --version`; its official distribution also supports `gemini update`, while npm installations can be updated with `npm install -g @google/gemini-cli@latest`. This Skill deliberately does not run either command automatically because CLI installation ownership is separate from Skill ownership.

## Configure an update source

The Skill intentionally has no hard-coded third-party update server. Configure a release-manifest source after publishing your own trusted artifacts:

```bash
export GEMINI_SKILL_MANIFEST_URL=https://example.com/gemini-release-manifest.json
# or shared for both providers
export FOREIGN_CLI_SKILL_MANIFEST_URL=https://example.com/gemini-release-manifest.json
```

You can also pass `--manifest <https-url-or-local-path>` explicitly.

Remote sources must use HTTPS. Local paths are allowed for testing/offline administration.

## Check, install, rollback

```bash
python3 scripts/run.py --check-update
python3 scripts/run.py --update-info

# Explicit mutation requires a second opt-in.
python3 scripts/run.py --self-update --allow-self-update

# Pin a published version.
python3 scripts/run.py --self-update --update-version 1.4.1 --allow-self-update

python3 scripts/run.py --list-backups
python3 scripts/run.py --rollback --allow-self-update
python3 scripts/run.py --rollback --rollback-version 1.4.0 --allow-self-update
```

`--check-update` fetches only the manifest and caches metadata. `--self-update` downloads the selected standalone ZIP, verifies SHA-256, rejects unsafe ZIP entries, validates the candidate Skill, compiles all runtime Python, runs `run.py --help` as a smoke check, creates a local backup, and then replaces the Skill directory. A failed directory swap restores the previous Skill.

## Release manifest schema

```json
{
  "schema_version": 1,
  "provider": "gemini",
  "channels": {"stable": "1.5.1"},
  "releases": {
    "1.5.1": {
      "artifact_url": "https://example.com/gemini-skill-v1.5.1.zip",
      "sha256": "64-lowercase-hex-characters...",
      "breaking": false,
      "notes": "Short release note",
      "compatibility": {
        "tested_through_cli": "0.56.0"
      }
    }
  }
}
```

A model alias/version change does not by itself justify a Skill update. Update the Skill when Headless protocol, structured events, thinking configuration, permissions, session behavior, or wrapper logic changes.
