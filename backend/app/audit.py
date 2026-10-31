from sqlalchemy.orm import Session
from app.models import AuditLog
import hashlib

def verify_audit_chain(db: Session) -> bool:
    """
    অডিট লগের হ্যাশ-চেইনিং (Hash-chaining) এবং আগের ও বর্তমান হ্যাশের সঠিকতা যাচাই করে।
    """
    logs = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    prev_hash = "0" * 64

    for log in logs:
        # লগে সংরক্ষিত previous_hash রিয়েল চেইনের সাথে মিলছে কিনা চেক করা
        if log.previous_hash != prev_hash:
            return False
            
        # মডেলের ফিল্ডগুলোর সাথে মিলিয়ে প্রত্যাশিত হ্যাশ কন্টেন্ট তৈরি করা
        expected_content = f"{log.previous_hash}{log.action}{log.event_data}{log.timestamp}"
        expected_hash = hashlib.sha256(expected_content.encode()).hexdigest()
        
        # current_hash ঠিক আছে কিনা যাচাই করা
        if log.current_hash != expected_hash:
            return False
            
        prev_hash = log.current_hash
        
    return True