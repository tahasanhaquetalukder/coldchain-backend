"""Test harness for the ColdChain backend.

Everything the app reads once at import time - the database URL, the two secrets, the audit anchor
path - has to be in the environment BEFORE app.main is imported, or the real coldchain.db and the
real anchor file get written to. Hence the env block above the imports.
"""
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # so `app` imports from backend/

_TMP = Path(tempfile.mkdtemp(prefix="coldchain-pytest-")).as_posix()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["AUDIT_ANCHOR"] = f"{_TMP}/anchor.log"
os.environ["ENV"] = "development"
os.environ["HMAC_SECRET_KEY"] = "test-fleet-key"
# 32 bytes or pyjwt prints an InsecureKeyLengthWarning on every encode and decode, and the noise
# hides the warnings worth reading. A real deployment has no default here at all.
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app import database, hmac_auth, main, models  # noqa: E402

# 50 concurrent audit writers all queue on _CHAIN_LOCK; SQLite still needs patience to hand the
# file over, and its 5 s default makes a flaky test rather than a bug in the code under test.
@event.listens_for(database.engine, "connect")
def _busy_timeout(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA busy_timeout=15000")
    cur.close()


@pytest.fixture(scope="session", autouse=True)
def _scratch_dir():
    """Delete this run's database and anchor when it ends.

    Every run makes a new temp dir, and twelve of them left on disk is a leak that outlives the
    suite. SQLite on Windows will not let a file go while a pooled connection still holds it, so the
    engine has to be disposed first - hence this cannot be a plain atexit hook.
    """
    yield
    database.engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    # The context manager runs the lifespan, which is what seeds the demo users, fridges and batches.
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def tok(client):
    """A Bearer header per role, minted with the documented demo passwords."""
    out = {}
    for role in ("admin", "pharmacist", "inspector"):
        r = client.post("/api/auth/login", json={"username": role, "password": f"{role}123"})
        assert r.status_code == 200, r.text
        out[role] = {"Authorization": f"Bearer {r.json()['token']}"}
    return out


@pytest.fixture(autouse=True)
def clear_reject_throttle():
    """The throttle state is process-global and keyed by (device, reason); without this, one test's
    flood silences the next test's rejection log and every "one row was written" assertion lies."""
    main._REJECT_SEEN.clear()
    yield
    main._REJECT_SEEN.clear()


# Every reader below opens its own session and closes it. A session kept open across an API call
# would hold a SQLite read transaction, and in a rollback-journal database a reader is what stops
# the server's writer from committing at all - the test would hang instead of failing.
def rows(query):
    """Run a query in a session that is gone before this returns; gives back plain tuples."""
    s = database.SessionLocal()
    try:
        return query(s)
    finally:
        s.close()


def now():
    return round(time.time(), 2)


def audit_rows(action, contains=None):
    def q(s):
        query = s.query(models.AuditLog).filter(models.AuditLog.action == action)
        if contains:
            query = query.filter(models.AuditLog.details.contains(contains))
        return [(l.id, l.details, l.timestamp) for l in query.order_by(models.AuditLog.id)]
    return rows(q)


def readings_of(device_id):
    def q(s):
        return [(r.ts, r.temperature, bool(r.buffered), r.received_ts)
                for r in s.query(models.Reading).filter_by(device_id=device_id)
                        .order_by(models.Reading.id).all()]
    return rows(q)


def reading_flags(device_id):
    """The two fields Task 5 added to the trace: (ts, compressor_on, power_ok), NULL left as NULL.

    A separate reader because readings_of() unpacks four values in tests that predate Task 5, and a
    widening there would be a change of shape for nothing.
    """
    def q(s):
        return [(r.ts, r.compressor_on, r.power_ok)
                for r in s.query(models.Reading).filter_by(device_id=device_id)
                        .order_by(models.Reading.id).all()]
    return rows(q)


def set_batch_minutes(code, minutes):
    def q(s):
        s.query(models.Batch).filter_by(code=code).update({"used_minutes": minutes})
        s.commit()
    return rows(q)


def set_fridge(device_id, **columns):
    """Rewrite a node row directly. Only for the few fields no endpoint can set (last_ts)."""
    def q(s):
        s.query(models.Fridge).filter_by(device_id=device_id).update(columns)
        s.commit()
    return rows(q)


def fridge_field(device_id, column):
    return rows(lambda s: getattr(s.query(models.Fridge).filter_by(device_id=device_id).one(), column))


# the two defaults a node sends for fields a test does not care about
DEFAULTS = dict(power_ok=True, battery=100.0, compressor_on=False)


def reading(device_id, temperature, ts=None, door=False, buffered=False, key=None, nonce=None, **over):
    """A signed /api/sensor body, exactly as firmware would send it.

    The signature covers the canonical string, so the values put in the JSON must be the values that
    were signed - same floats, same rounding. `key` is a node's own hmac_key; None means the shared
    fleet secret, which is what the two seeded fridges still use.
    """
    ts = ts if ts is not None else now()
    nonce = nonce or uuid.uuid4().hex
    body = dict(device_id=device_id, temperature=temperature, door_open=door, ts=ts, nonce=nonce,
                buffered=buffered, **{**DEFAULTS, **over})
    body["signature"] = hmac_auth.sign(
        hmac_auth.canonical(device_id, temperature, door, ts, nonce, body["power_ok"],
                            body["battery"], body["compressor_on"], buffered), key)
    return body


def send(client, device_id, temperature, ts=None, **kw):
    return client.post("/api/sensor", json=reading(device_id, temperature, ts, **kw))


def register(client, admin, name="test node"):
    """Register a node and return (fridge_id, device_id, hmac_key) - what the firmware gets handed."""
    device_id = f"node-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/devices", json={"name": name, "device_id": device_id}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["id"], device_id, r.json()["hmac_key"]


def node(client, admin, code, name="test node"):
    """A node and a batch of its own, so nothing another test feeds the API can move these numbers."""
    fid, device_id, key = register(client, admin, name=name)
    add_batch(client, admin, code, fid)
    return fid, device_id, key


def add_batch(client, admin, code, fridge_id, vaccine="Test Vaccine", expiry="2030-01-01"):
    r = client.post("/api/batches",
                    json={"code": code, "vaccine": vaccine, "expiry": expiry, "fridge_id": fridge_id},
                    headers=admin)
    assert r.status_code == 201, r.text


def budget(client, admin, code):
    return next(b for b in client.get("/api/batches", headers=admin).json() if b["code"] == code)
