"""Fake ESP32. Run from project root: python simulator.py [fridge-1|fridge-2] [hot]
Positional 'hot' pushes temperature above 12C to test the heat budget."""
import sys, time, uuid, random, requests
from backend.hmac_auth import canonical, sign
dev = sys.argv[1] if len(sys.argv) > 1 else "fridge-1"; hot = "hot" in sys.argv
t = 5.0
while True:
    t += random.uniform(-.3, .3) + (0.4 if hot and t < 14 else 0)
    ts, nonce, door = round(time.time(), 2), uuid.uuid4().hex, False
    body = dict(device_id=dev, temperature=round(t, 1), door_open=door, ts=ts, nonce=nonce,
                compressor_on=t > 7, power_ok=True, battery=100)
    body["signature"] = sign(canonical(dev, body["temperature"], door, ts, nonce, body["power_ok"], body["battery"], body["compressor_on"]))
    print(requests.post("http://127.0.0.1:8000/api/sensor", json=body).status_code, body["temperature"])
    time.sleep(5)