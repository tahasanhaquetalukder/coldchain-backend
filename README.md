# ColdChain — vaccine & insulin cold-chain monitor

ESP32 fridges report temperature, door, power and compressor state over a signed HTTP channel.
The server turns that into a per-batch **heat-exposure budget**, a role-based dashboard, a public
QR check and a **tamper-evident audit log**.

```
backend/    FastAPI + SQLAlchemy + SQLite   (REST API, HMAC ingest, JWT auth, hash-chain log)
frontend/   React + Vite + Tailwind         (dashboard, inventory, audit log, public QR page)
scripts/    smoke_test.py                   (Task 4 acceptance checks)
```

## Requirements

- Python 3.11+ and Node 18+
- Backend deps are pinned in `backend/requirements.txt` (a ready `backend/venv` is committed for
  Windows; recreate with `python -m venv venv` if you start fresh)

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

# 3. Fake ESP32 (from the repo root; add "hot" to force a heat excursion)
backend\venv\Scripts\python.exe backend\simulator.py fridge-1
backend\venv\Scripts\python.exe backend\simulator.py fridge-2 hot
```

On first start the API seeds two fridges (`fridge-1`, `fridge-2`), two batches (`VAX-001`,
`VAX-002`) and the three accounts below.

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

## Verify it works

```bash
# scratch database so the demo data stays clean
mkdir scratch && cd scratch
set PYTHONPATH=../backend                # macOS/Linux: export PYTHONPATH=../backend
../backend/venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# then, from another terminal:
../backend/venv/Scripts/python.exe ../scripts/smoke_test.py --db coldchain.db
```

27 checks cover login and role enforcement, signed ingest, forged/stale/replayed rejection,
double-weighted budget accrual, inventory validation, the public page and tamper detection.

## Point the web app at another API

`frontend/.env.local` → `VITE_API_URL=http://192.168.1.20:8000`. Default is
`http://127.0.0.1:8000`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
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
- `backend/.env` is currently **inert** — no code calls `load_dotenv()`, and
  `backend/app/database.py` hard-codes SQLite. Set the variables in the shell instead.
- CORS is `allow_origins=["*"]` for the demo.
- Login state is kept in `localStorage`, so refreshing does not sign you out.
