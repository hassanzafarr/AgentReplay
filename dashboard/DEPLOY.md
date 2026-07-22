# Deploying the AgentReplay dashboard to Vercel

The dashboard is a **100% client-side Next.js app** — no backend, no API routes, no
env vars, no database. Traces are parsed and diffed in the browser. It builds to fully
static output, so it drops straight onto Vercel's free tier.

The one catch: the Next app lives in `dashboard/`, not the repo root. Point Vercel at it.

## Option A — Vercel dashboard (Git-connected, auto-deploys on push)

1. Push this repo to GitHub.
2. vercel.com → **Add New… → Project** → import the repo.
3. **Root Directory → `dashboard`** (this is the only non-default setting).
4. Framework auto-detects as **Next.js**. Leave build/output defaults.
5. **Deploy.** You get a live `*.vercel.app` URL; every push to `master` redeploys.

## Option B — Vercel CLI (one-off, from your machine)

```bash
npm i -g vercel
cd dashboard
vercel            # first run: link/create project, answer prompts
vercel --prod     # promote to the production URL
```

## Verify locally first

```bash
cd dashboard
npm install
npm run build     # must pass — it also runs the TypeScript check
npm run start     # serve the production build at http://localhost:3000
```

## Notes

- Visitors can drag in their own `.trace.json` files, or click **"try a sample trace"** /
  **"load a sample baseline vs. candidate"** — bundled sample traces live in
  `dashboard/public/samples/` so the live site is usable with zero uploads.
- Nothing is uploaded to a server; trace parsing/diffing is entirely in-browser.
- `agentreplay serve` (the Python CLI) is only for local `npm run dev`; it is unrelated
  to the Vercel deploy.
