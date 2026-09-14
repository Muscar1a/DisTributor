# SmartRoute Dashboard

React/Vite playground for exercising the SmartRoute gateway and inspecting its routing metadata.

## Local development

```bash
cp .env.example .env.local
npm ci
npm run dev
```

Set `VITE_API_URL` to the gateway origin. `VITE_API_KEY` is optional; because Vite exposes `VITE_*` values to the browser, it must only contain a restricted demo key, never an administrative or server-side secret.

## Vercel

1. Import the repository and set **Root Directory** to `src/dashboard`.
2. Add `VITE_API_URL` and, if required, a restricted `VITE_API_KEY` in Project Settings → Environment Variables for Preview and Production.
3. Add the Vercel site origin to the gateway's `CORS_ORIGINS` setting.
4. Add a `VERCEL_STAGING_DOMAIN` repository variable containing the staging hostname without `https://`, for example `dashboard-staging.example.com`.
5. Point that hostname at Vercel before the first staging deployment. The workflow updates its alias after every merge to `dev`.
6. Deploy. Pull requests create Preview deployments, `dev` updates the stable staging alias with Preview variables, and `main` deploys Production. `vercel.json` builds with `npm run build` and publishes `dist`.

Verify the header shows **Connected**, then send a prompt and confirm the routing panel and feedback flow work against the deployed gateway.
