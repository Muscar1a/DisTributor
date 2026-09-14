# Render staging deployment

Issue #90 adds an isolated staging path from the `dev` branch:

`dev` push -> GitHub Actions -> `ghcr.io/ai20k-build-phase-cohort-3/p-156:latest-dev` -> Render deploy webhook -> staging service

Production remains on the `main` branch and the `latest` image tag.

## Environment matrix

| Setting | Local development | Staging | Production |
|---|---|---|---|
| `APP_ENV` | `development` | `staging` | `production` |
| `API_AUTH_REQUIRED` | `false` | `true` | `true` |
| `DATABASE_URL` | Docker PostgreSQL: `postgresql+psycopg2://sr:smartroute@localhost:5432/smartroute` | Staging Supabase pooler URL with `sslmode=require` | Production Supabase pooler URL with `sslmode=require` |
| `GATEWAY_DEV_KEY` | Optional local key | Staging-only secret | Production-only secret |
| `ADMIN_KEY` | Optional local key | Staging-only secret | Production-only secret |
| `GEMINI_API_KEY` | Optional | Staging secret | Production secret |
| `GROQ_API_KEY` | Optional | Staging secret | Production secret |
| `OPENAI_API_KEY` | Optional | Staging secret | Production secret |
| `USE_MOCK_PROVIDERS` | Team choice | `false` | `false` |
| `VITE_API_URL` | `http://localhost:8000` | Staging HTTPS URL | Production HTTPS URL |
| `VITE_API_KEY` | Optional local key | Restricted staging client key | Restricted production client key |

Local development intentionally uses PostgreSQL through `docker compose`; SQLite is not supported. Keep staging and production database credentials, gateway keys, and provider keys separate. `VITE_*` variables are embedded in browser assets and must never contain provider, database, admin, GitHub, or Render secrets.

## One-time Render setup

1. Create a second Render Web Service using **Existing Image**.
2. Configure the image as `ghcr.io/ai20k-build-phase-cohort-3/p-156:latest-dev`.
3. Add GHCR registry credentials with package-read permission if the package is private.
4. Configure the staging values from the matrix above, using a staging Supabase pooler URL with `sslmode=require`.
5. Set the health-check path to `/healthz`.
6. Copy the staging service deploy-hook URL and treat it as a secret.
7. Add it to GitHub Actions as `RENDER_STAGING_DEPLOY_WEBHOOK_URL`.

The workflow `.github/workflows/deploy-staging.yml` builds and pushes `latest-dev` for every push to `dev`, then calls the staging hook only after the image push succeeds. It also supports manual runs from the Actions page.

## Verification

1. Merge or push a harmless change to `dev`.
2. Confirm **Deploy Staging to Render** succeeds in both jobs.
3. Confirm GHCR shows a new `latest-dev` image for the workflow commit.
4. Confirm Render deploys that image digest successfully.
5. Run:

   ```bash
   curl --fail https://YOUR-STAGING-SERVICE.onrender.com/healthz
   curl --fail https://YOUR-STAGING-SERVICE.onrender.com/readyz
   ```

6. Send an authenticated request to `/v1/chat/completions` and verify it is recorded in the staging database, not production.

If the workflow fails in **Validate staging deploy webhook**, add the repository secret and rerun the failed job. If Render cannot pull the image, verify the lowercase GHCR path and registry credential permissions.
