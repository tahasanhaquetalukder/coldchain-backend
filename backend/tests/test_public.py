"""The public QR check: the one page a stranger scans, so it answers as little as possible."""
import pytest

from app import main
from conftest import add_batch, audit_rows, budget, node, now, register, send, set_batch_minutes


def test_shape_and_no_login(client, tok):
    r = client.get("/api/public/batch/VAX-001")
    assert r.status_code == 200
    assert set(r.json()) == {"code", "vaccine", "expiry", "status", "expired"}
    assert r.json()["code"] == "VAX-001"
    # nothing here identifies the fridge, the keys or the log - a scanner is not staff
    assert "fridge" not in r.text and "hmac" not in r.text.lower()


def test_the_page_needs_no_token_at_all(client):
    for code in ("VAX-001", "VAX-002", "does-not-exist"):
        assert client.get(f"/api/public/batch/{code}").status_code in (200, 404)


@pytest.mark.parametrize("used,status", [(0.0, "Safe"), (55.0, "At Risk"), (61.0, "Discard")])
def test_the_budget_is_what_the_page_shows(client, tok, used, status):
    code = f"PUB-{used}"
    add_batch(client, tok["admin"], code, 1)
    set_batch_minutes(code, used)
    assert client.get(f"/api/public/batch/{code}").json()["status"] == status


def test_an_expired_batch_is_flagged_whatever_its_temperature_said(client, tok):
    add_batch(client, tok["admin"], "PUB-OLD", 1, expiry="2020-01-01")
    body = client.get("/api/public/batch/PUB-OLD").json()
    assert body["expired"] is True and body["status"] == "Safe"


def test_a_batch_still_in_the_future_is_not_flagged(client, tok):
    add_batch(client, tok["admin"], "PUB-NEW", 1, expiry="2099-01-01")
    assert client.get("/api/public/batch/PUB-NEW").json()["expired"] is False


def test_an_unknown_code_is_a_plain_404(client):
    r = client.get("/api/public/batch/NOPE")
    assert r.status_code == 404 and r.json()["detail"] == "Batch not found"


def test_a_batch_is_created_within_its_budget(client, tok):
    add_batch(client, tok["admin"], "PUB-FRESH", 1)
    assert budget(client, tok["admin"], "PUB-FRESH")["remaining_min"] == main.BUDGET


@pytest.mark.parametrize("expiry", ["2027-13-01", "01-03-2027", "tomorrow", "", None])
def test_a_non_iso_expiry_never_reaches_the_public_page(client, tok, expiry):
    """The date is compared as written; garbage would either crash the scanned page or silently
    read as not-expired, so it is refused at the only door it comes through."""
    code = f"BAD-{repr(expiry)}"
    r = client.post("/api/batches",
                    json={"code": code, "vaccine": "V", "expiry": expiry, "fridge_id": 1},
                    headers=tok["admin"])
    assert r.status_code == 422, r.text


def test_a_batch_only_costs_the_fridge_it_is_stored_in(client, tok):
    """Moving stock is a real ward decision, and the budget follows the crate, not the label."""
    _, a_dev, a_key = node(client, tok["admin"], "MOV-1", name="fridge A")
    b_fid, b_dev, b_key = register(client, tok["admin"], name="fridge B")
    t0 = now() - 1200
    send(client, a_dev, 13.0, t0, buffered=True, key=a_key)          # first reading: no elapsed time
    send(client, a_dev, 13.0, t0 + 120, buffered=True, key=a_key)    # 2 min weighed double
    assert budget(client, tok["admin"], "MOV-1")["remaining_min"] == 56.0

    bid = budget(client, tok["admin"], "MOV-1")["id"]
    assert client.put(f"/api/batches/{bid}/move", json={"fridge_id": b_fid},
                      headers=tok["admin"]).status_code == 200
    assert audit_rows("BATCH_MOVED", "MOV-1")

    send(client, a_dev, 13.0, t0 + 240, buffered=True, key=a_key)    # the old fridge costs nothing now
    assert budget(client, tok["admin"], "MOV-1")["remaining_min"] == 56.0
    send(client, b_dev, 13.0, t0, buffered=True, key=b_key)
    send(client, b_dev, 13.0, t0 + 120, buffered=True, key=b_key)
    assert budget(client, tok["admin"], "MOV-1")["remaining_min"] == 52.0
