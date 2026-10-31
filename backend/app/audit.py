import hashlib, os
from datetime import datetime
from sqlalchemy.orm import Session
from . import models

GENESIS = "0" * 64
ANCHOR = os.getenv("AUDIT_ANCHOR", "audit_anchor.log")  # keep outside the DB (ideally on another disk/host)

def calculate_hash(prev: str, action: str, details: str, ts: str) -> str:
    return hashlib.sha256(f"{prev}|{action}|{details}|{ts}".encode()).hexdigest()

def create_audit_log(db: Session, action: str, details: str):
    last = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
    prev = last.current_hash if last else GENESIS
    now = datetime.utcnow()
    log = models.AuditLog(action=action, details=details, timestamp=now, previous_hash=prev,
                          current_hash=calculate_hash(prev, action, details, now.isoformat()))
    db.add(log); db.commit(); db.refresh(log)
    with open(ANCHOR, "a") as f:   # head anchor: catches deletion of the newest records
        f.write(f"{log.id} {log.current_hash}\n")
    return log

def verify_chain(db: Session):
    prev, logs = GENESIS, db.query(models.AuditLog).order_by(models.AuditLog.id).all()
    for l in logs:
        if l.previous_hash != prev or l.current_hash != calculate_hash(prev, l.action, l.details, l.timestamp.isoformat()):
            return {"valid": False, "broken_at": l.id, "checked": len(logs), "reason": "record edited or chain broken"}
        prev = l.current_hash
    try:
        anchor = open(ANCHOR).read().split()[-2:]
    except Exception:
        anchor = None
    if anchor and (not logs or str(logs[-1].id) != anchor[0] or logs[-1].current_hash != anchor[1]):
        return {"valid": False, "broken_at": int(anchor[0]), "checked": len(logs), "reason": "newest records were deleted"}
    return {"valid": True, "broken_at": None, "checked": len(logs), "head": prev}