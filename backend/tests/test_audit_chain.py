"""The audit chain: what it proves, and the two attacks it has to catch.

One of those attacks is our own concurrency: two writers that both read the head before either
inserts fork the chain, and the operator sees "tampering detected" for something the server did.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from app import audit, database, models
from conftest import audit_rows, rows

FIELDS = {"id", "action", "details", "previous_hash", "current_hash", "timestamp"}


def audit_row(audit_id):
    def q(s):
        l = s.query(models.AuditLog).filter_by(id=audit_id).one()
        return (l.id, l.action, l.details, l.previous_hash, l.current_hash, l.timestamp)
    return rows(q)


def last_audit():
    def q(s):
        l = s.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
        return (l.id, l.action, l.details, l.previous_hash, l.current_hash, l.timestamp)
    return rows(q)


def edit_audit(audit_id, **columns):
    def q(s):
        s.query(models.AuditLog).filter_by(id=audit_id).update(columns)
        s.commit()
    return rows(q)


def delete_audit(audit_id):
    def q(s):
        s.query(models.AuditLog).filter_by(id=audit_id).delete()
        s.commit()
    return rows(q)


def reinsert(row):
    """Put a deleted record back byte-for-byte, id included - SQLite would otherwise reuse the tail id."""
    def q(s):
        s.add(models.AuditLog(id=row[0], action=row[1], details=row[2], previous_hash=row[3],
                              current_hash=row[4], timestamp=row[5]))
        s.commit()
    return rows(q)


def verify(client, tok):
    return client.get("/api/audits/verify", headers=tok["admin"]).json()


def test_the_chain_is_intact_after_normal_use(client, tok):
    v = verify(client, tok)
    assert v["valid"] is True and v["broken_at"] is None
    assert v["checked"] >= 1 and len(v["head"]) == 64


def test_audits_come_back_as_named_fields_newest_first(client, tok):
    body = client.get("/api/audits", headers=tok["admin"]).json()
    assert 0 < len(body) <= 200
    assert all(set(l) == FIELDS for l in body)
    assert [l["id"] for l in body] == sorted([l["id"] for l in body], reverse=True)
    # naive UTC, exactly as it was hashed: an offset would print a different hour than the record
    # verify_chain recomputes over, and every row would then read as tampered
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?", body[0]["timestamp"])
    assert len(body[0]["current_hash"]) == 64 and len(body[0]["previous_hash"]) == 64


def test_editing_one_record_names_the_record(client, tok):
    seed = audit_rows("SEED")[0]
    edit_audit(seed[0], details="someone moved the cheese")
    v = verify(client, tok)
    assert v["valid"] is False and v["broken_at"] == seed[0]
    assert v["reason"] == "record edited or chain broken"

    edit_audit(seed[0], details=seed[1])
    assert verify(client, tok)["valid"] is True


def test_deleting_the_newest_record_is_caught_by_the_anchor(client, tok):
    """The chain alone cannot see its own tail being cut off - the newest hash has nothing to point at.

    That is what the anchor file outside the database is for.
    """
    row = last_audit()
    delete_audit(row[0])
    v = verify(client, tok)
    assert v["valid"] is False and v["reason"] == "newest records were deleted"
    assert v["broken_at"] == row[0]

    reinsert(row)
    assert verify(client, tok)["valid"] is True


def test_removing_a_middle_record_breaks_the_next_links_hash(client, tok):
    """Write three rows, cut out the middle one: the tail still points at a record that is gone."""
    s = database.SessionLocal()
    ids = []
    for n in ("one", "two", "three"):
        ids.append(audit.create_audit_log(s, "GAP", f"row {n}").id)
    s.close()

    victim = audit_row(ids[1])
    delete_audit(ids[1])
    v = verify(client, tok)
    assert v["valid"] is False, "dropping a record re-parents the one after it"
    assert v["broken_at"] == ids[2], "the break is reported at the row whose previous hash no longer matches"

    reinsert(victim)
    assert verify(client, tok)["valid"] is True


def test_fifty_concurrent_writers_still_make_one_chain(client, tok):
    """The chain is a read-modify-write, so it needs serialising or it forks under real traffic."""
    before = rows(lambda s: s.query(models.AuditLog).count())

    def write(n):
        s = database.SessionLocal()
        try:
            audit.create_audit_log(s, "CONCURRENCY", f"writer {n}")
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(write, range(50)))

    assert rows(lambda s: s.query(models.AuditLog).count()) == before + 50
    v = verify(client, tok)
    assert v["valid"] is True, "50 rows, one unbroken chain - the lock is doing its job"
    assert v["checked"] == before + 50
    writers = audit_rows("CONCURRENCY")
    assert len(writers) == 50 and len({w[1] for w in writers}) == 50


def test_the_head_hash_is_the_last_records_hash(client, tok):
    assert verify(client, tok)["head"] == last_audit()[4]
