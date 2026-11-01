# ColdChain — vaccine & insulin cold-chain monitor

ESP32 fridges report temperature, door, power and compressor state over a signed HTTP channel.
The server turns that into a per-batch **heat-exposure budget**, a role-based dashboard, a public
QR check and a **tamper-evident audit log**.

```
backend/    FastAPI + SQLAlchemy + SQLite   (REST API, HMAC ingest, JWT auth, hash-chain log)
frontend/   React + Vite + Tailwind         (dashboard, inventory, audit log, public QR page)
scripts/    smoke_test.py                   (Task 4 acceptance checks)
render.yaml Reference values for the two Render services — not applied as a Blueprint
USER_MANUAL.md                              (how to operate the app: roles, screens, QR, audit log)
```

## Requirements

- Python 3.11+ and Node 18+
- Backend deps are listed in `backend/requirements.txt`; create the venv yourself with
  `python -m venv venv && venv/Scripts/pip install -r requirements.txt` (`venv/` is gitignored)

## Run it

Three terminals. The SQLite path is relative to the working directory, so **start uvicorn from
`backend/`** or the database lands somewhere else.

```bash
# 1. API  -> http://127.0.0.1:8000  (docs at /docs)
cd backend
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# 2. Web app -> http://localhost:5173
cd frontend
npm install
npm run dev

# 3. Fake ESP32 (from the repo root; "hot" forces a heat excursion, "door" holds the door open)
backend\venv\Scripts\python.exe backend\simulator.py fridge-1
backend\venv\Scripts\python.exe backend\simulator.py fridge-2 hot
backend\venv\Scripts\python.exe backend\simulator.py fridge-1 door   # door alert after 60 s
```

On first start the API seeds two fridges (`fridge-1`, `fridge-2`), two batches (`VAX-001`,
`VAX-002`) and the three accounts below.

### If the fridges talk MQTT

Task 1 asks for MQTT and Task 4 asks for signed HTTP ingest. `backend/mqtt_bridge.py` satisfies both:
the ESP32 signs on the device and publishes that body to `coldchain/<device_id>/reading`, and the
bridge forwards it to `/api/sensor` unchanged. It never signs anything, so it cannot invent a reading.

```bash
mosquitto -p 1883
API_BASE=http://127.0.0.1:8000 MQTT_HOST=127.0.0.1 backend/venv/Scripts/python.exe backend/mqtt_bridge.py
```

## Demo accounts

| Role | Password | Can do |
| --- | --- | --- |
| admin | `admin123` | Everything, incl. resetting a spent heat budget |
| pharmacist | `pharmacist123` | Dashboard, create/move batches; no audit log, no resets |
| inspector | `inspector123` | Read-only dashboard, audit log and integrity check |

Permissions are enforced on the server, not just hidden in the UI.

## Task 4 → where it lives

| Requirement | Implementation |
| --- | --- |
| JWT + bcrypt, three roles, server-side enforcement | `backend/app/main.py` — `login()`, `roles()` dependency |
| Live dashboard: temp, door, power, compressor, budget | `GET /api/dashboard`, polled every 4 s by `frontend/src/App.jsx` |
| Live node view: freshness, replay, clock drift, rejections | `GET /api/devices`, `GET /api/readings`, the **Live** tab |
| Register a node without touching the database | `POST/DELETE /api/devices` (admin), same tab |
| Inventory: manage batches, assign/move between fridges | `GET/POST /api/batches`, `PUT /api/batches/{id}/move` |
| Public QR check without login | `GET /api/public/batch/{code}` → `http://localhost:5173/#/check/VAX-001` |
| HMAC-SHA256 + timestamp + nonce, reject and log | `backend/app/hmac_auth.py`, `POST /api/sensor`, `MESSAGE_REJECTED` audit rows |
| Hash chain + Verify Integrity | `backend/app/audit.py` — `create_audit_log()`, `verify_chain()`, `GET /api/audits/verify` |

### Heat-exposure budget

Each batch gets **60 budget-minutes above 8 °C**. Minutes are measured between consecutive
readings, so a dropped connection does not lose exposure time (capped at 10 min per step to stop a
long offline gap from instantly discarding a batch). Time above 12 °C counts **double**.
Below 20 % remaining → `At Risk`; at 0 % → `Discard`, which only an admin can clear.

### Device security

Every reading signs `device_id|temperature|door_open|ts|nonce|power_ok|battery|compressor_on`
with `HMAC_SECRET_KEY`. The server rejects a bad signature, a timestamp more than 60 s off
(3 h for `buffered: true` offline replays), a reused nonce, an out-of-order duplicate and an
unknown device — each rejection is written to the audit chain.

The ingest reply is the device's only instruction channel: `{"status":"ok",
"batch_status":"Safe"|"At Risk"|"Discard"|null}`. A node drives its red LED from `Discard` and
leaves it latched until an admin resets the batch, which is how Task 2's
"keep the red LED ON until admin reset" works when the budget lives on the server.

A door left open past 60 s is logged as `DOOR_ALERT` once (it does not re-alert while it stays
open) and, when `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set, pushed to Telegram after the
database commit so a slow network cannot delay the reading that triggered it.

### The Live tab: what a real node looks like

The dashboard answers "is this fridge safe". The **Live** tab answers "is this device actually
talking, and if not, why" — which is the only question while a node is being brought up.

| What it shows | Where it comes from |
| --- | --- |
| `live 3s` / `stale 40s` / `offline 12m` / `never reported` | `age_s` — seconds since the last **accepted** reading |
| `emptying buffer` | the newest accepted row carries `buffered: true`, i.e. the node is replaying its queue |
| `node clock is -0.7s against the server` | signed `ts` minus the server's arrival time, per reading (`readings.received_ts`) |
| the trace, with replayed points marked | `GET /api/readings?device_id=…&limit=…`, oldest first |
| `4 packets rejected in the last hour — 2 × replayed nonce …` | `MESSAGE_REJECTED` audit rows grouped by device, each reason explained |
| `fridge-9 — 1 rejected, latest unknown device` | packets for an id nobody registered, with a one-click register |
| MQTT topics for the node | `coldchain/<device_id>/reading` in, `/command` back out |

Register the node from the page (admin): the `DEVICE_ID` in `firmware/coldchain_node/cc_config.h`
must match the id exactly, or every packet is refused as `unknown device` and the node keeps
buffering. An id is 1–32 characters of `A-Z a-z 0-9 . _ -` because it becomes an MQTT topic.

A device that has never reported shows `--.-` and `No data`, not the 5.0 °C the column defaults to.
Nothing on this tab is inferred: every number is a packet that passed signature, window and nonce
checks, and the rejections sit beside it so an absent trace is explainable rather than mysterious.

## Verify it works

```bash
# scratch database so the demo data stays clean
mkdir scratch && cd scratch
set PYTHONPATH=../backend                # macOS/Linux: export PYTHONPATH=../backend
../backend/venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# then, from another terminal:
../backend/venv/Scripts/python.exe ../scripts/smoke_test.py --db coldchain.db
```

37 checks cover login and role enforcement, signed ingest, forged/stale/replayed rejection, the live
device endpoints (register, per-device rejections, arrival times, unregister), double-weighted budget
accrual, inventory validation, the public page and tamper detection.

## Publish on Render (free tier)

Two services, both created with **New → Web Service**; `render.yaml` records the same values but
must not be applied as a Blueprint once the API exists, or Render creates a second API with its own
empty database.

| Setting | Value |
| --- | --- |
| API | runtime Python, Root Directory `backend` |
| API build / start | `pip install -r requirements.txt` / `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| API URL | `https://<name Render gave it>.onrender.com` — read it off that service's header; the suffix is assigned, not chosen |
| API health check | `/api/health` — open it first when anything says the server is unreachable |
| Web | runtime Static, Root Directory `frontend`, build `npm ci && npm run build`, publish `dist` |
| Web env `VITE_API_URL` | the API URL above, exactly |

The API's bare root answers `{"detail":"Not Found"}` and that is correct — only `/api/...` routes
exist, and the dashboard is served by the static site, not by FastAPI.

`VITE_API_URL` is substituted into the bundle at **build** time, so it is not a runtime switch:
if you rename the API service, change the value in the web service's env panel and redeploy the web
service, or the page keeps calling the old host. `HMAC_SECRET_KEY` is pinned to the value
`simulator.py` signs with — change one without the other and every reading is rejected.

Keep the free instance warm and drive the demo with one command:

```bash
API_BASE=https://your-api-host.onrender.com backend/venv/Scripts/python.exe backend/simulator.py fridge-1
```

SQLite on Render is on an ephemeral disk: a redeploy or a long sleep recreates `coldchain.db`, and
`seed()` puts the two demo fridges and batches back. Readings posted while the instance is waking
are lost unless the device sends `buffered: true`, which the ingest accepts for 3 hours.

## Point the web app at another API

`frontend/.env.local` → `VITE_API_URL=http://192.168.1.20:8000` (LAN phone demo), or set the same
variable in the host's build environment. With no override, `npm run dev` targets
`http://127.0.0.1:8000` and a production build targets the origin it was served from — a published
bundle never points at `127.0.0.1`, because that is the visitor's own machine.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Published page says `Server not reachable` | `VITE_API_URL` was unset when `npm run build` ran, or the free API instance is asleep — open `/api/health` on the API host to tell the two apart |
| First visit after a quiet period takes ~50 s | Render free instances sleep when idle; run `simulator.py` with `API_BASE` pointed at it to stay awake |
| Every reading returns `401 invalid signature` after deploy | The API was rebuilt with a different `HMAC_SECRET_KEY` than the device signs with |
| `http://127.0.0.1:5173` refuses to connect | Vite binds `localhost` (often IPv6). Open `http://localhost:5173` or run `npm run dev -- --host` |
| Simulator prints `401 invalid signature` on every line | `HMAC_SECRET_KEY` differs between the server and the simulator process |
| Simulator prints `201` but dashboard stays `offline` | Dashboard marks a fridge offline after 20 s without a *live* reading; buffered replays still update the data |
| `no such table` / data vanished after a reboot | uvicorn was started outside `backend/`, so it made a new `coldchain.db` in that directory |
| Verify Integrity reports tampering | The audit rows were written by an older build of this app. Archive `backend/coldchain.db` and restart to re-seed |
| UI falls back to Times/system fonts | Google Fonts is unreachable (offline venue); layout is unaffected, only the typefaces change |

## Configuration notes

- `JWT_SECRET` and `HMAC_SECRET_KEY` are read from the process environment and fall back to
  hackathon defaults so the demo runs with zero setup. Set both before deploying anywhere real.
- `AUDIT_ANCHOR` moves the append-only head-anchor file (`audit_anchor.log`), which lets
  `verify_chain` also detect deleted records. Keep it on a different disk for it to mean anything.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` both have to be set for door alerts to leave the
  process; with either missing, the alert is still logged and nothing is sent. Get the token from
  `@BotFather` and the chat id from `@userinfobot`.
- `MQTT_HOST` / `MQTT_PORT` (bridge, default `127.0.0.1:1883`) and `API_BASE` (bridge and
  simulator) are separate: the bridge publishes to the broker and posts to the API, so it needs both.
- `backend/.env` is currently **inert** — no code calls `load_dotenv()`, and
  `backend/app/database.py` hard-codes SQLite. Set the variables in the shell instead.
- CORS is `allow_origins=["*"]` for the demo.
- Login state is kept in `localStorage`, so refreshing does not sign you out.
