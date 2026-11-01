"""The offline buffer: what a node does for the hour the Wi-Fi was down.

These are the two behaviours the firmware depends on and the two that are easiest to get wrong on
stage: a replayed queue must land in order and cost each minute once, and a live reading sent before
the queue is emptied silently swallows the whole backlog.
"""
from conftest import budget, node, now, reading, readings_of, register, send


def queue(device_id, key, count=6, step=600, temp=9.0, end=None):
    """A backlog that ended at `end` (default: this instant), `count` readings `step` seconds apart,
    oldest first."""
    end = end if end is not None else now()
    return [reading(device_id, temp, end - step * (count - 1 - i), buffered=True, key=key)
            for i in range(count)]


def test_a_backlog_emptied_oldest_first_is_stored_in_order(client, tok):
    _, device_id, key = node(client, tok["admin"], "BUF-1", name="buffer node")
    bodies = queue(device_id, key)
    for b in bodies:
        r = client.post("/api/sensor", json=b)
        assert r.status_code == 201 and r.json()["status"] == "ok", b["ts"]
    stored = readings_of(device_id)
    assert [x[0] for x in stored] == sorted(x[0] for x in stored)
    assert all(x[2] for x in stored), "every replayed row keeps its buffered mark"
    assert len(stored) == len(bodies)


def test_the_backlog_costs_the_budget_once(client, tok):
    _, device_id, key = node(client, tok["admin"], "BUF-2", name="budget buffer node")
    end = now()
    bodies = queue(device_id, key, temp=9.0, end=end)
    for b in bodies:
        client.post("/api/sensor", json=b)
    # five gaps of 10 minutes at 9 C = 50 weighted minutes; the first reading costs nothing
    assert budget(client, tok["admin"], "BUF-2")["remaining_min"] == 10.0
    assert budget(client, tok["admin"], "BUF-2")["status"] == "At Risk"

    # the node cannot tell the server it already delivered these, so it resends the whole queue
    for b in bodies:
        assert client.post("/api/sensor", json=b).json()["detail"] == "replayed nonce"
    assert budget(client, tok["admin"], "BUF-2")["remaining_min"] == 10.0, "no double counting"
    assert len(readings_of(device_id)) == len(bodies)

    # ... and the same hour re-signed with brand new nonces is equally harmless
    for b in queue(device_id, key, end=end):
        r = client.post("/api/sensor", json=b)
        assert r.status_code == 201 and r.json()["status"] == "duplicate-ignored"
    assert len(readings_of(device_id)) == len(bodies)
    assert budget(client, tok["admin"], "BUF-2")["remaining_min"] == 10.0


def test_a_live_reading_sent_before_the_backlog_eats_the_backlog(client, tok):
    """The documented reason a node flushes oldest-first, as a test so the rule cannot rot.

    Anything at or before the last accepted timestamp is ignored, so one live sample lands ahead of
    the queued hour and every reading after it is dropped.
    """
    _, device_id, key = register(client, tok["admin"], name="wrong order node")
    live = send(client, device_id, 5.0, key=key)          # now
    assert live.json()["status"] == "ok"
    backlog = [send(client, device_id, 9.0, now() - 60 * i, buffered=True, key=key)
               for i in range(5, 0, -1)]
    assert all(r.json()["status"] == "duplicate-ignored" for r in backlog)
    assert len(readings_of(device_id)) == 1, "the hour of readings is gone - which is why the node flushes first"


def test_a_backlog_flushed_before_live_readings_survives(client, tok):
    _, device_id, key = register(client, tok["admin"], name="right order node")
    for b in queue(device_id, key, count=5, step=600, end=now() - 600):
        client.post("/api/sensor", json=b)
    assert send(client, device_id, 5.0, key=key).json()["status"] == "ok"
    assert len(readings_of(device_id)) == 6
