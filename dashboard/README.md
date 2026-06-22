# Extending secdash with Sentinel panels

Your existing **secdash** Next.js app already lives on `192.168.1.217` and renders the
security view (threat map, IDS feed, per-domain, GeoIP). These files add Sentinel's
control-plane panels — **Deploy console**, **Infra**, **Audit log** — without touching
the security panels.

## How it fits

```
secdash (Next.js, :8095)
  app/page.jsx ............ add <SentinelPanels/>  (security panels stay as-is)
  app/SentinelPanels.jsx .. NEW (from here)
  app/api/sentinel/* ...... NEW route handlers -> proxy to sentinel-agent (FastAPI)
sentinel-agent (FastAPI, :8799)
  /api/infra /api/audit /api/deploy   <- the panels call these
```

## Steps

1. **Pull the current secdash source** off the box into this repo so you're editing the
   real app (run from the repo root):
   ```bash
   rsync -av aryan@192.168.1.217:~/secdash-next/ dashboard/secdash/   # adjust the path
   ```
   (In the cowork log the Next.js app was built under `~/secdash-next`.)

2. **Copy the drop-ins** into that app:
   ```bash
   cp dashboard/app/SentinelPanels.jsx        dashboard/secdash/app/
   cp -r dashboard/app/api/sentinel           dashboard/secdash/app/api/
   ```

3. **Mount the panels** in `app/page.jsx` — import and render below the security view:
   ```jsx
   import SentinelPanels from "./SentinelPanels";
   // ...inside the page, after the existing panels:
   <SentinelPanels />
   ```

4. **Point the routes at the agent.** Set `SENTINEL_AGENT_URL` for the dashboard
   container (defaults to `http://sentinel-agent:8799`, which is what the compose stack
   provides). See `docker-compose.yml` at the repo root.

5. **Rebuild + redeploy** the secdash container, then open `http://192.168.1.217:8095` —
   the Deploy / Infra / Audit panels render live alongside the security map.

The panels poll `/api/sentinel/*` every 8s; the Deploy console's **PLAN** button is a
dry run, **APPLY** sends `confirm:true` (and is styled red on purpose).
