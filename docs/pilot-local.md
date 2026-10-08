# Local pilot: share the apps from this computer with a login

**Current hosting choice (2026-10-08):** the apps run on this computer in Docker, behind a username/password login. A Cloudflare quick tunnel gives a public HTTPS link for cofounders and investors. This replaces the VM option for now; `docs/deployment-plan.md` stays the plan for a real host later.

| Pros | Cons |
|---|---|
| No hosting account or bill; fatsecret already accepts this computer's IP (App A works as is) | The link works only while this computer is on and Docker is running |
| Each person gets their own login; it's one command to remove someone | The quick-tunnel URL changes every time the tunnel restarts; Cloudflare offers quick tunnels for testing, without an uptime guarantee |
| Photos aren't stored; the APIs are never exposed (only the two pages behind the login) | Every scan anyone runs costs real money (about $0.05 per App B scan; App A uses the fatsecret quota) |

## One-time setup

1. **Create a login for each person**, in your own PowerShell window in the project folder (it prompts for the password and never shows it):
   ```powershell
   .\scripts\pilot-user.ps1 -Name tony
   .\scripts\pilot-user.ps1 -Name cofounder1
   .\scripts\pilot-user.ps1 -Name investor1
   ```
   Passwords: 12+ printable characters, no spaces. Only bcrypt hashes are stored, in `infra/pilot/users.caddy` (git-ignored). Remove someone with `-Remove`.
2. **App B's database login** (App B needs read access to the food catalog):
   ```powershell
   docker exec -it foodvision-postgres-1 psql -U foodvision -d foodvision
   ```
   Then, inside psql:
   ```sql
   CREATE ROLE b_pilot LOGIN IN ROLE fv_inference;
   \password b_pilot
   \q
   ```

## Start (each session)

```powershell
# App B's database login, typed in this window only (the host inside Docker is "postgres")
$env:B_DATABASE_URL = "postgresql+psycopg://b_pilot:<the password you set>@postgres:5432/foodvision"
docker compose -f infra/compose.yml --profile app-a --profile app-b --profile pilot up -d --build
```

Check it yourself first at **http://localhost:8080**: log in, then open App A and App B and run one photo each.

## Share the link

```powershell
docker compose -f infra/compose.yml --profile pilot --profile tunnel up -d tunnel
docker compose -f infra/compose.yml logs tunnel | Select-String "trycloudflare.com"
```

Send each person the `https://….trycloudflare.com` link plus **their own** username. Send passwords separately, for example through a password manager or a different channel.

## Stop sharing / stop everything

```powershell
docker compose -f infra/compose.yml stop tunnel     # the public link stops working immediately
docker compose -f infra/compose.yml --profile app-a --profile app-b --profile pilot --profile tunnel stop
```

## What was verified (2026-10-08, locally in MOCK mode, nothing public)

- No login or a wrong password → 401. The right login → 200 for the landing page, App A and App B. Each password works only for its own user.
- Streamlit's live connection (WebSocket) passes through the login (101), and is refused without it (401).
- The APIs aren't reachable through the proxy (404). Request bodies are capped at 11 MB. Uploads over 10 MB are rejected by the app.
- Script: adds, replaces and removes logins; rejects short passwords and bad usernames. The stored hash was checked independently against the password.
- **Not yet verified:** the public quick tunnel (never started), the browser's own password prompt (a human check), and live (non-MOCK) scans through the proxy.
