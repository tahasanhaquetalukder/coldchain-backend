import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import requests
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from . import audit, database, hmac_auth, models
from .ai import predict as ai_predict

models.Base.metadata.create_all(bind=database.engine)


def ensure_columns(table: str, *names: str):
    """Add model columns a pre-existing table does not have yet.

    create_all builds a missing table but never alters an existing one, so a coldchain.db that already
    holds readings would keep ingesting with holes in the live view. PRAGMA table_info is SQLite-only,
    so this asks the SQLAlchemy inspector instead and lets the dialect name the column type - the same
    code runs against SQLite and the Postgres a deployed backend gets. Rows that predate the column
    come back NULL, which every reader of these columns already treats as 'unknown'.
    """
    have = {c["name"] for c in inspect(database.engine).get_columns(table)}
    missing = [n for n in names if n not in have]
    if not missing:
        return
    with database.engine.begin() as conn:
        for name in missing:
            col = models.Base.metadata.tables[table].columns[name]
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} "
                                 f"{col.type.compile(database.engine.dialect)}")


# what the live view reads: buffered = this arrived from the node's offline queue, received_ts = when
# the server got it (that pair is what keeps device clock drift separate from age), and hmac_key = the
# secret a node was issued, NULL meaning it still signs with the shared fleet key.
# compressor_on / power_ok were always signed and always thrown away; Task 5 needs the run history.
ensure_columns("readings", "buffered", "received_ts", "compressor_on", "power_ok")
ensure_columns("fridges", "hmac_key")

# `or` so that a blank JWT_SECRET= in the environment is treated as unset rather than as a signing key
# of zero bytes. The value it falls back to is a placeholder, and DEMO_SECRETS below is what refuses it.
JWT_SECRET = os.getenv("JWT_SECRET") or "CHANGE_ME_JWT_SECRET"
ENV = os.getenv("ENV", "development").strip().lower()
PRODUCTION = ENV == "production"
# origins the browser front-end is actually served from; empty means same-origin only
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
BUDGET = 60.0          # minutes above 8C per batch
LIVE_SKEW = 60         # seconds allowed for live messages
BUFFER_WINDOW = 3 * 3600
DOOR_LIMIT = 60        # seconds
NONCE_TTL = 86400      # replay protection window to keep

DEMO_SECRETS = {"JWT_SECRET": "CHANGE_ME_JWT_SECRET", "HMAC_SECRET_KEY": "CHANGE_ME_FLEET_KEY"}


def refuse_insecure_start():
    """The two values that decide who can sign in and who can sign a reading.

    Both have demo defaults, and a deployed backend that kept one is open to anyone who has read this
    source: the JWT default mints an admin token, the HMAC default forges any node's reading. So with
    ENV=production the process dies at import instead of serving traffic on a known secret.
    """
    if not PRODUCTION:
        return
    still_default = [name for name, default in DEMO_SECRETS.items()
                     if os.getenv(name, "") in ("", default)]
    if still_default:
        raise RuntimeError(f"ENV=production will not start on a missing or default "
                          f"{', '.join(still_default)} - set them to a fresh secrets.token_hex(32)")


refuse_insecure_start()


def seed_password(username: str) -> str:
    env = f"SEED_{username.upper()}_PASSWORD"
    value = os.getenv(env)
    if value:
        return value
    if PRODUCTION:
        raise RuntimeError(f"ENV=production will not create the {username} login without {env}")
    return f"{username}123"      # the documented demo credentials


# ---------- startup seed ----------
def seed(db: Session):
    if db.query(models.User).first():
        return
    for username in ("admin", "pharmacist", "inspector"):
        db.add(models.User(username=username, role=username,
               password_hash=bcrypt.hashpw(seed_password(username).encode(), bcrypt.gensalt()).decode()))
    db.add_all([models.Fridge(name="Fridge A", device_id="fridge-1"),
                models.Fridge(name="Fridge B", device_id="fridge-2")])
    db.commit()
    db.add_all([models.Batch(code="VAX-001", vaccine="MMR", expiry="2027-03-01", fridge_id=1),
                models.Batch(code="VAX-002", vaccine="Hepatitis B", expiry="2027-06-15", fridge_id=2)])
    db.commit()
    audit.create_audit_log(db, "SEED", "demo users, fridges and batches created")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = database.SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield


app = FastAPI(title="ColdChain API", lifespan=lifespan)
# "*" is only ever a dev convenience: it lets any page that can reach the API read every dashboard
# payload with the visitor's stored token. Production must name its origins in CORS_ORIGINS.
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS or (["*"] if not PRODUCTION else []),
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def service_card():
    """Names itself instead of 404-ing, for whoever opens the API host in a browser to see if it is alive."""
    return {"service": "ColdChain API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
def health():
    """Unauthenticated probe: Render's health check path and the first call to test when the dashboard cannot reach the API."""
    return {"ok": True, "time": round(time.time(), 2)}


# ---------- auth ----------
bearer = HTTPBearer()


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(d: Login, db: Session = Depends(database.get_db)):
    u = db.query(models.User).filter_by(username=d.username).first()
    if not u or not bcrypt.checkpw(d.password.encode(), u.password_hash.encode()):
        audit.create_audit_log(db, "LOGIN_FAILED", f"user={d.username}")
        raise HTTPException(401, "Wrong username or password")
    token = jwt.encode({"sub": u.username, "role": u.role, "exp": time.time() + 8 * 3600}, JWT_SECRET, "HS256")
    return {"token": token, "role": u.role, "username": u.username}


def roles(*allowed):
    def dep(c: HTTPAuthorizationCredentials = Depends(bearer)):
        try:
            p = jwt.decode(c.credentials, JWT_SECRET, algorithms=["HS256"])
        except Exception:
            raise HTTPException(401, "Session expired. Sign in again.")
        if p["role"] not in allowed:
            raise HTTPException(403, f"{p['role']} cannot do this")
        return p
    return dep


ANY = roles("admin", "pharmacist", "inspector")


# ---------- heat budget ----------
def batch_state(b):
    rem = max(0.0, BUDGET - b.used_minutes)
    pct = rem / BUDGET * 100
    status = "Discard" if pct <= 0 else "At Risk" if pct < 20 else "Safe"
    return {"remaining_min": round(rem, 1), "remaining_pct": round(pct, 1), "status": status}


def fridge_status(t):
    if t is None or t > 12 or t < 0:
        return "Breach"
    if t > 8 or t < 2:
        return "Warning"
    return "Safe"


def expiry_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(500, "Invalid batch expiry date")


# ---------- device ingest ----------
_last_nonce_cleanup = 0.0


def cleanup_old_nonces(db: Session):
    """Delete nonce records older than the replay-protection window."""
    global _last_nonce_cleanup
    now = time.time()
    # Throttled: a full-table delete on every single reading would dominate ingest cost.
    if now - _last_nonce_cleanup < 3600:
        return 0
    _last_nonce_cleanup = now
    deleted = (
        db.query(models.Nonce)
        .filter(models.Nonce.ts < now - NONCE_TTL)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def notify(text: str):
    """Best-effort Telegram alert. Silent when unconfigured, and never raises: an outage is exactly
    when this runs, and a hanging network call must not cost the reading that triggered it."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=3)
    except requests.RequestException:
        pass


class SensorMsg(BaseModel):
    device_id: str
    temperature: float
    door_open: bool
    ts: float
    nonce: str
    signature: str
    power_ok: bool = True
    battery: float = 100.0
    compressor_on: bool = False
    buffered: bool = False   # True when replayed from the offline buffer


# Rejections are the one thing an unauthenticated sender can produce on demand, and every audit row
# costs a hash of the previous one. (device, reason) gets one row per REJECT_LOG_INTERVAL and the
# count of what was swallowed rides along on the next one, so the live view can still add them up.
REJECT_LOG_INTERVAL = 60
_REJECT_SEEN = {}           # (device_id, reason) -> [last logged epoch, suppressed since then]


def log_rejection(db: Session, device_id: str, reason: str, nonce: str):
    now = time.time()
    seen = _REJECT_SEEN.setdefault((device_id, reason), [0.0, 0])
    if now - seen[0] < REJECT_LOG_INTERVAL:
        seen[1] += 1
        return
    # a bot cycling random device ids would otherwise grow this dict without bound; losing the
    # suppression counters is harmless, the next packet in each key starts counting again
    if len(_REJECT_SEEN) > 2048:
        _REJECT_SEEN.clear()
        seen = _REJECT_SEEN.setdefault((device_id, reason), [0.0, 0])
    details = f"device={device_id} reason={reason} nonce={nonce}"
    if seen[1]:
        details += f" suppressed={seen[1]}"
        seen[1] = 0
    seen[0] = now
    audit.create_audit_log(db, "MESSAGE_REJECTED", details)


@app.post("/api/sensor", status_code=201)
def sensor(m: SensorMsg, db: Session = Depends(database.get_db)):
    def reject(reason):
        log_rejection(db, m.device_id, reason, m.nonce)
        raise HTTPException(401, reason)

    f = db.query(models.Fridge).filter_by(device_id=m.device_id).first()
    # a node signs with the key it was handed at registration; the pre-key fleet still uses the shared secret
    key = f.hmac_key if f and f.hmac_key else hmac_auth.SECRET_KEY
    msg = hmac_auth.canonical(m.device_id, m.temperature, m.door_open, m.ts, m.nonce,
                              m.power_ok, m.battery, m.compressor_on, m.buffered)
    if not hmac_auth.verify(msg, m.signature, key):
        reject("invalid signature")
    window = BUFFER_WINDOW if m.buffered else LIVE_SKEW
    if abs(time.time() - m.ts) > window:
        reject("stale timestamp")
    if db.get(models.Nonce, m.nonce):
        reject("replayed nonce")
    if not f:
        reject("unknown device")
    db.add(models.Nonce(nonce=m.nonce, ts=m.ts))
    # Anything at or before the last accepted timestamp is ignored: no reading row, no budget minutes.
    # That is what makes a resend harmless, and it is also why the node must empty its offline buffer
    # oldest-first BEFORE sending live readings - one live sample lands ahead of the backlog and every
    # queued hour after it is silently dropped as out-of-order. See the buffer rule in README.md.
    if m.ts <= f.last_ts:
        db.commit()
        return {"status": "duplicate-ignored"}
    # heat budget: elapsed time since previous reading, weighted by temperature
    if f.last_ts:
        dt = min((m.ts - f.last_ts) / 60, 10)
        w = 2 if m.temperature > 12 else 1 if m.temperature > 8 else 0
        if w:
            for b in db.query(models.Batch).filter_by(fridge_id=f.id):
                before = batch_state(b)["status"]
                b.used_minutes += dt * w
                after = batch_state(b)["status"]
                if before != after:
                    audit.create_audit_log(db, "BATCH_STATUS", f"{b.code} {before} -> {after}")
    f.last_ts, f.temperature, f.power_ok = m.ts, m.temperature, m.power_ok
    f.battery, f.compressor_on = m.battery, m.compressor_on
    if m.door_open and not f.door_open:
        f.door_open_since, f.door_alerted = m.ts, False
    if not m.door_open:
        f.door_open_since, f.door_alerted = None, False
    f.door_open = m.door_open
    alert = None
    if f.door_open and not f.door_alerted and m.ts - f.door_open_since > DOOR_LIMIT:
        f.door_alerted = True
        alert = f"{f.name} door has been open over {DOOR_LIMIT} seconds"
        audit.create_audit_log(db, "DOOR_ALERT", alert)
    db.add(models.Reading(device_id=m.device_id, ts=m.ts, temperature=m.temperature,
                          door_open=m.door_open, buffered=m.buffered, received_ts=time.time(),
                          compressor_on=m.compressor_on, power_ok=m.power_ok))
    db.commit()
    cleanup_old_nonces(db)
    if alert:
        notify(alert)   # after the commit: SQLite holds one writer, and a network call must not sit inside it
    # Task 5: the same is true of the forecast, so a breach warning does not wait for somebody to open
    # the Insights page. Once a minute per node - each look reads back ninety minutes of rows.
    if ai_watch_due(m.device_id, time.time()):
        ai_evaluate(db, f)
    statuses = [batch_state(b)["status"] for b in db.query(models.Batch).filter_by(fridge_id=f.id)]
    return {"status": "ok",
            "batch_status": "Discard" if "Discard" in statuses else "At Risk" if "At Risk" in statuses else "Safe" if statuses else None}


# ---------- Task 5: the 30-minute forecast and the breach warning ----------
AI_LOOKBACK_S = 90 * 60     # rows handed to the feature builder; the window itself only needs 30 minutes
AI_CHECK_INTERVAL = 60      # seconds between two ingest-triggered evaluations of the same node
_AI_CHECKED = {}            # device_id -> last evaluation wall-clock, bounded like _REJECT_SEEN


def ai_watch_due(device_id, now):
    last = _AI_CHECKED.get(device_id, 0.0)
    if now - last < AI_CHECK_INTERVAL:
        return False
    if len(_AI_CHECKED) > 2048:
        _AI_CHECKED.clear()
    _AI_CHECKED[device_id] = now
    return True


def ai_rows(db: Session, device_id: str, since: float):
    """The tuples predict.forecast() expects, read straight from the table.

    Not through /api/readings: that route caps at 600 rows, which on a five-second node is fifty
    minutes and a quarter of them are usually the gap the forecast is being asked about.
    """
    return [(r.ts, r.temperature, r.compressor_on, r.door_open, r.power_ok)
            for r in db.query(models.Reading)
                        .filter(models.Reading.device_id == device_id, models.Reading.ts >= since)
                        .order_by(models.Reading.ts).all()]


def ai_evaluate(db: Session, f):
    """One forecast for one fridge, plus the single audit row and message a new episode earns.

    The episode bookkeeping is in app.ai.predict and is keyed by device, so the ingest path and this
    route can both call it and still produce one BREACH_WARNING per heat wave, not one per poll.
    """
    out = ai_predict.forecast(ai_rows(db, f.device_id, time.time() - AI_LOOKBACK_S), device_id=f.device_id)
    out["device_name"] = f.name
    if out.get("breach_warning_raised"):
        details = (f"{f.device_id} forecast above {out['threshold_c']:g} C within {out['horizon_min']} min: "
                   f"now {out['now_c']} C, peak {out['max_next_30_c']} C, model {out['model']}")
        audit.create_audit_log(db, "BREACH_WARNING", details)
        notify(f"{f.name}: predicted above {out['threshold_c']:g} C within {out['horizon_min']} minutes "
               f"(peak {out['max_next_30_c']} C, now {out['now_c']} C)")
    return out


@app.get("/api/ai/forecast")
def ai_forecast(device_id: str, _: dict = Depends(ANY), db: Session = Depends(database.get_db)):
    """Any logged-in role: a ward clerk who needs to know whether to move the stock now is not an admin."""
    f = db.query(models.Fridge).filter_by(device_id=device_id).first()
    if not f:
        raise HTTPException(404, "Unknown device")
    return ai_evaluate(db, f)


# ---------- dashboard & inventory ----------
def report_state(f):
    """A node that has never been heard of shows as unknown, not as the 5.0 the column defaults to.
    A fridge you registered ten minutes ago is not a fridge that is safe."""
    if not f.last_ts:
        return None, None
    return f.temperature, fridge_status(f.temperature)


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(ANY), db: Session = Depends(database.get_db)):
    out = []
    for f in db.query(models.Fridge).all():
        bs = [{"id": b.id, "code": b.code, "vaccine": b.vaccine, **batch_state(b)}
              for b in db.query(models.Batch).filter_by(fridge_id=f.id)]
        hist = (db.query(models.Reading).filter_by(device_id=f.device_id)
                .order_by(models.Reading.ts.desc()).limit(40).all())
        temperature, status = report_state(f)
        out.append({"id": f.id, "name": f.name, "device_id": f.device_id, "temperature": temperature,
                    "status": status, "door_open": f.door_open, "power_ok": f.power_ok,
                    "battery": f.battery, "compressor_on": f.compressor_on,
                    "door_alert": f.door_alerted, "online": time.time() - f.last_ts < 20,
                    "history": [r.temperature for r in reversed(hist)], "batches": bs})
    return out


# ---------- live device view ----------
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
REJECT_RE = re.compile(r"device=(\S+) reason=(.+?) nonce=(\S*)(?: suppressed=(\d+))?")


class DeviceIn(BaseModel):
    name: str
    device_id: str


def recent_rejects(db: Session, hours: int = 1):
    """Rejections grouped by the device that sent them.

    The audit log is the only place a rejected packet leaves a trace - nothing is stored on the
    readings path - so this is what turns "the dashboard is not moving" into "the node signs with a
    stale HMAC key" or "nobody registered fridge-3". Rejections are throttled to one audit row per
    (device, reason) per REJECT_LOG_INTERVAL, and the suppressed count on each row is added back here.
    """
    since = audit.utc_now() - timedelta(hours=hours)
    grouped = {}
    for l in (db.query(models.AuditLog)
              .filter(models.AuditLog.action == "MESSAGE_REJECTED", models.AuditLog.timestamp >= since)
              .order_by(models.AuditLog.id).all()):
        m = REJECT_RE.search(l.details or "")
        if not m:
            continue
        # group 3 is the nonce; the suppressed count is group 4 and is absent on the first row of a burst
        device, reason, swallowed = m.group(1), m.group(2), int(m.group(4) or 0)
        g = grouped.setdefault(device, {"n": 0, "reasons": {}, "last": 0.0})
        # one row stands for 1 + suppressed packets, so the throttle cannot hide a flood from the operator
        g["n"] += 1 + swallowed
        g["reasons"][reason] = g["reasons"].get(reason, 0) + 1 + swallowed
        g["last"] = l.timestamp.replace(tzinfo=timezone.utc).timestamp()
    return grouped


@app.get("/api/devices")
def devices(_: dict = Depends(ANY), db: Session = Depends(database.get_db)):
    now = time.time()
    rejects = recent_rejects(db)
    out = []
    for f in db.query(models.Fridge).order_by(models.Fridge.id).all():
        last = (db.query(models.Reading).filter_by(device_id=f.device_id)
                .order_by(models.Reading.id.desc()).first())
        temperature, status = report_state(f)
        age = None if not f.last_ts else round(now - f.last_ts, 1)
        drift = None if not (last and last.received_ts) else round(last.ts - last.received_ts, 1)
        bad = rejects.pop(f.device_id, None)
        out.append({
            "id": f.id, "name": f.name, "device_id": f.device_id,
            "topic": f"coldchain/{f.device_id}/reading",
            "temperature": temperature, "status": status,
            "door_open": f.door_open, "power_ok": f.power_ok, "battery": f.battery,
            "compressor_on": f.compressor_on, "door_alert": f.door_alerted,
            "last_ts": f.last_ts, "age_s": age,
            "readings": db.query(models.Reading).filter_by(device_id=f.device_id).count(),
            # 'replaying' is the offline buffer arriving: the node was dark and is emptying its queue
            "replaying": bool(last and last.buffered),
            "drift_s": drift,
            "online": age is not None and age < 20,
            # which secret this node is expected to sign with; the key itself never leaves the server
            "own_key": bool(f.hmac_key),
            "rejects": bad["n"] if bad else 0,
            "reasons": bad["reasons"] if bad else {},
        })
    return {"devices": out, "unknown": [{"device_id": d, **g} for d, g in rejects.items()]}


@app.post("/api/devices", status_code=201)
def add_device(d: DeviceIn, u=Depends(roles("admin")), db: Session = Depends(database.get_db)):
    device_id, name = d.device_id.strip(), d.name.strip()
    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(422, "A device id is 1-32 letters, digits, dot, dash or underscore - "
                                 "exactly what you wrote in cc_config.h")
    if not name or len(name) > 40:
        raise HTTPException(422, "Give the node a name of 1-40 characters")
    if db.query(models.Fridge).filter_by(device_id=device_id).first():
        raise HTTPException(409, f"{device_id} is already registered")
    f = models.Fridge(name=name, device_id=device_id, temperature=None,
                      hmac_key=secrets.token_hex(16))
    db.add(f)
    db.commit()
    audit.create_audit_log(db, "DEVICE_ADDED", f"{device_id} ({name}) by {u['sub']}")
    return {"id": f.id, "device_id": device_id, "hmac_key": f.hmac_key,
            "topic": f"coldchain/{device_id}/reading",
            "command_topic": f"coldchain/{device_id}/command"}


@app.post("/api/devices/{fid}/key")
def rotate_key(fid: int, u=Depends(roles("admin")), db: Session = Depends(database.get_db)):
    """Issue a new secret. The old one stops working on the next packet, so the node must be
    reflashed with what this call returns - there is no grace period and no way to read it again."""
    f = db.get(models.Fridge, fid)
    if not f:
        raise HTTPException(404, "No device with that id")
    f.hmac_key = secrets.token_hex(16)
    db.commit()
    audit.create_audit_log(db, "DEVICE_KEY_ROTATED", f"{f.device_id} by {u['sub']}")
    return {"status": "ok", "device_id": f.device_id, "hmac_key": f.hmac_key}


@app.delete("/api/devices/{fid}")
def remove_device(fid: int, u=Depends(roles("admin")), db: Session = Depends(database.get_db)):
    f = db.get(models.Fridge, fid)
    if not f:
        raise HTTPException(404, "No device with that id")
    dropped = db.query(models.Reading).filter_by(device_id=f.device_id).delete(synchronize_session=False)
    # batches outlive the node that stored them; only their location becomes unknown
    db.query(models.Batch).filter_by(fridge_id=f.id).update({"fridge_id": None})
    device_id, name = f.device_id, f.name
    db.delete(f)
    db.commit()
    audit.create_audit_log(db, "DEVICE_REMOVED",
                           f"{device_id} ({name}) and {dropped} readings deleted by {u['sub']}")
    return {"status": "ok", "device_id": device_id, "readings_deleted": dropped}


@app.get("/api/readings")
def readings(device_id: str, limit: int = 150, _: dict = Depends(ANY),
             db: Session = Depends(database.get_db)):
    """The last `limit` accepted readings for one node, oldest first - the trace the live view draws."""
    limit = max(1, min(limit, 600))
    rows = (db.query(models.Reading).filter_by(device_id=device_id)
            .order_by(models.Reading.id.desc()).limit(limit).all())
    return [{"id": r.id, "ts": r.ts, "temperature": r.temperature, "door_open": bool(r.door_open),
             "buffered": bool(r.buffered), "received_ts": r.received_ts or None}
            for r in reversed(rows)]


class BatchIn(BaseModel):
    code: str
    vaccine: str
    expiry: str
    fridge_id: Optional[int] = None


class MoveIn(BaseModel):
    fridge_id: Optional[int]


@app.get("/api/batches")
def batches(_: dict = Depends(ANY), db: Session = Depends(database.get_db)):
    return [{"id": b.id, "code": b.code, "vaccine": b.vaccine, "expiry": b.expiry,
             "fridge_id": b.fridge_id, **batch_state(b)} for b in db.query(models.Batch)]


@app.post("/api/batches", status_code=201)
def add_batch(d: BatchIn, u=Depends(roles("admin", "pharmacist")), db: Session = Depends(database.get_db)):
    try:
        date.fromisoformat(d.expiry)
    except ValueError:
        raise HTTPException(422, "Expiry must be an ISO date, e.g. 2027-03-01")
    if db.query(models.Batch).filter_by(code=d.code).first():
        raise HTTPException(409, "Batch code already exists")
    db.add(models.Batch(**d.model_dump())); db.commit()
    audit.create_audit_log(db, "BATCH_CREATED", f"{d.code} ({d.vaccine}) by {u['sub']}")
    return {"status": "ok"}


@app.put("/api/batches/{bid}/move")
def move(bid: int, d: MoveIn, u=Depends(roles("admin", "pharmacist")), db: Session = Depends(database.get_db)):
    b = db.get(models.Batch, bid)
    if not b:
        raise HTTPException(404, "Batch not found")
    old, b.fridge_id = b.fridge_id, d.fridge_id
    db.commit()
    audit.create_audit_log(db, "BATCH_MOVED", f"{b.code}: fridge {old} -> {d.fridge_id} by {u['sub']}")
    return {"status": "ok"}


@app.post("/api/batches/{bid}/reset")
def reset(bid: int, u=Depends(roles("admin")), db: Session = Depends(database.get_db)):
    b = db.get(models.Batch, bid)
    if not b:
        raise HTTPException(404, "Batch not found")
    b.used_minutes = 0
    db.commit()   # clears the red LED condition on the device side
    audit.create_audit_log(db, "ADMIN_RESET", f"{b.code} budget reset by {u['sub']}")
    return {"status": "ok"}


# ---------- public QR check (no login) ----------
@app.get("/api/public/batch/{code}")
def public_batch(code: str, db: Session = Depends(database.get_db)):
    batch = db.query(models.Batch).filter_by(code=code).first()
    if batch is None:
        raise HTTPException(404, "Batch not found")

    state = batch_state(batch)

    return {
        "code": batch.code,
        "vaccine": batch.vaccine,
        "expiry": batch.expiry,
        "status": state["status"],
        "expired": expiry_date(batch.expiry) < datetime.now().date(),
    }


# ---------- audit ----------
@app.get("/api/audits")
def audits(_: dict = Depends(roles("admin", "inspector")), db: Session = Depends(database.get_db)):
    """Named fields, newest first. Returning the ORM objects would publish whatever the model has today
    - including SQLAlchemy's own state - and the chain columns the UI must show would be incidental."""
    return [{"id": l.id, "action": l.action, "details": l.details,
             "previous_hash": l.previous_hash, "current_hash": l.current_hash,
             "timestamp": l.timestamp.isoformat()}
            for l in db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(200)]


@app.get("/api/audits/verify")
def verify(_: dict = Depends(roles("admin", "inspector")), db: Session = Depends(database.get_db)):
    return audit.verify_chain(db)
