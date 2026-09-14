# Vercel dashboard and Render gateway deployment

The React dashboard and FastAPI gateway are separate production services:

- Vercel serves the browser application.
- Render serves `/healthz`, `/v1/*`, and `/admin/*`.

Requests such as `/admin/keys` and `/admin/config` must be sent to the Render
origin. They are API endpoints, not Vercel routes.

## Required GitHub production configuration

Configure these GitHub Actions **production environment variables**:

| Variable | Example | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `https://p-156-latest.onrender.com` | Render gateway origin compiled into the Vercel bundle |
| `RENDER_GATEWAY_URL` | `https://p-156-latest.onrender.com` | Target used by the post-deploy smoke test |
| `VERCEL_PRODUCTION_ORIGIN` | `https://dashboard-ten-theta-86.vercel.app` | Expected browser origin for CORS validation |

Each value must be an HTTPS **origin only**. Do not append `/admin`, `/v1`, a
secret, query parameters, or credentials.

Configure these GitHub Actions **production environment secrets**:

| Secret | Purpose |
| --- | --- |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | Vercel CLI deployment |
| `RENDER_DEPLOY_WEBHOOK_URL` | Starts the Render production deployment |
| `ADMIN_KEY` | Read-only admin smoke test; must match Render's `ADMIN_KEY` |

The Vercel workflow validates `VITE_API_URL` before building. It rejects a URL
with a path/secret, a non-HTTPS URL, and a URL equal to the Vercel dashboard
origin.

## Render environment

Set at least:

```dotenv
APP_ENV=production
API_AUTH_REQUIRED=true
ADMIN_KEY=<strong-random-secret>
DATABASE_URL=<production-postgres-url>
ALLOWED_ORIGINS=https://dashboard-ten-theta-86.vercel.app
USE_MOCK_PROVIDERS=false
GEMINI_API_KEY=<provider-key>
GROQ_API_KEY=<provider-key>
OPENAI_API_KEY=<provider-key>
```

`ADMIN_KEY` belongs only in Render and the protected GitHub production
environment. It must never be a `VITE_*` variable because Vite values are
publicly readable in the browser bundle.

The gateway CORS middleware permits the configured origin and request headers,
including `X-Admin-Key`, `Authorization`, and `Content-Type`.

## Vercel environment

Configure both of these values in the Vercel **Production** environment before
starting a production build:

| Variable | Value |
| --- | --- |
| `VITE_API_URL` | `https://p-156-latest.onrender.com` |
| `VITE_API_KEY` | A dedicated, rate-limited `sr-...` browser key |

`VITE_API_KEY` is required when the public dashboard calls protected `/v1/*`
routes. It must never be `ADMIN_KEY`. Browser users can inspect every `VITE_*`
value.

`VITE_API_URL` is supplied by the GitHub production environment during the
automated build. It must also exist in Vercel Production because a direct
`vercel deploy` build reads Vercel's environment instead of GitHub's.

Changing a Vercel environment variable does not alter an existing build. Start
a new build after every build-time environment change. Do not redeploy a
prebuilt artifact when the new value must be compiled into the Vite bundle.

## Production deployment

The GitHub Actions production job is the normal release path. It checks out the
`main` commit that triggered the workflow, builds from `src/dashboard`, and
deploys a prebuilt artifact. A Vercel project that is only driven by this CLI
workflow may not show **Create Deployment** in the dashboard; that control is
available for Git-connected projects.

### Emergency deployment from a local machine

`vercel deploy` uploads the current directory. It does **not** fetch GitHub or
implicitly select `main`. Running it from a stale branch or a dirty working tree
can therefore replace production with uncommitted or old code. A CLI deployment
may also appear as a CLI source in Vercel instead of showing the usual GitHub
commit metadata; that is expected, but the revision must be verified locally.

Use a disposable clean worktree pinned to the latest remote `main`:

```powershell
cd D:\AI_ThucChien_Build
git fetch origin main
git worktree add .worktrees\prod-main origin/main
cd .worktrees\prod-main\src\dashboard

git status --porcelain
git rev-parse HEAD
git rev-parse origin/main

npx vercel@latest login
npx vercel@latest link --yes --project dashboard --scope nairyuuus-projects
npx vercel@latest deploy --prod --force
```

Before deploying, `git status --porcelain` must print nothing and the two commit
IDs must match. Run the commands from `src/dashboard`, not the repository root.
Use a normal build as shown above; do not add `--prebuilt`, because a prebuilt
artifact can retain old build-time environment values.

The command must finish by assigning the production alias:

```text
Aliased https://dashboard-ten-theta-86.vercel.app
```

If `.worktrees\prod-main` already exists, remove it only after confirming it has
no work you need, or choose a new disposable worktree name.

## Bootstrap the first gateway key

After Render is deployed, open the dashboard's **API Keys** page and enter the
Render `ADMIN_KEY`. The dashboard sends it in `X-Admin-Key` to
`https://<render-origin>/admin/keys`. Create a dedicated key and copy the full
`sr-...` value immediately; it is shown only once.

Never put either key in a URL. Revoke or rotate any key that has appeared in a
URL, screenshot, browser history, or log.

## Automated smoke test

After the Render webhook is triggered, `scripts/smoke_admin_api.py` waits for
`/healthz`, then performs read-only checks:

1. CORS preflight from the Vercel production origin to `/admin/keys`.
2. Authenticated `GET /admin/keys`.
3. Authenticated `GET /admin/config`.

The test never creates keys and never prints `ADMIN_KEY`.

Run it manually with the same three environment values when diagnosing a
deployment:

```bash
RENDER_GATEWAY_URL=https://p-156-latest.onrender.com \
VERCEL_PRODUCTION_ORIGIN=https://dashboard-ten-theta-86.vercel.app \
ADMIN_KEY=... \
python scripts/smoke_admin_api.py
```

## Rollback

For Vercel, promote a known-good deployment and revert the faulty commit. For
Render, redeploy a known-good image. Promotion reuses the old build; when a
build-time environment value changed, create a fresh build from the corrected
commit instead. Run the smoke test after either rollback.
