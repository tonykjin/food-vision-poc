# Credential Handling

How this project keeps secrets out of Git, out of Claude's context and out of UI users' reach. **This file never contains secret values.**

**Last updated:** 2026-10-02 (Prompt 05)

## Where secrets live

| Secret-bearing location | Used by | Tracked? |
|---|---|---|
| `.env.provider.local` | App A (fatsecret, USDA, provider DB URL) | No (`.gitignore`) |
| `.env.agent.local` | App B (vision model key, USDA, agent DB URL) | No (`.gitignore`) |
| `secrets/` | Any other key material or service-account files | No (`.gitignore`) |
| Deployment secrets store | Hosted pilot (chosen in Prompt 27) | N/A |
| `.env.example` | Variable **names** only, with empty values | Yes. Claude may read it. |

The evaluator database URL (hidden benchmark labels) must never be present in either inference app's env file.

## Controls in place

1. **Git:** `.gitignore` ignores `.env`, `.env.*` (except `.env.example`), `*.env`, `secrets/`, `.secrets/`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `credentials*.json`, `service-account*.json`. Verified with `git check-ignore` in Prompt 04.
2. **Claude Code permission rules** (`.claude/settings.json`, project scope, tracked): `Read` and `Edit` deny rules anchored at the project root (`/**/...`) cover `.env`, `.env.local`, `.env.*.local`, `*.env`, `secrets/**`, `.secrets/**`, `*.pem`, `*.key`, `credentials*.json`, `service-account*.json`. `.env.example` doesn't match any rule, so it stays readable. `disableBypassPermissionsMode` is set to `disable`.
   - Verified 2026-10-02: Read of `.env.agent.local` and of `secrets/x.json` was denied. A Bash `touch .env.provider.local` / `secrets/dummy.json` was denied. Read of `.env.example` succeeded.
3. **Instructions:** `CLAUDE.md` says to never read, print or echo secret values, even when troubleshooting.
4. **Pre-commit inspection:** check the staged file list and scan the staged diff for credential patterns before every commit.

## What these controls do NOT prevent

From the official permissions docs (https://code.claude.com/docs/en/permissions):

- Read and Edit deny rules apply to Claude's file tools, to Bash file commands Claude Code recognizes (`cat`, `head`, `tail`, `sed`, `tee`) and to redirect targets. **They do not apply** to commands that read files without naming them (for example `grep -r pattern .`), or to subprocesses that open files themselves (a Python or Node script, `uv run`, the app itself). For example, `uv run foodvision doctor` will legitimately load the env file.
- `CLAUDE.md` is guidance, not an enforcement boundary.
- The rules are anchored at the session's primary working directory. A Claude session started outside the project root doesn't get this project's settings. Always start `claude` from the project root.
- OS-level enforcement would need the Claude Code sandbox: see "Remaining options" below.

## Credential presence checks (boolean only)

Runtime checks report whether a credential is **set**, never its value, length, prefix or hash. The `foodvision doctor --app provider|agent` entry point (plan §6, built from Prompt 10 on) must follow this contract:

```text
FATSECRET_CLIENT_ID      set
FATSECRET_CLIENT_SECRET  missing
USDA_API_KEY             set
```

Rules:
- Print only `set` or `missing` (empty counts as missing). Never echo, mask-print or log a value, including in exceptions and tracebacks.
- Settings models mark secrets with `pydantic.SecretStr` so `repr` and logs show `**********`.
- Live validation (a real authenticated call) happens only in explicit opt-in smoke tests (`ENABLE_LIVE_API_TESTS=true`) and reports pass or fail, not response bodies that contain tokens.
- Claude never runs commands that print env-file contents or environment values (`cat .env*`, `Get-Content .env*`, `printenv`, `Get-ChildItem env:`, `gh auth token`), even for troubleshooting. Use the boolean check instead.

## Remaining options (not enabled)

- **Claude Code sandbox:** OS-level filesystem and network isolation for Bash (https://code.claude.com/docs/en/sandboxing). Consider it before provider keys are first stored locally (Prompt 07/19).
- **GitHub secret scanning and push protection:** PENDING (plan Step 3; see `docs/project-settings.md`).
- **Provider-side limits:** spend caps and per-key restrictions on each runtime API account (Prompt 07).
- **Key rotation:** rotate any key that was ever pasted into a chat, an issue or a log.
