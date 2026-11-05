# ColdChain — vaccine & insulin cold-chain monitor

ESP32 fridges report temperature, door, power and compressor state over a signed HTTP channel.
The server turns that into a per-batch **heat-exposure budget**, a role-based dashboard, a public
QR check and a **tamper-evident audit log**.

```
backend/app/            FastAPI routes, HMAC ingest, JWT auth, hash-chain audit log
backend/simulator.py    a fake ESP32 that signs readings and posts them over HTTP
backend/mqtt_bridge.py  broker -> /api/sensor forwarder; it never signs, so it cannot invent a reading
backend/requirements.txt
backend/tests/          pytest suite, run against a throwaway SQLite database
frontend/src/pages/     Login, Dashboard, Inventory, Devices, Audit, PublicCheck
frontend/src/components charts, readouts, badges, QR modal, shared state helpers
frontend/src/api.js     axios instance, Bearer header, VITE_API_BASE
frontend/src/auth.jsx   session context and the role gates
backend/.env.example    every variable the API reads, as placeholders
frontend/.env.example   VITE_API_BASE, the only variable the web app reads
firmware/               the Arduino ESP32 node and its native unit tests
firmware/coldchain_node/cc_config.example.h  the node's config template; cc_config.h is gitignored
scripts/smoke_test.py   acceptance checks run against a live server
render.yaml             Render Blueprint: Postgres + API + static site, no secret values in it
USER_MANUAL.md          how to operate the app: roles, screens, QR, audit log
```

## Requirements

- Python 3.11+ and Node 18+
- One requirements file covers both: `backend/requirements.txt` lists the runtime pins and, at the
  bottom, `pytest` + `httpx` for the test suite. A few MB in the deploy image is cheaper than a
  second file that goes stale.
- Create the venv yourself with `python -m venv venv && venv/Scripts/pip install -r requirements.txt`
  (`venv/` is gitignored)

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

# 3. Fake ESP32 (from the repo root; "hot" forces a heat excursion, "door" holds the door open,
#    "weak" and "powerfail" produce the two signals Task 5 scores - see the Insights page)
backend\venv\Scripts\python.exe backend\simulator.py fridge-1
backend\venv\Scripts\python.exe backend\simulator.py fridge-2 hot
backend\venv\Scripts\python.exe backend\simulator.py fridge-1 door   # door alert after 60 s
backend\venv\Scripts\python.exe backend\simulator.py fridge-1 weak       # runs long, cools little
backend\venv\Scripts\python.exe backend\simulator.py fridge-2 powerfail  # mains drops, battery drains
```

On first start the API seeds two fridges (`fridge-1`, `fridge-2`), two batches (`VAX-001`,
`VAX-002`) and the three accounts below.

Nothing has to be configured for that: unset variables fall back to the documented defaults, and the
secrets fall back to a placeholder that `ENV=production` refuses to run on.
`backend/app/database.py` calls `load_dotenv()`, so `backend/.env` **is** read at startup whatever
directory uvicorn was started from. Copy the tracked `backend/.env.example` to that `.env` and fill it
in — `.env.example` is committed and holds placeholders, `.env` is gitignored and holds the real
values, which is the other way round from what a stray export would give you.

## Environment variables

| Variable | Default | What it decides |
| --- | --- | --- |
| `ENV` | `development` | `production` refuses to boot on a missing or placeholder `JWT_SECRET`/`HMAC_SECRET_KEY`, refuses to seed a login without its `SEED_*_PASSWORD`, and stops allowing `*` in CORS |
| `DATABASE_URL` | `sqlite:///./coldchain.db` | a blank or unset value means SQLite. `postgres://` and `postgresql+psycopg://` are normalised to `postgresql://` for psycopg2, and an unreachable host exits with one line naming host:port instead of a traceback |
| `JWT_SECRET` | placeholder (`CHANGE_ME_JWT_SECRET`) | signs session tokens — the placeholder mints an admin login for anyone, so production refuses it |
| `HMAC_SECRET_KEY` | placeholder (`CHANGE_ME_FLEET_KEY`) | the **fleet** key, used only by nodes that predate per-device registration |
| `CORS_ORIGINS` | unset | comma-separated origins. Empty in dev means `*`; production must name them |
| `SEED_ADMIN_PASSWORD`<br>`SEED_PHARMACIST_PASSWORD`<br>`SEED_INSPECTOR_PASSWORD` | `<role>123` outside production | the seeded logins. Required in production, and only applied while the `users` table is empty |
| `AUDIT_ANCHOR` | `audit_anchor.log` | append-only head-anchor file; keep it off the database disk so a deleted row is still detectable |
| `MAX_BATCHES_PER_FRIDGE` | `6` | how many vaccine batches one fridge is assumed to hold. The only capacity figure the relocation rules have — nothing in the database describes the size of a box, so this is a number the operator sets per ward and the server applies to every node. A value that is not a whole number ≥ 1 stops the server from booting |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | unset | door-alert push. With either missing the alert is still logged and nothing is sent |
| `API_BASE` | `http://127.0.0.1:8000` | where `simulator.py` and `mqtt_bridge.py` post |
| `MQTT_HOST` / `MQTT_PORT` | `127.0.0.1` / `1883` | the broker the bridge subscribes to |
| `MQTT_USER` / `MQTT_PASS` | unset | broker login. Unset keeps the anonymous connect a local mosquitto answers |
| `MQTT_TLS` | `0` | `1` makes the bridge connect over TLS, which is what a hosted broker requires |
| `VITE_API_BASE` | dev only: `http://127.0.0.1:8000` | the API the built web app calls. Put it in `frontend/.env.local` (or the host's env panel), never in `backend/.env` |

`ENV`, `DATABASE_URL`, `AUDIT_ANCHOR`, `MAX_BATCHES_PER_FRIDGE` and the secrets are read at **import**
time, so a `.env` change needs a restart, not just a reload of the page.

### If the fridges talk MQTT

Task 1 asks for MQTT and Task 4 asks for signed HTTP ingest. `backend/mqtt_bridge.py` satisfies both:
the ESP32 signs on the device and publishes that body to `coldchain/<device_id>/reading`, and the
bridge forwards it to `/api/sensor` unchanged. It never signs anything, so it cannot invent a reading.

```bash
mosquitto -p 1883
API_BASE=http://127.0.0.1:8000 MQTT_HOST=127.0.0.1 backend/venv/Scripts/python.exe backend/mqtt_bridge.py
```

A hosted broker (HiveMQ Cloud and the rest) is the same bridge with three more variables, because it
listens on 8883 over TLS and wants a login. The topic, the payload and the signature do not change, so
a node that already works against the LAN bridge works against it too:

```bash
MQTT_HOST=<your-broker-host> MQTT_PORT=8883 MQTT_TLS=1 \
MQTT_USER=<broker-username> MQTT_PASS=<broker-password> \
API_BASE=https://<your-api-host> backend/venv/Scripts/python.exe backend/mqtt_bridge.py
```

`MQTT_USER`/`MQTT_PASS` are never printed by the bridge, including when the broker refuses them — it
says so and names the login, port and TLS switch instead. The matching defines on the node side are
`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS` and `MQTT_USE_TLS` in `cc_config.h`; a remote node
that should not depend on a broker at all can skip MQTT and use `INGEST_TRANSPORT INGEST_HTTP` with
`USE_HTTPS_DIRECT 1`. Both paths, and what each refusal means, are in `USER_MANUAL.md` section 9.

`bash firmware/tests/run_tests.sh` compiles the sketch in every one of those configurations — MQTT
plain, MQTT over TLS with a pinned CA, direct HTTP, direct HTTPS with a pinned CA — and checks the
node's canonical string and HMAC against vectors generated by the real `hmac_auth.canonical()`.

## Secrets

**The fleet key that this project used through the first sprint is compromised, and no amount of
editing the current files can undo that.** It was committed in plain text in
`firmware/coldchain_node/cc_config.h` and in `render.yaml`, which means it lives in the git history of
every clone and every fork. Anyone holding it can sign a reading that looks like it came from any
node that still uses the fleet key, and can forge the audit trail's input. It is being reported here,
not hidden.

The values themselves are gone from the working tree (the defaults in code are now the literal
placeholders `CHANGE_ME_FLEET_KEY` and `CHANGE_ME_JWT_SECRET`), and history has deliberately **not**
been rewritten — rewriting it would break the branch your teammate is on and does not un-leak a key
that has already been fetched.

Retire it in this order:

1. Make a new one: `python -c "import secrets; print(secrets.token_hex(32))"`, and set it as
   `HMAC_SECRET_KEY` on Render (and in `backend/.env` locally). Anything else the API answers is
   `invalid signature`, which is the failure you want.
2. Rotate every registered node from the **Devices** page (Rotate its key). A rotation kills the old
   key on the node's next packet, and the new key is shown once.
3. Reflash each ESP32 with the new `DEVICE_ID`/`HMAC_KEY` pair from that card. Per-node keys mean a
   reflash is only needed for the nodes you rotated.
4. Set a fresh `JWT_SECRET` too — the old default could mint an admin session for anyone who read the
   source. Sessions die when it changes, which is the point.

What must never be committed, and is now gitignored: `firmware/coldchain_node/cc_config.h` (Wi-Fi
password + node key), `.env` files, `*.db`, `*.db.bak`, `audit_anchor.log`. `cc_config.example.h` and
`.env.example` carry placeholders only.

A node's key is written once, at registration. No `GET`, no list, no audit row and no log line carries
it, so a leaked database dump does not let anyone sign.

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
| Live dashboard: temp, door, power, compressor, budget | `GET /api/dashboard`, polled every 5 s by `frontend/src/pages/Dashboard.jsx` |
| Node view: freshness, replay, clock drift, rejections | `GET /api/devices`, `GET /api/readings`, `frontend/src/pages/Devices.jsx` |
| Register a node and get its own key | `POST/DELETE /api/devices`, `POST /api/devices/{id}/key` (admin) |
| Inventory: manage batches, assign/move between fridges | `GET/POST /api/batches`, `PUT /api/batches/{id}/move`, `frontend/src/pages/Inventory.jsx` |
| Public QR check without login | `GET /api/public/batch/{code}` → `http://localhost:5173/#/check/VAX-001` |
| HMAC-SHA256 + timestamp + nonce, reject and log | `backend/app/hmac_auth.py`, `POST /api/sensor`, `MESSAGE_REJECTED` audit rows |
| Hash chain + Verify Integrity | `backend/app/audit.py` — `create_audit_log()`, `verify_chain()`, `GET /api/audits/verify`, `frontend/src/pages/Audit.jsx` |

## Task 5 → where it lives

| Requirement | Implementation |
| --- | --- |
| Features from a raw trace (minute grid, both flag kinds) | `backend/app/ai/features.py` |
| 30-minute forecast + breach warning, stdlib model serving | `backend/app/ai/predict.py`, `backend/app/ai/model.json` → `GET /api/ai/forecast` |
| Compressor health score 0–100 with reasons | `backend/app/ai/compressor.py` → `GET /api/ai/compressor` |
| Relocation suggestions from explainable rules | `backend/app/ai/relocation.py` → `GET /api/ai/relocations` |
| One-click confirm, recomputed server-side | `POST /api/ai/relocations/confirm` (admin + pharmacist), `RELOCATION_CONFIRMED` audit rows |
| Simulated training data, training, metrics, report | `ml/generate_data.py`, `ml/train.py`, `ml/evaluate.py`, `ml/make_report.py` → `docs/task5_report.md` |
| Repeatable live demo of all three answers | `backend/scripts/demo_task5.py` |

The rules read `MAX_BATCHES_PER_FRIDGE` as their capacity assumption and the forecast's `risk`
(`low` / `watch` / `high`) as their safety signal; both are explained in
[`docs/task5_report.md`](docs/task5_report.md).

### Running the AI demo

With the API up, one command leaves a fridge that is predicted to breach, a compressor score that has
fallen on it, and a move waiting to be confirmed — no training run, no real hardware, no waiting:

```powershell
$env:DEMO_PASSWORD = "admin123"        # the seeded demo admin; the script refuses to run without it
backend\venv\Scripts\python.exe backend\scripts\demo_task5.py
```

It registers two nodes (`demo-warm-1`, `demo-cold-1`), puts two batches in the warm one and posts ~155
signed readings per node, oldest first, as a buffer emptying: the warm fridge cools normally for four
compressor cycles, then slowly for three, then stops cutting in and creeps to 7.6 °C. Its own key is
used for the signing (`app/hmac_auth.py`, the same path `simulator.py` uses), so it is the real ingest
path, not a shortcut into the database.

Then open the web app as **pharmacist** or **admin**, AI Insights tab, and press **Confirm move**.
Signed in as **inspector** the same list is read-only, and a stale or forged `suggestion_id` is refused
with `409`. Run the script as often as you like: it appends the minutes a node is missing instead of
trying to re-write history the ingest has already seen, and it never confirms a move for you.

`API_BASE` points it at a deployed backend; `DEMO_USERNAME` at another admin. Full output
explanation in [`ml/README.md`](ml/README.md).

### Heat-exposure budget

Each batch gets **60 budget-minutes above 8 °C**. Minutes are measured between consecutive
readings, so a dropped connection does not lose exposure time (capped at 10 min per step to stop a
long offline gap from instantly discarding a batch). Time above 12 °C counts **double**.
Below 20 % remaining → `At Risk`; at 0 % → `Discard`, which only an admin can clear.

### Device security

Every reading signs

```
device_id|temperature|door_open|ts|nonce|power_ok|battery|compressor_on|buffered
```

with HMAC-SHA256, and the last field matters: `buffered` is what tells the server to widen the
timestamp window from 60 s to 3 h, so an unsigned flag would let a captured live sample be relabelled
as a backlog replay (or an hour-old one be sent as live). Python's `str(float)` is what the firmware
mirrors — `coldchain_core.h` prints the same digits, and `firmware/tests` checks the strings match.

The key is per node, not per fleet. Registering a device makes the server issue it a 32-hex-character
secret, shown once; from then on the shared `HMAC_SECRET_KEY` is refused for that id. Nodes that
predate registration (the two seeded fridges, `simulator.py`) keep using the fleet key until an admin
rotates them. No GET endpoint returns any key, and none is written to the audit log.

The server rejects a bad signature, a timestamp outside its window, a reused nonce, an out-of-order
duplicate and an unknown device. Each rejection answers `401` with the reason, and is written to the
audit chain — throttled to one row per (device, reason) per 60 s, with the suppressed count carried on
the next logged row so a flooded node cannot fill the chain.

#### The buffer rule: oldest first, before live readings

A reading at or before the node's last accepted timestamp is ignored: no row, no budget minutes. That
is what makes a resend harmless. It also means **the node must empty its offline buffer oldest-first
BEFORE it sends a live reading** — one live sample landing ahead of the backlog marks every queued
hour after it as out-of-order, and those minutes are dropped for good. The firmware drains the queue
in `setup()` before the first publish; a node that restarts into the middle of its backlog loses the
gap it had not replayed yet.

The ingest reply is the device's only instruction channel: `{"status":"ok",
"batch_status":"Safe"|"At Risk"|"Discard"|null}`. A node drives its red LED from `Discard` and
leaves it latched until an admin resets the batch, which is how Task 2's
"keep the red LED ON until admin reset" works when the budget lives on the server.

A door left open past 60 s is logged as `DOOR_ALERT` once (it does not re-alert while it stays
open) and, when `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set, pushed to Telegram after the
database commit so a slow network cannot delay the reading that triggered it.

### The Devices page: what a real node looks like

The dashboard answers "is this fridge safe". The **Devices** page answers "is this device actually
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

A device that has never reported shows `--.-` and `No data`, not the 5.0 °C the column defaults to.
Nothing on this page is inferred: every number is a packet that passed signature, window and nonce
checks, and the rejections sit beside it so an absent trace is explainable rather than mysterious.

### Bringing a real ESP32 online

1. Flash `firmware/coldchain_node` with the `DEVICE_ID` you want, in `cc_config.h` (Wi-Fi, broker and
   API host live in that one file). An id is 1–32 characters of `A-Z a-z 0-9 . _ -` because it becomes
   an MQTT topic; it has to match what the node sends, character for character, or every packet comes
   back `unknown device` and the node just keeps buffering.
2. **Devices → Register a node** (admin only). The server makes up a per-node key and shows it exactly
   once, as the two lines to paste:

   ```c
   #define DEVICE_ID   "fridge-3"
   #define HMAC_KEY    "3f9c…"   // 32 hex characters, generated by the server
   ```

3. Paste both into `cc_config.h`, reflash, restart. From the next packet that node signs with its own
   key and the shared `HMAC_SECRET_KEY` is refused for it. The badge on the page tells the two kinds
   apart: `own key` or `fleet key`.
4. **Rotate its key** issues a new one and the old stops working on the next packet — reflash before
   pressing it during a demo. **Unregister this node** deletes it and its readings; batches it held
   stay in inventory as unassigned.
5. A key is never readable again: no GET endpoint returns one and no audit row contains one. Losing
   the panel means rotating, not recovering.

The node's clock has to be NTP-synced, or every reading lands outside the 60 s window and the page
says `stale timestamp` — that is the single most common reason a freshly flashed device has no trace.

## Verify it works

```bash
# the whole backend suite, on a temporary SQLite file it makes and throws away
cd backend
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
python -m pytest tests -q

# frontend: production build
cd ../frontend && npm run build
```

The suite covers login and token expiry, the full role matrix, every ingest rejection reason and its
audit row, `buffered` being inside the signature, the double-weighted heat budget and its thresholds,
offline-buffer replay (in order, counted once, resends harmless), per-node keys including that no
endpoint leaks one, the rejection throttle, 50 concurrent audit writers against the hash chain,
tampering (an edited row, a deleted newest row) and the public page.

Two guards run in a subprocess, because they test what happens at import: `ENV=production` refuses to
start on a default secret, and refuses to create the seeded logins without their `SEED_*_PASSWORD`.

For an end-to-end check against a running server — `scripts/smoke_test.py`, which needs the API up on
a scratch database:

```bash
# scratch database so the demo data stays clean
mkdir scratch && cd scratch
set PYTHONPATH=../backend                # macOS/Linux: export PYTHONPATH=../backend
../backend/venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# then, from another terminal:
../backend/venv/Scripts/python.exe ../scripts/smoke_test.py --db coldchain.db
```

## Deploy to Render

`render.yaml` is a Blueprint: Postgres + the API + the static site in one file, with every secret left
out of it (Render generates `JWT_SECRET`, pulls `DATABASE_URL` from the database it creates, and marks
the rest `sync: false` so a human fills them in the dashboard and they are never stored in git).

**One warning before step 1.** If `coldchain-backend` already exists as a hand-created service, do not
import this Blueprint — Render would create a *second* API with its own empty database. Either use the
Blueprint for a fresh stack, or copy the env-var list below into the services you already have.

1. **New → Blueprint** on the repo, pick the branch, and Render reads `render.yaml`. It offers to
   create `coldchain-db`, `coldchain-backend` and `coldchain-web` together.
2. **Fill in the `sync: false` variables**, because Render leaves them blank on purpose and the API
   will not boot without them:

   | Variable | Where | Value |
   | --- | --- | --- |
   | `HMAC_SECRET_KEY` | API | the fleet key every node signs with — generate one, set it here **and** in every node that uses the fleet key |
   | `CORS_ORIGINS` | API | exactly the origin of the static site, no wildcard |
   | `SEED_ADMIN_PASSWORD`<br>`SEED_PHARMACIST_PASSWORD`<br>`SEED_INSPECTOR_PASSWORD` | API | the three logins. `ENV=production` refuses to seed `admin/admin123`, so with these unset the users table stays empty and there is nobody to sign in as |
   | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | API | optional; door alerts stay audit-log-only without them |
   | `VITE_API_BASE` | Web | the API host from step 3, exactly, no trailing slash |

3. **Read the API host off the service header** — `https://<name Render gave it>.onrender.com`. The
   suffix is assigned, not chosen, so do not write a guess into `VITE_API_BASE` or into a QR code.
4. **Set `VITE_API_BASE` on the web service, then trigger a manual build.** Vite substitutes it at
   build time; editing the env panel alone leaves the old bundle calling the old host.
5. **Deploy.** First cold start is 30–50 s on the free plan. Open `https://<api host>/api/health`
   before a demo or before judging any error page — `{"ok": true}` means the API is awake, and the
   service card at `/` names itself if you just open the host in a browser.
6. **Check the database really is Postgres**: the API logs one line at startup if it cannot reach the
   database (`Cannot reach the database at host:port/db. Unset DATABASE_URL to use local SQLite.`) and
   exits instead of hanging. That line never contains the password.

`ENV=production` is set in the Blueprint and is what makes steps 2 mandatory: the process refuses to
start on a missing or placeholder secret. For a throwaway demo you can unset `ENV` and let the
placeholders stand — but then the deployed API is signing sessions and readings with keys that are in
this README's source, which is exactly how the first sprint's fleet key got burned.

The free Postgres expires after 30 days of inactivity, and **every service's disk is ephemeral**: a
redeploy wipes `/tmp`, so `AUDIT_ANCHOR` (which the Blueprint points at `/tmp/coldchain_audit_anchor.log`)
loses its head hash. Rows edited in place are still caught; the whole log replaced is not. Data in the
database survives, because that is the attached Postgres, not the disk.

Keep the free instance warm and drive the demo with one command:

```bash
API_BASE=https://your-api-host.onrender.com backend/venv/Scripts/python.exe backend/simulator.py fridge-1
```

Readings posted while the instance is waking are lost unless the device sends `buffered: true`, which
the ingest accepts for 3 hours. With SQLite instead of Postgres, a redeploy recreates `coldchain.db`
and `seed()` puts the two demo fridges and batches back.

## Point the web app at another API

`frontend/.env.local` → `VITE_API_BASE=http://192.168.1.20:8000` (LAN phone demo), or set the same
variable in the host's build environment. With no override, `npm run dev` targets
`http://127.0.0.1:8000` and a production build targets the origin it was served from — a published
bundle never points at `127.0.0.1`, because that is the visitor's own machine. The header of the
signed-in app prints which API host the running bundle chose, so a mis-set variable is readable rather
than something to guess.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Published page says `Cannot reach the API at …` | `VITE_API_BASE` was unset when `npm run build` ran, or the free API instance is asleep — open `/api/health` on the API host to tell the two apart. The header names the host the bundle is calling |
| First visit after a quiet period takes ~50 s | Render free instances sleep when idle; run `simulator.py` with `API_BASE` pointed at it to stay awake |
| Every reading returns `401 invalid signature` after deploy | The API was rebuilt with a different `HMAC_SECRET_KEY` than the device signs with. A node registered through the app ignores the fleet key entirely — it signs with the secret it was issued, so a redeploy that restored `hmac_key = NULL` for that row breaks it too |
| `http://127.0.0.1:5173` refuses to connect | Vite binds `localhost` (often IPv6). Open `http://localhost:5173` or run `npm run dev -- --host` |
| Simulator prints `401 invalid signature` on every line | `HMAC_SECRET_KEY` differs between the server and the simulator process |
| Simulator prints `201` but the node shows `offline` | The dot goes red 20 s after the last accepted reading, live or buffered — a node that only sends every minute is `stale`, not broken |
| `no such table` / data vanished after a reboot | uvicorn was started outside `backend/`, so it made a new `coldchain.db` in that directory |
| The API prints one line — `Cannot reach the database at host:port/name` — and exits | `DATABASE_URL` (in the environment or in `backend/.env`) names a database that is not reachable. The line shows host, port and database name and never the password. `postgresql+psycopg://` is rewritten to `postgresql://` and still needs the driver that `requirements.txt` pins (psycopg2-binary); a URL Render gave a different service, or a local Postgres that is not running, lands here too. Set it to a reachable server, leave it blank for SQLite, or delete `backend/.env` |
| Verify Integrity reports tampering | The audit rows were written by an older build of this app. Archive `backend/coldchain.db` **and** `audit_anchor.log` together, then restart to re-seed |
| UI falls back to Times/system fonts | Google Fonts is unreachable (offline venue); layout is unaffected, only the typefaces change |

## Configuration notes

- `JWT_SECRET` and `HMAC_SECRET_KEY` fall back to a `CHANGE_ME_…` placeholder so the demo runs with
  zero setup, and `ENV=production` refuses to start while either is still a placeholder.
- `AUDIT_ANCHOR` moves the append-only head-anchor file (`audit_anchor.log`), which lets
  `verify_chain` also detect deleted records. Keep it on a different disk for it to mean anything, and
  archive it together with the database — a surviving anchor and a restored database read as tampering.
- `_CHAIN_LOCK` in `backend/app/audit.py` serialises the chain only within one process. Run **one
  worker per database**; several workers fork the chain and Integrity reports a tamper nobody made.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` both have to be set for door alerts to leave the
  process; with either missing, the alert is still logged and nothing is sent. Get the token from
  `@BotFather` and the chat id from `@userinfobot`.
- `MQTT_HOST` / `MQTT_PORT` (bridge, default `127.0.0.1:1883`) and `API_BASE` (bridge and
  simulator) are separate: the bridge publishes to the broker and posts to the API, so it needs both.
- `backend/.env` is read at import by `backend/app/database.py` (`load_dotenv()`), and `.env` is
  gitignored while `.env.example` is committed with placeholders. A variable already in the
  environment wins over the file, so `DATABASE_URL=` on the command line overrides a stale entry in
  `backend/.env`. `DATABASE_URL` selects the database: SQLite when unset **or blank**, and
  `postgres://` / `postgresql+psycopg://` are normalised to `postgresql://` for the pinned psycopg2.
  A non-SQLite target also gets `connect_timeout` (5 s, or `DB_CONNECT_TIMEOUT`), so an unreachable
  host is a one-line exit rather than a hang.
- CORS uses `CORS_ORIGINS` verbatim in production. Unset in development it is `allow_origins=["*"]`,
  which is a local convenience and not a deployable setting.
- The session is kept in `sessionStorage`, so refreshing keeps you signed in and closing the tab does
  not — a console left open on a shared ward terminal should not hand an admin token to the next person.
