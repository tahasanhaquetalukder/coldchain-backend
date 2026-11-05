"""The device contract: what is accepted, what is refused, and what each refusal costs.

Every case here is one the firmware can hit in the field, so the reasons are asserted as text - the
operator sees them verbatim in the Devices tab, and a reworded reason is a reworded diagnosis.
"""
import pytest

from conftest import audit_rows, fridge_field, now, reading, reading_flags, readings_of, register, send

SHARED = "fridge-1"          # a seeded fridge, so it still signs with the shared fleet key


def test_a_correctly_signed_reading_is_stored(client):
    r = send(client, SHARED, 5.4)
    assert r.status_code == 201 and r.json()["status"] == "ok"
    last = readings_of(SHARED)[-1]
    assert last[1] == 5.4 and last[2] is False


def test_a_tampered_signature_is_refused_and_audited(client):
    body = reading(SHARED, 30.0)
    body["signature"] = "0" * 64
    r = client.post("/api/sensor", json=body)
    assert r.status_code == 401 and r.json()["detail"] == "invalid signature"
    logged = audit_rows("MESSAGE_REJECTED", f"device={body['device_id']}")[-1]
    assert "reason=invalid signature" in logged[1] and body["nonce"] in logged[1]
    assert not any(x[0] == body["ts"] for x in readings_of(SHARED)), \
        "a rejected packet must not reach the trace"


@pytest.mark.parametrize("buffered", [True, False])
def test_the_buffered_flag_is_part_of_the_signature(client, buffered):
    """Flipping the flag alone must not widen (or narrow) a captured reading's timestamp window.

    Unsigned, one stolen live packet could be replayed hours later as an offline-buffer reading and
    pass - which is the difference between a gap in the record and a fabricated cold chain.
    """
    honest = reading(SHARED, 6.0, buffered=not buffered)
    relabelled = dict(honest, buffered=buffered)   # same nonce, same signature, different flag
    r = client.post("/api/sensor", json=relabelled)
    assert r.status_code == 401 and r.json()["detail"] == "invalid signature"


def test_live_readings_get_sixty_seconds(client):
    assert send(client, SHARED, 5.0, ts=now() - 120).json()["detail"] == "stale timestamp"
    assert send(client, SHARED, 5.0, ts=now() + 120).json()["detail"] == "stale timestamp"


def test_a_buffered_replay_gets_three_hours(client, tok):
    _, device_id, key = register(client, tok["admin"])
    assert send(client, device_id, 4.8, now() - 2 * 3600, buffered=True, key=key).status_code == 201
    assert send(client, device_id, 4.9, now() - 4 * 3600, buffered=True, key=key) \
        .json()["detail"] == "stale timestamp"


def test_a_replayed_nonce_is_refused(client):
    body = reading(SHARED, 5.1)
    assert client.post("/api/sensor", json=body).status_code == 201
    assert client.post("/api/sensor", json=body).json()["detail"] == "replayed nonce"


def test_an_unregistered_id_is_refused_after_the_signature_checks(client):
    # a valid fleet signature from an id nobody registered is the classic "flashed the wrong DEVICE_ID"
    r = send(client, "ghost-1", 5.0)
    assert r.status_code == 401 and r.json()["detail"] == "unknown device"
    assert audit_rows("MESSAGE_REJECTED", "reason=unknown device")


def test_rejection_order_is_signature_first(client):
    """A forged packet from an unknown id reports the forgery, not the missing registration -
    otherwise the endpoint tells an attacker which device ids exist."""
    body = dict(reading("ghost-order", 5.0), signature="ff" * 32)
    assert client.post("/api/sensor", json=body).json()["detail"] == "invalid signature"


def test_an_out_of_order_reading_is_ignored_without_a_row(client, tok):
    _, device_id, key = register(client, tok["admin"])
    ts = now() - 600
    assert send(client, device_id, 5.0, ts, buffered=True, key=key).json()["status"] == "ok"
    before = len(readings_of(device_id))

    late = send(client, device_id, 31.0, ts - 300, buffered=True, key=key)
    assert late.status_code == 201 and late.json() == {"status": "duplicate-ignored"}
    stored = readings_of(device_id)
    assert len(stored) == before, "an ignored resend must not add a point to the trace"
    assert not any(t == 31.0 for _, t, _, _ in stored)


def test_the_nonce_of_an_ignored_packet_is_still_consumed(client, tok):
    # the nonce row is written before the out-of-order guard, so a node that re-sends its whole
    # queue cannot use one packet's nonce twice
    _, device_id, key = register(client, tok["admin"])
    ts = now() - 600
    send(client, device_id, 5.0, ts, buffered=True, key=key)
    body = reading(device_id, 31.0, ts - 300, buffered=True, key=key)
    assert client.post("/api/sensor", json=body).json()["status"] == "duplicate-ignored"
    assert client.post("/api/sensor", json=body).json()["detail"] == "replayed nonce"


def test_a_door_left_open_past_the_limit_raises_one_alert(client, tok):
    name = "Alert-Door-A"
    fid, device_id, key = register(client, tok["admin"], name=name)
    t0 = now() - 300
    assert send(client, device_id, 5.0, t0, door=True, buffered=True, key=key).status_code == 201
    assert audit_rows("DOOR_ALERT", name) == []
    assert send(client, device_id, 5.0, t0 + 70, door=True, buffered=True, key=key).status_code == 201
    assert len(audit_rows("DOOR_ALERT", name)) == 1
    # still open, far past the limit - and no second row until the door is shut and opened again
    assert send(client, device_id, 5.0, t0 + 400, door=True, buffered=True, key=key).status_code == 201
    assert len(audit_rows("DOOR_ALERT", name)) == 1
    assert fridge_field(device_id, "door_alerted") is True
    row = next(d for d in client.get("/api/devices", headers=tok["admin"]).json()["devices"]
               if d["id"] == fid)
    assert row["door_alert"] is True


def test_a_shut_door_resets_the_open_timer(client, tok):
    name = "Alert-Door-B"
    _, device_id, key = register(client, tok["admin"], name=name)
    t0 = now() - 300
    send(client, device_id, 5.0, t0, door=True, buffered=True, key=key)
    send(client, device_id, 5.0, t0 + 70, door=True, buffered=True, key=key)
    assert len(audit_rows("DOOR_ALERT", name)) == 1
    send(client, device_id, 5.0, t0 + 90, door=False, buffered=True, key=key)
    # opened again after being shut: the clock restarts, so nothing fires at once and a fresh
    # alert comes 60 s later
    send(client, device_id, 5.0, t0 + 100, door=True, buffered=True, key=key)
    assert len(audit_rows("DOOR_ALERT", name)) == 1
    send(client, device_id, 5.0, t0 + 170, door=True, buffered=True, key=key)
    assert len(audit_rows("DOOR_ALERT", name)) == 2


def test_the_signed_compressor_and_power_states_reach_the_trace(client, tok):
    """Task 5 scores compressor runs and power gaps out of the readings table, and both fields have
    been signed, verified and thrown away on the way in since Task 1. A health score built on that
    table would otherwise have been guessing."""
    _, device_id, key = register(client, tok["admin"])
    send(client, device_id, 6.2, compressor_on=True, power_ok=False, key=key)
    assert reading_flags(device_id)[-1][1:] == (True, False)
    send(client, device_id, 6.3, compressor_on=False, power_ok=True, key=key)
    assert reading_flags(device_id)[-1][1:] == (False, True)


def test_a_row_without_the_new_fields_reads_back_unknown_not_off(client, tok):
    """Rows written before the migration are NULL, and NULL must stay NULL.

    Coerced to False, a week of history would claim the compressor never ran, which is the one
    reading of the data that would make every health score meaningless.
    """
    _, device_id, key = register(client, tok["admin"])
    assert send(client, device_id, 5.0, key=key).status_code == 201
    from app import database, models
    s = database.SessionLocal()
    try:
        s.add(models.Reading(device_id=device_id, ts=now() + 1, temperature=5.0, door_open=False))
        s.commit()
    finally:
        s.close()
    assert reading_flags(device_id)[-1][1:] == (None, None)


def test_a_simulator_shaped_packet_is_accepted(client):
    """Assembled the way backend/simulator.py assembles it, not the way conftest.reading does.

    The simulator builds its own dict and its own canonical string, so it is the one signer this repo
    runs against a deployed server without going through the test fixture. If the field order or a
    float's spelling drifts, every demo reading dies as "invalid signature" and only a test like this
    one says so before the stage does.
    """
    from app import hmac_auth

    ts, nonce = round(now(), 2), "0123456789abcdef0123456789abcdef"
    body = dict(device_id=SHARED, temperature=round(5.0, 1), door_open=False, ts=ts, nonce=nonce,
                compressor_on=False, power_ok=True, battery=100.0, buffered=False)
    message = hmac_auth.canonical(body["device_id"], body["temperature"], body["door_open"], ts, nonce,
                                  body["power_ok"], body["battery"], body["compressor_on"],
                                  body["buffered"])
    assert message == f"{SHARED}|5.0|0|{ts}|{nonce}|1|100.0|0|0"
    body["signature"] = hmac_auth.sign(message)
    assert hmac_auth.verify(message, body["signature"]) is True
    r = client.post("/api/sensor", json=body)
    assert r.status_code == 201, r.text
    assert readings_of(SHARED)[-1][1] == 5.0
