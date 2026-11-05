"""A repeatable live demo for Task 5: python backend/scripts/demo_task5.py

Leaves a running backend in the one state where all three AI answers are non-empty at the same time:
a forecast that says a fridge is on its way over 8 C, a compressor health score on that fridge that has
visibly fallen, and a relocation plan that names a batch and a destination for it. Then it prints those
three answers and stops - the numbers on the screen are the ones the routes are serving right now.

Two nodes are used, because a suggestion needs somewhere to go:

    demo-warm-1   "Demo ward (dying)"  cools normally for four cycles, then slowly for three more,
                                       then stops cutting in and creeps up toward the line
    demo-cold-1   "Demo cold room"     cycles healthily and ends mid-cool, so it qualifies as a
                                       destination instead of merely being the other box

Two batches live in the warm one, least-remaining-budget first is what the plan ranks on.

Everything comes from environment variables, because the one thing a demo script must never do is carry
a secret:

    API_BASE       where the backend is (default http://127.0.0.1:8000)
    DEMO_USERNAME  who to sign in as (default admin; must be able to register devices and batches)
    DEMO_PASSWORD  that account's password, required, never printed

Readings are written the way a node whose Wi-Fi dropped writes them: signed with that node's own key,
buffered=True, oldest first, one a minute. Two ingest rules decide the shape of this script:

  - anything at or before the device's newest stored timestamp is ignored, so the whole trace has to be
    written before the live packet that would otherwise advance it, and
  - a buffered packet is only accepted inside the 3-hour buffer window, so the traces below are under
    160 minutes long and no longer.

Safe to run twice, but not by rewriting history: a rerun cannot re-send the minutes it already sent, so
it reads each node's newest stored timestamp and temperature and appends only the gap up to now,
continuing the same trace from where it stopped. That is why the warm node creeps toward but never past
DEMO_TOP_C: every rerun leaves it just under the line, still rising, still a prediction rather than an
alarm that already happened.

It never confirms a move - that click is the thing being demonstrated.
"""
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # backend/
from app.hmac_auth import canonical, sign   # noqa: E402  (the simulator's own signing path)

API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
USER = os.getenv("DEMO_USERNAME", "admin")
PASSWORD = os.getenv("DEMO_PASSWORD")

COLD_ID, WARM_ID = "demo-cold-1", "demo-warm-1"
BATCHES = [("DEMO-A01", "Pfizer RDT", "2027-03-01"), ("DEMO-A02", "AstraZeneca", "2026-12-15")]

# Task 1's own rule, so the trace is a fridge and not a curve: ON at 7 C, OFF at 3 C.
CUT_IN_C, CUT_OUT_C = 7.0, 3.0
WARM_C_PER_MIN = 0.5    # coasting between runs: 3 C to 7 C in eight minutes
PULL_HEALTHY = 0.8      # a unit that empties 4 C in five minutes of running
PULL_SLOW = 0.22        # the same unit later: eighteen minutes for the same 4 C
HEALTHY_CYCLES, SLOW_CYCLES = 4, 3
COLD_CYCLES = 11          # ~143 minutes: long enough for a health score of its own, short of the window
BUFFER_LIMIT_MIN = 170    # BUFFER_WINDOW on the server is 3 h of buffered packets; this is the margin
STALL_C_PER_MIN = 0.26  # slower than the normal coast: the fault is that it never cuts in again
STALL_MINUTES = 18
DEMO_TOP_C = 7.9        # the warm node is kept under the line: this demo is about the prediction
IGNORED = "duplicate-ignored"


def login():
    if not PASSWORD:
        raise SystemExit("DEMO_PASSWORD is not set. The script will not carry a password for you, even a "
                         "demo one: set it and run again.")
    r = requests.post(f"{API}/api/auth/login", json={"username": USER, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"sign-in as {USER!r} at {API} failed with {r.status_code}: {r.text}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def devices(hdr):
    r = requests.get(f"{API}/api/devices", headers=hdr, timeout=30)
    r.raise_for_status()
    return {d["device_id"]: d for d in r.json()["devices"]}


def ensure_device(hdr, name, device_id):
    """Register the node, or rotate its key if it already exists, and return (fridge_id, key).

    A key is only ever handed out by those two calls, so a rerun cannot read back the one it used last
    time and has to issue a new one. That is the app's own rule - the old key stops working on the next
    packet - and the script follows it instead of stashing the secret somewhere it should not be.
    """
    r = requests.post(f"{API}/api/devices", json={"name": name, "device_id": device_id},
                      headers=hdr, timeout=30)
    if r.status_code == 201:
        return r.json()["id"], r.json()["hmac_key"]
    if r.status_code != 409:
        raise SystemExit(f"registering {device_id} failed with {r.status_code}: {r.text}")
    fid = devices(hdr)[device_id]["id"]
    return fid, requests.post(f"{API}/api/devices/{fid}/key", headers=hdr, timeout=30).json()["hmac_key"]


def ensure_batch(hdr, code, vaccine, expiry, fridge_id):
    """Create the batch in that fridge, or move the one that is already there back into it."""
    r = requests.post(f"{API}/api/batches", json={"code": code, "vaccine": vaccine, "expiry": expiry,
                                                  "fridge_id": fridge_id}, headers=hdr, timeout=30)
    if r.status_code in (200, 201):
        return "created"
    bid = next((b["id"] for b in requests.get(f"{API}/api/batches", headers=hdr,
                                              timeout=30).json() if b["code"] == code), None)
    if bid is None:
        raise SystemExit(f"{code} could not be created ({r.status_code}: {r.text}) and is not listed either")
    requests.put(f"{API}/api/batches/{bid}/move", json={"fridge_id": fridge_id},
                 headers=hdr, timeout=30).raise_for_status()
    return "moved back in"


def send(device_id, key, temp, ts, comp, buffered):
    """One signed packet, signed the way firmware signs one."""
    nonce = uuid.uuid4().hex
    temp = round(temp, 2)
    body = {"device_id": device_id, "temperature": temp, "door_open": False, "ts": ts, "nonce": nonce,
            "buffered": buffered, "power_ok": True, "battery": 100.0, "compressor_on": comp,
            "signature": sign(canonical(device_id, temp, False, ts, nonce, True, 100.0, comp, buffered), key)}
    r = requests.post(f"{API}/api/sensor", json=body, timeout=30)
    if r.status_code >= 300:
        raise SystemExit(f"{device_id} packet refused ({r.status_code}): {r.text}")
    return r.json().get("status") == IGNORED


def cycled(n_cycles, healthy_cycles):
    """`n_cycles` complete runs of the thermostat rule, each row the reading at the end of a minute.

    The first `healthy_cycles` runs pull at PULL_HEALTHY and every run after that at PULL_SLOW, which is
    the whole of the fault. The health score compares a fridge's recent cycles with its own earliest
    ones, so a trace that was slow from the start has nothing to fall from.

    Every run ends on a row at exactly 3 C with the compressor still on, because a run that stops while
    the box is still above the cut-out is read by compressor.py as a relay being switched off rather than
    a unit slowing - and that warning is not the story this demo is telling.
    """
    rows, t, on, done = [], CUT_OUT_C, False, 0
    while done < n_cycles:
        if on:
            t = max(t - (PULL_HEALTHY if done < healthy_cycles else PULL_SLOW), CUT_OUT_C)
            rows.append((round(t, 2), True))
            if t <= CUT_OUT_C:
                on, done = False, done + 1
        else:
            t = t + WARM_C_PER_MIN
            if t >= CUT_IN_C:
                t, on = CUT_IN_C, True
            rows.append((round(t, 2), False))
    return rows


def warm_trace():
    """Four good cycles, three tired ones, then a compressor that stops cutting in.
    """
    rows = cycled(HEALTHY_CYCLES + SLOW_CYCLES, HEALTHY_CYCLES)
    t = rows[-1][0]
    for _ in range(STALL_MINUTES):
        t = min(t + STALL_C_PER_MIN, DEMO_TOP_C)
        rows.append((round(t, 2), False))
    return rows


def cold_trace():
    """The destination: healthy cycles, and it must stop while the unit is still cooling.

    Truncating inside a cooling run is not decoration. A trace that ends at the top of a coast-up reads
    to the model as a fridge on its way over the line, and a destination whose forecast risk is not
    `low` is refused by the relocation rules - so the demo would quietly have nowhere to move its own
    batches to. Cutting at the last row under 5 C leaves it mid-pull, with the slope still negative.
    """
    rows = cycled(COLD_CYCLES, COLD_CYCLES)
    stop = max(i for i, (t, on) in enumerate(rows) if on and t <= 5.0)
    return rows[:stop + 1]


def continuation(temp, on, steps, warm):
    """The next `steps` minutes of the same story, from where this node's own trace stopped.

    Same minute convention as cycled(): each row is the reading at the end of that minute, so a rerun
    joined onto the stored tail does not create a phantom cycle boundary.
    """
    rows, t = [], temp
    for _ in range(steps):
        if warm:
            t, state = min(t + STALL_C_PER_MIN, DEMO_TOP_C), False
        elif on:
            t, state = max(t - PULL_HEALTHY, CUT_OUT_C), True
            if t <= CUT_OUT_C:
                on = False
        else:
            t = t + WARM_C_PER_MIN
            if t >= CUT_IN_C:
                t, on = CUT_IN_C, True
            state = False
        rows.append((round(t, 2), state))
    return rows


def feed(device_id, key, rows, newest_ts):
    """Write `rows` oldest first on an exact minute grid, then one live packet at the current clock.

    The grid is what keeps the forecast usable at all: features.py refuses a node whose minute buckets
    are not contiguous back from the newest one, and spacing the packets by whatever each POST took can
    straddle a bucket boundary and leave a hole. So the whole trace is timestamped backwards from
    `newest_ts` and flagged as the offline buffer emptying, and only the single packet after it is live -
    which is also what keeps the node inside the 20-second online rule the relocation rules insist on.
    """
    n = len(rows)
    ignored = sum(1 for i, (temp, comp) in enumerate(rows)
                  if send(device_id, key, temp, newest_ts - (n - 1 - i) * 60, comp, True))
    temp, comp = rows[-1]
    if send(device_id, key, temp, time.time(), comp, False):
        ignored += 1
    return n + 1, ignored


def main():
    hdr = login()
    cold_id, cold_key = ensure_device(hdr, "Demo cold room", COLD_ID)
    warm_id, warm_key = ensure_device(hdr, "Demo ward (dying)", WARM_ID)
    placed = [f"{code} {ensure_batch(hdr, code, vaccine, expiry, warm_id)}"
              for code, vaccine, expiry in BATCHES]

    known = devices(hdr)
    now = time.time()
    for label, dev, key, fid, rows in (
            ("dying ward", WARM_ID, warm_key, warm_id, warm_trace()),
            ("cold room", COLD_ID, cold_key, cold_id, cold_trace())):
        if len(rows) > BUFFER_LIMIT_MIN:
            raise SystemExit(f"the {label} trace is {len(rows)} minutes long and the ingest only "
                             "accepts a buffered packet inside three hours - shorten the trace")
        node = known.get(dev)
        if node and node["last_ts"]:
            # already carrying a trace: the minutes it does not have yet, continuing from its own tail
            steps = min(max(int((now - node["last_ts"]) // 60), 1), BUFFER_LIMIT_MIN)
            rows = continuation(node["temperature"], bool(node["compressor_on"]), steps,
                                warm=(dev == WARM_ID))
            how = f"appending {steps} minute(s) onto the trace already stored"
        else:
            how = f"writing {len(rows)} minutes of history"
        n, ignored = feed(dev, key, rows, now)
        print(f"{label:11} {dev:12} fridge {fid:<3} {how}"
              + (f", {ignored} of {n} packets already stored and ignored" if ignored else ""))

    print("batches     " + ", ".join(placed))

    for label, dev in (("dying ward", WARM_ID), ("cold room", COLD_ID)):
        fc = requests.get(f"{API}/api/ai/forecast", params={"device_id": dev}, headers=hdr,
                          timeout=60).json()
        he = requests.get(f"{API}/api/ai/compressor", params={"device_id": dev}, headers=hdr,
                          timeout=120).json()["fridges"][0]
        print(f"\n{label} ({dev})")
        print(f"  forecast  {fc.get('state')} | risk {fc.get('risk')} | now {fc.get('now_c')} C | "
              f"+30 min {fc.get('forecast_c')} C | peak {fc.get('max_next_30_c')} C | "
              f"crosses 8 C in {fc.get('lead_min_est') if fc.get('lead_min_est') is not None else 'never'} min "
              f"| model {fc.get('model')}")
        for line in (fc.get("reasons") or [])[:2] + (fc.get("warnings") or [])[:2]:
            print(f"            {line}")
        print(f"  health    {he.get('score')}/100 ({he.get('band')}) on {he.get('cycles_used')} "
              f"clean cycle(s) of {he.get('cycles_seen')} seen | trend "
              f"{(he.get('trend') or {}).get('state')}")
        for line in (he.get("reasons") or [])[:2] + (he.get("warnings") or [])[:2]:
            print(f"            {line}")

    plan = requests.get(f"{API}/api/ai/relocations", headers=hdr, timeout=120).json()
    print(f"\nrelocation  {plan['count']} suggestion(s) | {plan['message']}")
    for s in plan["suggestions"]:
        print(f"  move {s['batch_code']} from {s['from_fridge_name']} to {s['to_fridge_name']} "
              f"({s['remaining_min']} budget-min left, {s['to_free_slots']} of {s['capacity']} places "
              f"free there)")
        print(f"    id {s['suggestion_id']} | valid until "
              f"{time.strftime('%H:%M:%S', time.localtime(s['expires_at']))}")
        print(f"    {s['reason']}")
    for u in plan["unplaced"]:
        print(f"  nowhere for {u['batch_code']}: {u['why']}")
    print("\nNext: open http://localhost:5173 and sign in as pharmacist or admin - the AI Insights tab "
          "shows these same three answers and the Confirm move button. This script never confirms a "
          "move for you; that click is the thing being demonstrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
