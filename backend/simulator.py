"""Fake ESP32. python backend/simulator.py [fridge-1|fridge-2] [hot] [door]
'hot' pushes temperature above 12C to test the heat budget; 'door' holds the door open past
the 60-second alert.
API_BASE=https://your-api.onrender.com python backend/simulator.py   # drive a deployed backend
The key is read by app.hmac_auth, so set HMAC_SECRET_KEY identically here and on the server.
Compressor follows the Task 1 rule: ON at 7C, OFF at 3C, never restarting within 60 seconds."""
import os, sys, time, uuid, random, requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.hmac_auth import canonical, sign

API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
dev = sys.argv[1] if len(sys.argv) > 1 else "fridge-1"
hot, door = "hot" in sys.argv, "door" in sys.argv
MIN_OFF_S = 60          # Task 1: compressor must stay off at least this long between runs
t, comp_on, off_since = 5.0, False, 0.0
while True:
    t += random.uniform(-.3, .3) + (0.4 if hot and t < 14 else 0)
    ts, nonce = round(time.time(), 2), uuid.uuid4().hex
    if comp_on:
        if t <= 3:
            comp_on, off_since = False, ts
    elif t >= 7 and ts - off_since >= MIN_OFF_S:
        comp_on = True
    body = dict(device_id=dev, temperature=round(t, 1), door_open=door, ts=ts, nonce=nonce,
                compressor_on=comp_on, power_ok=True, battery=100.0)
    body["signature"] = sign(canonical(dev, body["temperature"], door, ts, nonce, body["power_ok"], body["battery"], body["compressor_on"]))
    try:
        r = requests.post(f"{API}/api/sensor", json=body, timeout=30)
        print(r.status_code, body["temperature"], "comp:on" if comp_on else "comp:off",
              r.json().get("batch_status", ""), "" if r.ok else r.text[:120])
    except requests.RequestException as x:
        # A free instance wakes slowly; keep signing the next reading instead of dying mid-demo.
        print("ingest failed:", type(x).__name__, str(x)[:120])
    time.sleep(5)
