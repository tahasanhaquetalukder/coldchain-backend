from datetime import datetime, timezone
import hashlib, os
from sqlalchemy.orm import Session
from . import models

GENESIS = "0" * 64
ANCHOR = os.getenv("AUDIT_ANCHOR", "audit_anchor.log")

def calculate_hash(prev: str, action: str, details: str, ts: str) -> str:
    return hashlib.sha256(f"{prev}|{action}|{details}|{ts}".encode()).hexdigest()

def create_audit_log(db: Session, action: str, details: str):
    last = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
    prev = last.current_hash if last else GENESIS
    
    # সঠিক এবং আধুনিক ইউটিসি টাইমস্ট্যাম্প ব্যবহার
    now = datetime.now(timezone.utc)
    
    log = models.AuditLog(
        action=action, 
        details=details, 
        timestamp=now, 
        previous_hash=prev,
        current_hash=calculate_hash(prev, action, details, now.isoformat())
    )
    db.add(log); db.commit(); db.refresh(log)
    with open(ANCHOR, "a") as f:
        f.write(f"{log.id} {log.current_hash}\n")
    return log