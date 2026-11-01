"""Rejections are the one thing an anonymous sender can produce on demand.

Each audit row costs a hash over the previous one, so an unthrottled log is a free way to grow the
database and slow every reader of it - while still having to tell the operator the truth.
"""
import time

from app import main
from conftest import audit_rows, now, reading, readings_of, register, send


def test_the_interval_is_one_minute():
    assert main.REJECT_LOG_INTERVAL == 60


def advance(device, reason):
    """Step the recorded time back instead of sleeping through a minute of demo."""
    main._REJECT_SEEN[(device, reason)][0] -= main.REJECT_LOG_INTERVAL + 1


def logged(client, tok, device):
    d = next(x for x in client.get("/api/devices", headers=tok["admin"]).json()["devices"]
             if x["device_id"] == device)
    return d["rejects"], d["reasons"]


def test_a_flood_is_one_row_and_still_every_time_a_401(client, tok):
    device = "ghost-flood"
    for _ in range(12):
        r = client.post("/api/sensor", json=reading(device, 5.0))
        assert r.status_code == 401 and r.json()["detail"] == "unknown device"
    assert len(audit_rows("MESSAGE_REJECTED", f"device={device}")) == 1, "twelve packets, one row"


def test_the_swallowed_count_rides_along_on_the_next_row(client, tok):
    device = "ghost-suppressed"
    for _ in range(5):
        send(client, device, 5.0)
    assert len(audit_rows("MESSAGE_REJECTED", f"device={device}")) == 1

    advance(device, "unknown device")
    send(client, device, 5.0)
    rows_now = audit_rows("MESSAGE_REJECTED", f"device={device}")
    assert len(rows_now) == 2
    assert "suppressed=4" in rows_now[-1][1], "the row says how many it stood in for"

    # ... and the counter resets, so the row after that is not double-counting the same packets
    advance(device, "unknown device")
    send(client, device, 5.0)
    assert "suppressed=" not in audit_rows("MESSAGE_REJECTED", f"device={device}")[-1][1]


def test_each_reason_gets_its_own_row(client, tok):
    device = "ghost-reasons"
    send(client, device, 5.0)                                       # unknown device
    client.post("/api/sensor", json=dict(reading(device, 5.0), signature="ab" * 32))
    client.post("/api/sensor", json=reading(device, 5.0, ts=now() - 600))   # stale timestamp
    reasons = [r[1] for r in audit_rows("MESSAGE_REJECTED", f"device={device}")]
    assert len(reasons) == 3, "a mixed flood must not collapse into one reason"
    assert any("reason=unknown device" in x for x in reasons)
    assert any("reason=invalid signature" in x for x in reasons)
    assert any("reason=stale timestamp" in x for x in reasons)


def test_the_live_view_adds_a_burst_up_once_the_next_row_lands(client, tok):
    device = "ghost-visible"
    for _ in range(7):
        send(client, device, 5.0)
    unknown = client.get("/api/devices", headers=tok["admin"]).json()["unknown"]
    entry = next(u for u in unknown if u["device_id"] == device)
    assert entry["n"] == 1, "inside the window only the first packet has a row behind it"

    advance(device, "unknown device")
    send(client, device, 5.0)
    entry = next(u for u in client.get("/api/devices", headers=tok["admin"]).json()["unknown"]
                 if u["device_id"] == device)
    assert entry["n"] == 8 and entry["reasons"] == {"unknown device": 8}, \
        "one row stands for 1 + suppressed, so a flood is never hidden"
    assert entry["last"] > time.time() - 120


def test_a_replay_storm_on_a_registered_node_shows_under_that_node(client, tok):
    _, device_id, key = register(client, tok["admin"], name="storm node")
    body = reading(device_id, 5.0, key=key)
    client.post("/api/sensor", json=body)
    for _ in range(4):
        assert client.post("/api/sensor", json=body).json()["detail"] == "replayed nonce"
    n, reasons = logged(client, tok, device_id)
    assert (n, reasons) == (1, {"replayed nonce": 1})
    assert len(readings_of(device_id)) == 1, "rejections never become readings"

    advance(device_id, "replayed nonce")
    client.post("/api/sensor", json=body)
    n, reasons = logged(client, tok, device_id)
    assert (n, reasons) == (5, {"replayed nonce": 5})
