# Observability Console (frontend)

React + TypeScript + Vite + Material UI + Axios + Recharts + React Flow (`@xyflow/react`).
It only talks to the **API Gateway** (`/api/v1/...`) and never generates data itself.

## Run it

### Option A: with Docker (recommended)

From the project root (the folder with `docker-compose.yml`), after the backend patch is applied:

```powershell
docker compose up --build
```

Open **http://localhost:3000**. nginx serves the app and forwards `/api` to the `api-gateway` container, so there is no CORS setup.

### Option B: development mode (hot reload)

Keep the backend running with Docker (`docker compose up`), then in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite forwards `/api` to `http://localhost:8001` (change it with `VITE_GATEWAY_URL` in `frontend/.env`).
Requires Node 20 or newer.

### Sign in

| User | Default password (`.env`) | Can see |
|---|---|---|
| `viewer` | `viewer_password_change_me` | Overview, Trace Explorer, Dependency Map, Metrics, Alerts |
| `analyst` | `analyst_password_change_me` | + Log Explorer, Root Cause, acknowledge/resolve alerts |
| `admin` | `admin_password_change_me` | + change alert thresholds |

### Get data on the screens

```powershell
.\scripts\generate-traffic.ps1              # a mix of all six failure scenarios
.\scripts\generate-traffic.ps1 -Rounds 10   # more traffic: fills the charts and triggers alerts
```
Traces appear about 30 seconds after a request (the trace completion window). Metrics and alerts update every 30 seconds.

## Screens (task sections A to G)

| Route | Screen | What it shows |
|---|---|---|
| `/` | **Overview** | Total requests, error rate, avg / p95 / p99 latency, services with errors, active alerts, per-service health, latest failures. Time range + 15 s auto-refresh. |
| `/traces` | **Trace Explorer** | Search by trace ID or correlation ID; filter by status, completion, root service; paginated list. |
| `/traces/:id` | Trace detail | Request path, waterfall timeline (failed = red, slow = orange, missing parent = dashed), span details, latency contribution per service, related logs, diagnostic reports, "Run root-cause analysis". |
| `/dependencies` | **Dependency Map** | React Flow graph built from observed spans: request counts, error rates, latency, failing edges in red; click a service for incoming/outgoing dependencies. |
| `/logs` | **Log Explorer** (analyst+) | Filters (severity, service, time range, trace ID, correlation ID, text), expandable rows, trace links, and a *repeated error patterns* tab. |
| `/metrics` | **Metrics** | Request volume, error rate and latency trends (gaps shown for missing intervals), service comparison charts and a percentile table. |
| `/diagnostics`, `/diagnostics/:id` | **Root Cause** (analyst+) | Verdict (confirmed / probable / inconclusive / no issue), affected service, confidence, ranked services with reasons, failure timeline, latency contribution, limitations, grouped supporting evidence. |
| `/alerts` | **Alert Center** | Active / acknowledged / resolved, severity, measured vs threshold, evidence and related traces, acknowledge / resolve, thresholds tab (admin can edit). |

Behaviour worth knowing:
* A **partial result** (for example the log service is down) shows a yellow banner listing exactly what is missing.
* Errors say **who failed**: "Rejected by the API gateway" versus "query-service timed out", with the correlation ID to search for.
* A `401` signs you out; pages that need a higher role show an explanation instead of an empty table.

## Project layout

```
frontend/
  src/api/          typed Axios client + one function per backend endpoint (types.ts mirrors the API)
  src/auth/         login session, role checks
  src/components/   layout, chips, error/partial banners, trace waterfall
  src/pages/        the seven screens + login
  src/hooks/        useAsync (loading, polling, stale-response protection)
  nginx.conf        production proxy: /api -> api-gateway
  Dockerfile        build with Node, serve with nginx
```

## Checks I ran

* `tsc` strict type-check and `vite build` succeed.
* A contract test took real responses from the backend (through the gateway, with login) for every endpoint the console calls, and confirmed that every field the TypeScript types require exists in the JSON (33 objects, 26 interfaces).
* **Not done:** I could not open the app in a real browser here, so layout and interactions have not been seen by me. If something looks wrong on screen, send me a screenshot or the browser console error.
