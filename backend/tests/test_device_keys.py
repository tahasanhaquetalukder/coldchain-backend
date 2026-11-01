"""Per-node keys: the secret is issued once, used forever, and never shown again.

This is what makes a fleet of real ESP32s safe to run - one cloned node can no longer sign readings
for every other fridge.
"""
import json
import re

from conftest import add_batch, audit_rows, fridge_field, now, reading, register, send


def test_registration_hands_back_the_key_once(client, tok):
    r = client.post("/api/devices", json={"name": "Clinic fridge", "device_id": "key-shape-1"},
                    headers=tok["admin"])
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "device_id", "hmac_key", "topic", "command_topic"}
    assert re.fullmatch(r"[0-9a-f]{32}", body["hmac_key"]), "token_hex(16): 128 bits, lowercase hex"
    assert body["topic"] == "coldchain/key-shape-1/reading"
    assert body["command_topic"] == "coldchain/key-shape-1/command"


def test_an_own_key_node_refuses_the_fleet_key(client, tok):
    _, device_id, key = register(client, tok["admin"], name="own key node")
    assert send(client, device_id, 5.0, key=key).status_code == 201
    forged = reading(device_id, 40.0)                    # signed with the shared fleet secret
    r = client.post("/api/sensor", json=forged)
    assert r.status_code == 401 and r.json()["detail"] == "invalid signature"
    assert fridge_field(device_id, "temperature") == 5.0


def test_a_seeded_fridge_still_signs_with_the_fleet_key(client, tok):
    # the two demo fridges predate registration, and the demo must keep working without a reflash
    assert send(client, "fridge-2", 5.0).status_code == 201
    row = next(d for d in client.get("/api/devices", headers=tok["admin"]).json()["devices"]
               if d["device_id"] == "fridge-2")
    assert row["own_key"] is False


def test_the_key_never_comes_back_out_of_a_get(client, tok):
    _, device_id, key = register(client, tok["admin"], name="leak probe")
    send(client, device_id, 5.0, key=key)
    for path in ("/api/devices", "/api/dashboard", "/api/audits", "/api/batches",
                 f"/api/readings?device_id={device_id}", f"/api/public/batch/VAX-001"):
        body = client.get(path, headers=tok["admin"])
        assert body.status_code == 200, path
        assert key not in json.dumps(body.json()), f"{path} echoed the node secret"
    for row in audit_rows("DEVICE_ADDED", device_id) + audit_rows("DEVICE_KEY_ROTATED", device_id):
        assert key not in row[1], "the audit chain is a readable log, not a key store"


def test_rotating_invalidates_the_old_key(client, tok):
    fid, device_id, old = register(client, tok["admin"], name="rotate node")
    assert send(client, device_id, 5.0, key=old).status_code == 201
    r = client.post(f"/api/devices/{fid}/key", headers=tok["admin"])
    assert r.status_code == 200
    new = r.json()["hmac_key"]
    assert new != old and re.fullmatch(r"[0-9a-f]{32}", new)
    assert client.post("/api/sensor", json=reading(device_id, 40.0, key=old)).json()["detail"] \
        == "invalid signature", "the old secret has to stop working on the next packet"
    assert send(client, device_id, 5.0, ts=now() + 1, key=new).status_code == 201


def test_rotating_a_missing_device_is_404(client, tok):
    assert client.post("/api/devices/999999/key", headers=tok["admin"]).status_code == 404


def test_registration_input_is_checked_before_a_row_is_written(client, tok):
    cases = [
        ({"name": "bad id", "device_id": "fridge 1"}, 422),      # a space is not a valid id
        ({"name": "bad id", "device_id": "fr;drop"}, 422),
        ({"name": "bad id", "device_id": ""}, 422),
        ({"name": "", "device_id": "ok-name"}, 422),
        ({"name": "n" * 41, "device_id": "long-name"}, 422),
    ]
    for payload, code in cases:
        assert client.post("/api/devices", json=payload, headers=tok["admin"]).status_code == code, payload
    dup = {"name": "first", "device_id": "dup-1"}
    assert client.post("/api/devices", json=dup, headers=tok["admin"]).status_code == 201
    assert client.post("/api/devices", json=dup, headers=tok["admin"]).status_code == 409


def test_removing_a_node_takes_its_readings_and_leaves_its_batches(client, tok):
    fid, device_id, key = register(client, tok["admin"], name="orphan node")
    add_batch(client, tok["admin"], "ORPH-1", fid)
    send(client, device_id, 5.0, key=key)
    r = client.delete(f"/api/devices/{fid}", headers=tok["admin"])
    assert r.status_code == 200 and r.json()["readings_deleted"] == 1
    assert client.delete(f"/api/devices/{fid}", headers=tok["admin"]).status_code == 404

    batches = client.get("/api/batches", headers=tok["admin"]).json()
    orphan = next(b for b in batches if b["code"] == "ORPH-1")
    assert orphan["fridge_id"] is None, "the dose outlives the fridge; only its location is unknown"
    assert audit_rows("DEVICE_REMOVED", device_id)


def test_the_device_row_carries_what_the_live_view_draws(client, tok):
    fid, device_id, key = register(client, tok["admin"], name="shape node")
    send(client, device_id, 5.0, ts=now() - 120, buffered=True, key=key)
    d = next(x for x in client.get("/api/devices", headers=tok["admin"]).json()["devices"]
             if x["id"] == fid)
    assert d["topic"] == f"coldchain/{device_id}/reading"
    assert d["replaying"] is True, "the newest row came from the queue, so the node is emptying its buffer"
    assert d["drift_s"] is not None and abs(d["drift_s"] + 120) < 5, "ts minus arrival time"
    assert d["online"] is False and 119 < d["age_s"] < 200
    assert d["readings"] == 1 and d["own_key"] is True and d["rejects"] == 0
    assert d["temperature"] == 5.0 and d["status"] == "Safe"


def test_a_node_that_has_never_reported_has_no_temperature(client, tok):
    fid, _, _ = register(client, tok["admin"], name="silent node")
    d = next(x for x in client.get("/api/devices", headers=tok["admin"]).json()["devices"]
             if x["id"] == fid)
    assert d["temperature"] is None and d["status"] is None
    assert d["age_s"] is None and d["online"] is False and d["replaying"] is False
    assert d["readings"] == 0
