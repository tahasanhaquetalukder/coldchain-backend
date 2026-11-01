"""The role matrix, one row per route.

Written as data rather than one test per endpoint because the failure that matters is a route that
forgot its dependency - a table makes "which roles may call this" reviewable at a glance.
"""
import pytest

from conftest import add_batch, register

ADMIN, PHARM, INSP = "admin", "pharmacist", "inspector"


def test_dashboard_is_open_to_all_three(client, tok):
    for role in (ADMIN, PHARM, INSP):
        assert client.get("/api/dashboard", headers=tok[role]).status_code == 200


def test_ingest_and_public_check_need_no_token(client):
    # the node has no password - the HMAC is its identity - and the QR page is scanned by strangers
    assert client.get("/api/public/batch/VAX-001").status_code == 200
    assert client.post("/api/sensor", json={"device_id": "x"}).status_code == 422


def test_reads(client, tok):
    for path, allowed in [("/api/batches", {ADMIN, PHARM, INSP}),
                          ("/api/audits", {ADMIN, INSP}),
                          ("/api/audits/verify", {ADMIN, INSP}),
                          ("/api/devices", {ADMIN, PHARM, INSP}),
                          ("/api/readings?device_id=fridge-1", {ADMIN, PHARM, INSP})]:
        for role in (ADMIN, PHARM, INSP):
            r = client.get(path, headers=tok[role])
            assert (r.status_code == 200) == (role in allowed), f"{path} as {role} -> {r.status_code}"
            if role not in allowed:
                assert r.status_code == 403 and "cannot do this" in r.json()["detail"]


def test_batch_write_needs_admin_or_pharmacist(client, tok):
    for role, expected in [(ADMIN, 201), (PHARM, 201), (INSP, 403)]:
        r = client.post("/api/batches",
                        json={"code": f"RBAC-{role}", "vaccine": "V", "expiry": "2030-01-01"},
                        headers=tok[role])
        assert r.status_code == expected, r.text


@pytest.mark.parametrize("role,expected", [(ADMIN, 200), (PHARM, 200), (INSP, 403)])
def test_move(client, tok, role, expected):
    bid = client.get("/api/batches", headers=tok[ADMIN]).json()[0]["id"]
    assert client.put(f"/api/batches/{bid}/move", json={"fridge_id": 1},
                      headers=tok[role]).status_code == expected


@pytest.mark.parametrize("role,expected", [(ADMIN, 200), (PHARM, 403), (INSP, 403)])
def test_budget_reset_is_admin_only(client, tok, role, expected):
    add_batch(client, tok[ADMIN], f"RESET-{role}", 2)
    bid = next(b["id"] for b in client.get("/api/batches", headers=tok[ADMIN]).json()
               if b["code"] == f"RESET-{role}")
    assert client.post(f"/api/batches/{bid}/reset", headers=tok[role]).status_code == expected


@pytest.mark.parametrize("role,expected", [(ADMIN, 201), (PHARM, 403), (INSP, 403)])
def test_registering_a_node_is_admin_only(client, tok, role, expected):
    r = client.post("/api/devices", json={"name": "rbac", "device_id": f"rbac-{role}"},
                    headers=tok[role])
    assert r.status_code == expected
    if expected == 201:
        client.delete(f"/api/devices/{r.json()['id']}", headers=tok[ADMIN])


@pytest.mark.parametrize("role,expected", [(ADMIN, 200), (PHARM, 403), (INSP, 403)])
def test_key_rotation_is_admin_only(client, tok, role, expected):
    fid, _, _ = register(client, tok[ADMIN], name=f"rotate-{role}")
    assert client.post(f"/api/devices/{fid}/key", headers=tok[role]).status_code == expected
    client.delete(f"/api/devices/{fid}", headers=tok[ADMIN])


@pytest.mark.parametrize("role,expected", [(ADMIN, 200), (PHARM, 403), (INSP, 403)])
def test_removing_a_node_is_admin_only(client, tok, role, expected):
    fid, _, _ = register(client, tok[ADMIN], name=f"remove-{role}")
    assert client.delete(f"/api/devices/{fid}", headers=tok[role]).status_code == expected


def test_a_non_admin_token_cannot_reach_the_audit_chain_by_luck(client, tok):
    # 403, not 401: the request was authenticated, it just is not allowed - the UI shows the reason
    r = client.get("/api/audits", headers=tok[PHARM])
    assert r.status_code == 403 and r.json()["detail"] == "pharmacist cannot do this"
