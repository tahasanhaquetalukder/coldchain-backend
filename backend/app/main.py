from datetime import date, datetime, timezone
import time


@app.get("/api/public/batch/{code}")
def public_batch(code: str, db: Session = Depends(database.get_db)):
    batch = db.query(models.Batch).filter_by(code=code).first()
    if batch is None:
        raise HTTPException(404, "Batch not found")

    state = batch_state(batch)
    today_utc = datetime.now(timezone.utc).date()
    try:
        if isinstance(batch.expiry, datetime):
            expiry_date = batch.expiry.date()
        elif isinstance(batch.expiry, date):
            expiry_date = batch.expiry
        else:
            expiry_date = date.fromisoformat(batch.expiry)
    except (TypeError, ValueError):
        raise HTTPException(500, "Invalid batch expiry date")

    return {
        "code": batch.code,
        "vaccine": batch.vaccine,
        "expiry": batch.expiry,
        "status": state["status"],
        "expired": expiry_date < today_utc,
    }


def cleanup_old_nonces(db: Session):
    """Delete nonce records older than 24 hours."""
    threshold_time = time.time() - 86400
    deleted_count = (
        db.query(models.Nonce)
        .filter(models.Nonce.ts < threshold_time)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count