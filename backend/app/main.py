import os
import re
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
from sqlalchemy.orm import Session

from . import audit, database, hmac_auth, models

models.Base.metadata.create_all(bind=database.engine)


def ensure_reading_columns():
    """create_all builds a missing table but never alters an existing one, so a coldchain.db that
    already holds readings would keep ingesting without the two columns the live view needs."""
    with database.engine.begin() as conn:
        have = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(readings)")}
        for column, decl in (("buffered", "BOOLEAN DEFAULT 0"), ("received_ts", "FLOAT DEFAULT 0")):
            if column not in have:
                conn.exec_driver_sql(f"ALTER TABLE readings ADD COLUMN {column} {decl}")


ensure_reading_columns()

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-jwt-secret")
BUDGET = 60.0          # minutes above 8C per batch
LIVE_SKEW = 60         # seconds allowed for live messages
BUFFER_WINDOW = 3 * 3600
DOOR_LIMIT = 60        # seconds
NONCE_TTL = 86400      # replay protection window to keep


# ---------- startup seed ----------
def seed(db: Session):
    if db.query(models.User).first():
        return
    for u, r in [("admin", "admin"), ("pharmacist", "pharmacist"), ("inspector", "inspector")]:
        db.add(models.User(username=u, role=r,
               password_hash=bcrypt.hashpw(f"{u}123".encode(), bcrypt.gensalt()).decode()))
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


@app.post("/api/sensor", status_code=201)
def sensor(m: SensorMsg, db: Session = Depends(database.get_db)):
    def reject(reason):
        audit.create_audit_log(db, "MESSAGE_REJECTED", f"device={m.device_id} reason={reason} nonce={m.nonce}")
        raise HTTPException(401, reason)

    msg = hmac_auth.canonical(m.device_id, m.temperature, m.door_open, m.ts, m.nonce,
                              m.power_ok, m.battery, m.compressor_on)
    if not hmac_auth.verify(msg, m.signature):
        reject("invalid signature")
    window = BUFFER_WINDOW if m.buffered else LIVE_SKEW
    if abs(time.time() - m.ts) > window:
        reject("stale timestamp")
    if db.get(models.Nonce, m.nonce):
        reject("replayed nonce")
    f = db.query(models.Fridge).filter_by(device_id=m.device_id).first()
    if not f:
        reject("unknown device")
    db.add(models.Nonce(nonce=m.nonce, ts=m.ts))
    if m.ts <= f.last_ts:    # duplicate / out-of-order: store nothing, no double counting
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
                          door_open=m.door_open, buffered=m.buffered, received_ts=time.time()))
    db.commit()
    cleanup_old_nonces(db)
    if alert:
        notify(alert)   # after the commit: SQLite holds one writer, and a network call must not sit inside it
    statuses = [batch_state(b)["status"] for b in db.query(models.Batch).filter_by(fridge_id=f.id)]
    return {"status": "ok",
            "batch_status": "Discard" if "Discard" in statuses else "At Risk" if "At Risk" in statuses else "Safe" if statuses else None}


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
REJECT_RE = re.compile(r"device=(\S+) reason=(.+?) nonce=(\S*)")


class DeviceIn(BaseModel):
    name: str
    device_id: str


def recent_rejects(db: Session, hours: int = 1):
    """Rejections grouped by the device that sent them.

    The audit log is the only place a rejected packet leaves a trace - nothing is stored on the
    readings path - so this is what turns "the dashboard is not moving" into "the node signs with a
    stale HMAC key" or "nobody registered fridge-3".
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    grouped = {}
    for l in (db.query(models.AuditLog)
              .filter(models.AuditLog.action == "MESSAGE_REJECTED", models.AuditLog.timestamp >= since)
              .order_by(models.AuditLog.id).all()):
        m = REJECT_RE.search(l.details or "")
        if not m:
            continue
        device, reason = m.group(1), m.group(2)
        g = grouped.setdefault(device, {"n": 0, "reasons": {}, "last": 0.0})
        g["n"] += 1
        g["reasons"][reason] = g["reasons"].get(reason, 0) + 1
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
    f = models.Fridge(name=name, device_id=device_id, temperature=None)
    db.add(f)
    db.commit()
    audit.create_audit_log(db, "DEVICE_ADDED", f"{device_id} ({name}) by {u['sub']}")
    return {"id": f.id, "device_id": device_id, "topic": f"coldchain/{device_id}/reading",
            "command_topic": f"coldchain/{device_id}/command"}


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
    return db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(200).all()


@app.get("/api/audits/verify")
def verify(_: dict = Depends(roles("admin", "inspector")), db: Session = Depends(database.get_db)):
    return audit.verify_chain(db)
