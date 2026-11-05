"""Fake ESP32. python backend/simulator.py [fridge-1|fridge-2] [hot] [door] [weak] [powerfail]
'hot' pushes temperature above 12C to test the heat budget; 'door' holds the door open past
the 60-second alert; 'weak' runs a tired compressor that keeps its pull but loses its duty cycle;
'powerfail' drops the mains for 45 seconds every 105 so power_ok and the battery move together.
API_BASE=https://your-api.onrender.com python backend/simulator.py   # drive a deployed backend
The key is read by app.hmac_auth, so set HMAC_SECRET_KEY identically here and on the server. That
makes this node a fleet-key node - the two seeded fridges. A node registered through the web app signs
with its own issued key and this simulator cannot imitate it.
Compressor follows the Task 1 rule: ON at 7C, OFF at 3C, never restarting within 60 seconds.
The box itself is a leak toward the room plus the compressor's pull, so 'weak' and 'powerfail' are
states the temperature can actually show; a random walk could not tell a failing unit from a quiet day."""
import os, sys, time, uuid, random, requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.hmac_auth import canonical, sign

API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
dev = sys.argv[1] if len(sys.argv) > 1 else "fridge-1"
hot, door = "hot" in sys.argv, "door" in sys.argv
weak, powerfail = "weak" in sys.argv, "powerfail" in sys.argv
MIN_OFF_S = 60          # Task 1: compressor must stay off at least this long between runs
TICK_S = 5
LEAK = 0.03             # C per tick toward the room: 0.51 at 5C in a 22C room
PULL = 1.1 * (0.35 if hot else 1.0) * (0.45 if weak else 1.0)
AMBIENT = 30.0 if hot else 22.0     # a hot room and an undersized unit is what gets past 12C
# ticks: four healthy, then 45 s out and 60 s back. Fast because 'powerfail' exists so the supply
# alert and the battery arc are visible inside one demo, not because a ward loses power that often.
OUT_START, OUT_ON, OUT_OFF = 5, 9, 12

t, comp_on, off_since, battery = 5.0, False, 0.0, 100.0
tick = 0
while True:
    tick += 1
    ts, nonce = round(time.time(), 2), uuid.uuid4().hex
    # the supply first, because it decides whether the compressor is even allowed to run
    pos = tick - OUT_START
    power_ok = not (powerfail and pos >= 0 and pos % (OUT_ON + OUT_OFF) < OUT_ON)
    battery = min(100.0, battery + 0.12) if power_ok else max(5.0, battery - 0.15)
    if comp_on and not power_ok:
        comp_on, off_since = False, ts
    if comp_on:
        if t <= 3:
            comp_on, off_since = False, ts
    elif t >= 7 and power_ok and ts - off_since >= MIN_OFF_S:
        comp_on = True
    drift = (AMBIENT - t) * LEAK + (0.6 if door else 0) + (0.3 if not power_ok else 0)
    t += random.uniform(-.3, .3) + drift - (PULL if comp_on else 0)
    body = dict(device_id=dev, temperature=round(t, 1), door_open=door, ts=ts, nonce=nonce,
                compressor_on=comp_on, power_ok=power_ok, battery=round(battery, 1), buffered=False)
    body["signature"] = sign(canonical(dev, body["temperature"], door, ts, nonce, body["power_ok"],
                                        body["battery"], comp_on, body["buffered"]))
    try:
        r = requests.post(f"{API}/api/sensor", json=body, timeout=30)
        print(r.status_code, body["temperature"], "comp:on" if comp_on else "comp:off",
              "" if power_ok else "POWER:off", f"batt:{body['battery']}" if body["battery"] < 100 else "",
              r.json().get("batch_status", ""), "" if r.ok else r.text[:120])
    except requests.RequestException as x:
        # A free instance wakes slowly; keep signing the next reading instead of dying mid-demo.
        print("ingest failed:", type(x).__name__, str(x)[:120])
    time.sleep(TICK_S)
