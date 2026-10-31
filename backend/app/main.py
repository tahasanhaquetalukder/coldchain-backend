import time, os, bcrypt, jwt
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from . import models, database, audit, hmac_auth

models.Base.metadata.create_all(bind=database.engine)
app = FastAPI(title="ColdChain API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-jwt-secret")
BUDGET = 60.0          # minutes above 8C per batch
LIVE_SKEW = 60         # seconds allowed for live messages
BUFFER_WINDOW = 3 * 3600
DOOR_LIMIT = 60        # seconds

# ---------- startup seed ----------
@app.on_event("startup")
def seed():
    db = database.SessionLocal()
    if not db.query(models.User).first():
        for u, r in [("admin", "admin"), ("pharmacist", "pharmacist"), ("inspector", "inspector")]:
            db.add(models.User(username=u, role=r,
                   password_hash=bcrypt.hashpw(f"{u}123".encode(), bcrypt.gensalt()).decode()))
        db.add_all([models.Fridge(name="Fridge A", device_id="fridge-1"),
                    models.Fridge(name="Fridge B", device_id="fridge-2")])
        db.commit()
        db.add_all([models.Batch(code="VAX-001", vaccine="MMR", expiry="2027-03-01", fridge_id=1),
                    models.Batch(code="VAX-002", vaccine="Hepatitis B", expiry="2027-06-15", fridge_id=2)])
        db.commit()
    db.close()

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
            p = jwt.decode(c.credentials, JWT_SECRET, ["HS256"])
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
    if t > 12 or t < 0: return "Breach"
    if t > 8 or t < 2: return "Warning"
    return "Safe"

# ---------- device ingest ----------
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
    msg = hmac_auth.canonical(m.device_id, m.temperature, m.door_open, m.ts, m.nonce, m.power_ok, m.battery, m.compressor_on)
    if not hmac_auth.verify(msg, m.signature): reject("invalid signature")
    window = BUFFER_WINDOW if m.buffered else LIVE_SKEW
    if abs(time.time() - m.ts) > window: reject("stale timestamp")
    if db.get(models.Nonce, m.nonce): reject("replayed nonce")
    f = db.query(models.Fridge).filter_by(device_id=m.device_id).first()
    if not f: reject("unknown device")
    db.add(models.Nonce(nonce=m.nonce, ts=m.ts))
    if m.ts <= f.last_ts:            # duplicate / out-of-order: store nothing, no double counting
        db.commit(); return {"status": "duplicate-ignored"}
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
    if m.door_open and not f.door_open: f.door_open_since, f.door_alerted = m.ts, False
    if not m.door_open: f.door_open_since, f.door_alerted = None, False
    f.door_open = m.door_open
    if f.door_open and not f.door_alerted and m.ts - f.door_open_since > DOOR_LIMIT:
        f.door_alerted = True
        audit.create_audit_log(db, "DOOR_ALERT", f"{f.name} door open > {DOOR_LIMIT}s (notify via Telegram/SMS here)")
    db.add(models.Reading(device_id=m.device_id, ts=m.ts, temperature=m.temperature, door_open=m.door_open))
    db.commit()
    return {"status": "ok"}

# ---------- dashboard & inventory ----------
@app.get("/api/dashboard")
def dashboard(_=Depends(ANY), db: Session = Depends(database.get_db)):
    out = []
    for f in db.query(models.Fridge).all():
        bs = [{"id": b.id, "code": b.code, "vaccine": b.vaccine, **batch_state(b)}
              for b in db.query(models.Batch).filter_by(fridge_id=f.id)]
        hist = db.query(models.Reading).filter_by(device_id=f.device_id).order_by(models.Reading.ts.desc()).limit(40).all()
        out.append({"id": f.id, "name": f.name, "device_id": f.device_id, "temperature": f.temperature,
                    "status": fridge_status(f.temperature), "door_open": f.door_open, "power_ok": f.power_ok,
                    "battery": f.battery, "compressor_on": f.compressor_on,
                    "door_alert": f.door_alerted, "online": time.time() - f.last_ts < 20,
                    "history": [r.temperature for r in reversed(hist)], "batches": bs})
    return out

class BatchIn(BaseModel):
    code: str
    vaccine: str
    expiry: str
    fridge_id: Optional[int] = None

class MoveIn(BaseModel):
    fridge_id: Optional[int]

@app.get("/api/batches")
def batches(_=Depends(ANY), db: Session = Depends(database.get_db)):
    return [{"id": b.id, "code": b.code, "vaccine": b.vaccine, "expiry": b.expiry,
             "fridge_id": b.fridge_id, **batch_state(b)} for b in db.query(models.Batch)]

@app.post("/api/batches", status_code=201)
def add_batch(d: BatchIn, u=Depends(roles("admin", "pharmacist")), db: Session = Depends(database.get_db)):
    if db.query(models.Batch).filter_by(code=d.code).first(): raise HTTPException(409, "Batch code already exists")
    db.add(models.Batch(**d.dict())); db.commit()
    audit.create_audit_log(db, "BATCH_CREATED", f"{d.code} ({d.vaccine}) by {u['sub']}")
    return {"status": "ok"}

@app.put("/api/batches/{bid}/move")
def move(bid: int, d: MoveIn, u=Depends(roles("admin", "pharmacist")), db: Session = Depends(database.get_db)):
    b = db.get(models.Batch, bid)
    if not b: raise HTTPException(404, "Batch not found")
    old, b.fridge_id = b.fridge_id, d.fridge_id; db.commit()
    audit.create_audit_log(db, "BATCH_MOVED", f"{b.code}: fridge {old} -> {d.fridge_id} by {u['sub']}")
    return {"status": "ok"}

@app.post("/api/batches/{bid}/reset")
def reset(bid: int, u=Depends(roles("admin")), db: Session = Depends(database.get_db)):
    b = db.get(models.Batch, bid)
    if not b: raise HTTPException(404, "Batch not found")
    b.used_minutes = 0; db.commit()   # clears the red LED condition on the device side
    audit.create_audit_log(db, "ADMIN_RESET", f"{b.code} budget reset by {u['sub']}")
    return {"status": "ok"}

# ---------- public QR check (no login) ----------
@app.get("/api/public/batch/{code}")
def public_batch(code: str, db: Session = Depends(database.get_db)):
    b = db.query(models.Batch).filter_by(code=code).first()
    if not b: raise HTTPException(404, "Batch not found")
    s = batch_state(b)
    return {"code": b.code, "vaccine": b.vaccine, "expiry": b.expiry, "status": s["status"],
            "expired": b.expiry < time.strftime("%Y-%m-%d")}

# ---------- audit ----------
@app.get("/api/audits")
def audits(_=Depends(roles("admin", "inspector")), db: Session = Depends(database.get_db)):
    return db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(200).all()

@app.get("/api/audits/verify")
def verify(_=Depends(roles("admin", "inspector")), db: Session = Depends(database.get_db)):
    return audit.verify_chain(db)