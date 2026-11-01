"""Task 4 acceptance smoke test.

Run it against a SCRATCH server so your demo database stays clean:

    mkdir scratch && cd scratch
    set PYTHONPATH=<repo>/backend
    <repo>/backend/venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
    <repo>/backend/venv/Scripts/python.exe <repo>/scripts/smoke_test.py

Add --db <path> to also prove the hash chain detects an edited record. That leaves the
database permanently flagged as tampered, so never point it at a demo database.
"""
import argparse, os, sys, time, uuid, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import requests
from app import hmac_auth

p = argparse.ArgumentParser()
p.add_argument("--url", default=os.getenv("API_URL", "http://127.0.0.1:8000"))
p.add_argument("--db", default=None, help="SQLite file, to demo tamper detection")
a = p.parse_args()
BASE, ok, bad = a.url.rstrip("/"), [], []


def check(name, cond, detail=""):
    (ok if cond else bad).append(name)
    print(f"{'PASS' if cond else 'FAIL':5} {name}" + (f" -> {detail}" if detail else ""))


def send(device, t, ts=None, door=False, buffered=False, **over):
    ts = round(ts if ts is not None else time.time(), 2)
    nonce = over.pop("nonce", uuid.uuid4().hex)
    body = dict(device_id=device, temperature=t, door_open=door, ts=ts, nonce=nonce,
                power_ok=True, battery=100.0, compressor_on=False, buffered=buffered, **over)
    body["signature"] = hmac_auth.sign(hmac_auth.canonical(
        body["device_id"], t, door, ts, nonce, body["power_ok"], body["battery"], body["compressor_on"]))
    return requests.post(f"{BASE}/api/sensor", json=body)


def batch(code):
    return next(b for b in requests.get(f"{BASE}/api/batches", headers=H["admin"]).json() if b["code"] == code)


print(f"\n== ColdChain smoke test against {BASE} ==\n")

# 1. Auth & Roles -- JWT + bcrypt, permissions enforced on the server
tok = {}
for role in ("admin", "pharmacist", "inspector"):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": role, "password": f"{role}123"})
    check(f"login {role}", r.status_code == 200 and r.json().get("token"), r.text[:80])
    tok[role] = r.json().get("token", "")
H = {k: {"Authorization": f"Bearer {v}"} for k, v in tok.items()}
check("wrong password rejected", requests.post(f"{BASE}/api/auth/login",
      json={"username": "admin", "password": "x"}).status_code == 401)
check("missing token rejected", requests.get(f"{BASE}/api/dashboard").status_code in (401, 403))
check("bad token rejected", requests.get(f"{BASE}/api/dashboard",
      headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401)
code = "SMOKE-" + uuid.uuid4().hex[:6]
check("inspector cannot add batches", requests.post(f"{BASE}/api/batches",
      json={"code": code, "vaccine": "X", "expiry": "2027-01-01"}, headers=H["inspector"]).status_code == 403)
check("pharmacist cannot admin-reset", requests.post(f"{BASE}/api/batches/1/reset",
      headers=H["pharmacist"]).status_code == 403)

# 2. Heat-exposure budget -- replayed offline readings, >12C counts double.
#    Runs first because the readings are deliberately back-dated.
base = time.time() - 1300
before = batch("VAX-001")["remaining_min"]
send("fridge-1", 5.0, ts=base, buffered=True)
check("10 min at 13C spends 20 of the 60 budget-minutes",
      send("fridge-1", 13.0, ts=base + 600, buffered=True).status_code == 201)
spent = before - batch("VAX-001")["remaining_min"]
check("double-weighted exposure recorded", abs(spent - 20.0) < 0.2, f"spent {round(spent, 2)} min")
check("status reported", batch("VAX-001")["status"] in ("Safe", "At Risk", "Discard"), batch("VAX-001")["status"])

# 3. Device security -- HMAC-SHA256 + timestamp + nonce; rejects are logged
check("valid signed reading accepted", send("fridge-1", 5.0).status_code == 201)
ts = round(time.time(), 2)
forged = dict(device_id="fridge-1", temperature=30.0, door_open=False, ts=ts, nonce=uuid.uuid4().hex,
              power_ok=True, battery=100.0, compressor_on=False)
forged["signature"] = hmac_auth.sign(hmac_auth.canonical(
    "fridge-1", 5.0, False, ts, forged["nonce"], True, 100.0, False))   # signed for 5.0C
check("temperature changed after signing rejected",
      requests.post(f"{BASE}/api/sensor", json=forged).status_code == 401)
check("stale timestamp rejected", send("fridge-1", 5.0, ts=time.time() - 900).status_code == 401)
n = uuid.uuid4().hex
send("fridge-2", 5.0, nonce=n)
check("replayed nonce rejected", send("fridge-2", 5.0, nonce=n).status_code == 401)
check("unsigned reading rejected", requests.post(f"{BASE}/api/sensor", json={**forged, "signature": ""}).status_code == 401)
check("unknown device rejected", send("fridge-99", 5.0).status_code == 401)
rejected = [l for l in requests.get(f"{BASE}/api/audits", headers=H["admin"]).json()
            if l["action"] == "MESSAGE_REJECTED"]
check("rejections written to the audit log", len(rejected) >= 4, f"{len(rejected)} MESSAGE_REJECTED rows")

# 4. Live dashboard payload the UI renders
d = requests.get(f"{BASE}/api/dashboard", headers=H["admin"]).json()
need = {"temperature", "status", "door_open", "power_ok", "compressor_on", "battery", "history", "batches", "online"}
check("dashboard exposes temp/door/power/compressor/budget", d and need <= set(d[0]), f"missing {need - set(d[0])}")

# 5. Live device view -- what the /live tab needs to follow a real node
check("devices need a token", requests.get(f"{BASE}/api/devices").status_code in (401, 403))
check("pharmacist cannot register a node", requests.post(f"{BASE}/api/devices",
      json={"name": "x", "device_id": "smoke-node"}, headers=H["pharmacist"]).status_code == 403)
node = requests.post(f"{BASE}/api/devices", json={"name": "Smoke node", "device_id": "smoke-node"},
                     headers=H["admin"])
check("admin registers a node and gets its topics back",
      node.status_code == 201 and node.json().get("topic") == "coldchain/smoke-node/reading", node.text[:80])
check("a duplicate id is refused", requests.post(f"{BASE}/api/devices", json={"name": "x",
      "device_id": "smoke-node"}, headers=H["admin"]).status_code == 409)
check("an id that cannot be a topic is refused", requests.post(f"{BASE}/api/devices",
      json={"name": "x", "device_id": "bad id!"}, headers=H["admin"]).status_code == 422)
check("a never-reported node has no temperature, not a default one",
      next(d for d in requests.get(f"{BASE}/api/devices", headers=H["admin"]).json()["devices"]
           if d["device_id"] == "smoke-node")["temperature"] is None)
send("smoke-node", 6.5)
rows = requests.get(f"{BASE}/api/readings", params={"device_id": "smoke-node"}, headers=H["admin"]).json()
check("readings come back oldest first with arrival and buffer flags",
      len(rows) == 1 and {"ts", "received_ts", "buffered", "temperature"} <= set(rows[0])
      and abs(rows[0]["received_ts"] - time.time()) < 60, str(rows)[:120])
send("smoke-node", 6.6, ts=time.time() - 4 * 3600, buffered=True)   # past the 3 h replay window
live = next(d for d in requests.get(f"{BASE}/api/devices", headers=H["admin"]).json()["devices"]
            if d["device_id"] == "smoke-node")
check("rejections are counted and explained per device",
      live["rejects"] >= 1 and "stale timestamp" in live["reasons"], str(live["reasons"]))
check("an unregistered id is listed for the operator",
      any(u["device_id"] == "fridge-99" for u in
          requests.get(f"{BASE}/api/devices", headers=H["admin"]).json()["unknown"]))
gone = requests.delete(f"{BASE}/api/devices/{live['id']}", headers=H["admin"])
check("unregistering a node takes its readings with it",
      gone.status_code == 200 and gone.json().get("readings_deleted") == 1
      and not requests.get(f"{BASE}/api/readings", params={"device_id": "smoke-node"},
                           headers=H["admin"]).json(), str(gone.text)[:80])

# 6. Inventory -- create, validate, move
check("pharmacist creates a batch", requests.post(f"{BASE}/api/batches",
      json={"code": code, "vaccine": "Insulin", "expiry": "2027-12-31", "fridge_id": 2},
      headers=H["pharmacist"]).status_code == 201)
r = requests.post(f"{BASE}/api/batches", json={"code": code + "-BAD", "vaccine": "X",
                  "expiry": "31/12/2027"}, headers=H["pharmacist"])
det = r.json().get("detail")
check("malformed expiry rejected with a readable message",
      r.status_code == 422 and isinstance(det, str) and det.startswith("Expiry must be"), str(det))
bid = batch(code)["id"]
check("batch moved between fridges", requests.put(f"{BASE}/api/batches/{bid}/move",
      json={"fridge_id": 1}, headers=H["pharmacist"]).status_code == 200)

# 7. Public QR check -- no login
r = requests.get(f"{BASE}/api/public/batch/{code}")
check("public status without login", r.status_code == 200 and {"status", "expiry", "expired"} <= set(r.json()), r.text[:120])
check("unknown code -> 404", requests.get(f"{BASE}/api/public/batch/NO-SUCH").status_code == 404)

# 8. Tamper-evident log
v = requests.get(f"{BASE}/api/audits/verify", headers=H["admin"])
check("chain verifies", v.json().get("valid") is True, v.text[:120])
check("inspector may verify", requests.get(f"{BASE}/api/audits/verify", headers=H["inspector"]).status_code == 200)
if a.db:
    con = sqlite3.connect(a.db)
    row = con.execute("select id, details from audit_logs order by id limit 1").fetchone()
    con.execute("update audit_logs set details = ? where id = ?", ("edited after the fact", row[0]))
    con.commit(); con.close()
    v2 = requests.get(f"{BASE}/api/audits/verify", headers=H["admin"]).json()
    check("editing a record is detected", v2["valid"] is False and v2["broken_at"] == row[0], str(v2))

print(f"\n== {len(ok)} passed, {len(bad)} failed ==")
for b in bad:
    print("FAILED:", b)
sys.exit(1 if bad else 0)
