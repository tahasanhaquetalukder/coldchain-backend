import hashlib
from sqlalchemy.orm import Session
from . import models

def calculate_hash(previous_hash: str, action: str, details: str) -> str:
    """ব্লকচেইন স্টাইলের হ্যাশ-চেইনিং লজিক যা ডাটা টেম্পারিং প্রতিরোধ করে"""
    value_string = f"{previous_hash}{action}{details}"
    return hashlib.sha256(value_string.encode('utf-8')).hexdigest()

def create_audit_log(db: Session, action: str, details: str):
    last_log = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
    
    prev_hash = last_log.current_hash if last_log else "0" * 64
    curr_hash = calculate_hash(prev_hash, action, details)

    new_log = models.AuditLog(
        action=action,
        details=details,
        previous_hash=prev_hash,
        current_hash=curr_hash
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return new_log