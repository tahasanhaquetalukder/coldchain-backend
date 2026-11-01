"""The heat-exposure budget: weighted minutes above 8 C, and what each threshold means."""
import pytest

from app import main
from conftest import add_batch, audit_rows, budget, node, now, register, send, set_batch_minutes


def test_only_above_eight_costs_minutes_and_above_twelve_costs_double(client, tok):
    _, device_id, key = node(client, tok["admin"], "HB-1", name="weighting node")
    base = now() - 3000
    # seconds since the previous reading -> temperature -> weighted minutes that step must add
    steps = [(0, 5.0, 0.0), (600, 8.0, 0.0), (720, 9.0, 2.0), (840, 13.0, 4.0), (2400, 13.0, 20.0)]
    spent = 0.0
    for offset, t, add in steps:
        spent += add
        assert send(client, device_id, t, base + offset, buffered=True, key=key).status_code == 201
        got = budget(client, tok["admin"], "HB-1")["remaining_min"]
        assert got == round(main.BUDGET - spent, 1), f"{t} C after {offset}s left {got} min"


def test_the_first_reading_never_costs_anything(client, tok):
    # there is no elapsed time to weigh before a previous timestamp exists
    _, device_id, key = node(client, tok["admin"], "HB-2", name="first reading node")
    assert send(client, device_id, 30.0, key=key).status_code == 201
    assert budget(client, tok["admin"], "HB-2")["remaining_min"] == main.BUDGET


def test_a_gap_longer_than_ten_minutes_is_capped(client, tok):
    # a fridge that was offline for a day is a reporting gap, not a day of spoilage: the cap is what
    # stops one replayed backlog from flipping a still-good batch straight to Discard
    _, device_id, key = node(client, tok["admin"], "HB-3", name="capping node")
    send(client, device_id, 5.0, now() - 3 * 3600 + 120, buffered=True, key=key)
    send(client, device_id, 13.0, now() - 60, buffered=True, key=key)
    assert budget(client, tok["admin"], "HB-3")["remaining_min"] == main.BUDGET - 20.0, \
        "a >12 C gap must cost exactly the capped 10 minutes weighed double"


@pytest.mark.parametrize("used,pct,status", [
    (0.0, 100.0, "Safe"),
    (48.0, 20.0, "Safe"),        # exactly 20% is still Safe; the rule is "below 20"
    (48.1, 19.8, "At Risk"),
    (59.9, 0.2, "At Risk"),
    (60.0, 0.0, "Discard"),
    (75.0, 0.0, "Discard"),      # the budget never reads as negative
])
def test_thresholds(client, tok, used, pct, status):
    code = f"THR-{used}"
    add_batch(client, tok["admin"], code, 1)
    set_batch_minutes(code, used)
    b = budget(client, tok["admin"], code)
    assert (b["remaining_pct"], b["status"]) == (pct, status)


def test_a_discarded_batch_stays_discarded_until_an_admin_resets_it(client, tok):
    add_batch(client, tok["admin"], "RST-1", 1)
    set_batch_minutes("RST-1", 200)
    b = budget(client, tok["admin"], "RST-1")
    assert b["status"] == "Discard" and b["remaining_min"] == 0.0

    assert client.post(f"/api/batches/{b['id']}/reset", headers=tok["pharmacist"]).status_code == 403
    assert client.post(f"/api/batches/{b['id']}/reset", headers=tok["inspector"]).status_code == 403
    assert client.post(f"/api/batches/{b['id']}/reset", headers=tok["admin"]).status_code == 200
    fresh = budget(client, tok["admin"], "RST-1")
    assert fresh["remaining_min"] == main.BUDGET and fresh["status"] == "Safe"
    assert audit_rows("ADMIN_RESET", "RST-1")


def test_crossing_a_threshold_is_written_to_the_chain_once(client, tok):
    _, device_id, key = node(client, tok["admin"], "CRS-1", name="crossing node")
    t0 = now() - 1200
    send(client, device_id, 5.0, t0, buffered=True, key=key)
    set_batch_minutes("CRS-1", 59.0)
    # two minutes at 13 C costs four weighted minutes, so this reading is the one that flips it
    r = send(client, device_id, 13.0, t0 + 120, buffered=True, key=key)
    assert r.json()["batch_status"] == "Discard"
    assert "At Risk -> Discard" in audit_rows("BATCH_STATUS", "CRS-1")[-1][1]
    assert send(client, device_id, 13.0, t0 + 240, buffered=True, key=key).json()["batch_status"] == "Discard"
    assert len(audit_rows("BATCH_STATUS", "CRS-1")) == 1, "one row per change, not one per reading"


def test_a_fridge_with_no_batch_has_no_status(client, tok):
    _, device_id, key = register(client, tok["admin"], name="batchless node")
    assert send(client, device_id, 5.0, key=key).json()["batch_status"] is None
