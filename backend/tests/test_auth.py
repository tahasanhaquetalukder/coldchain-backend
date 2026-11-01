"""Who gets a token, who gets refused, and what the refusals leave behind."""
import time

import jwt
import pytest

from app import main
from conftest import audit_rows


def test_login_returns_token_and_role(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"token", "role", "username"}
    assert body["role"] == "admin" and body["username"] == "admin"
    # the token must carry what the routes read out of it, or every role check is decoration
    claims = jwt.decode(body["token"], main.JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "admin" and claims["role"] == "admin"


@pytest.mark.parametrize("role", ["pharmacist", "inspector"])
def test_every_seeded_role_can_sign_in(client, role):
    assert client.post("/api/auth/login",
                       json={"username": role, "password": f"{role}123"}).status_code == 200


def test_wrong_password_is_401_and_is_logged(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "guess"})
    assert r.status_code == 401
    assert "Wrong username or password" in r.json()["detail"]
    assert audit_rows("LOGIN_FAILED", "user=admin"), \
        "a failed login that is not in the tamper-evident log is a failed login nobody saw"


def test_unknown_username_is_401(client):
    assert client.post("/api/auth/login",
                       json={"username": "nobody", "password": "x"}).status_code == 401
    assert audit_rows("LOGIN_FAILED", "user=nobody")


def test_missing_token_cannot_read_the_dashboard(client):
    assert client.get("/api/dashboard").status_code in (401, 403)


@pytest.mark.parametrize("make", [
    lambda: "not-a-jwt",
    lambda: jwt.encode({"sub": "admin", "role": "admin", "exp": time.time() + 60},
                       "someone-elses-secret-0123456789ab", "HS256"),
    lambda: jwt.encode({"sub": "admin", "role": "admin", "exp": time.time() - 60},
                       main.JWT_SECRET, "HS256"),
])
def test_bad_or_expired_token_is_401(client, make):
    r = client.get("/api/dashboard", headers={"Authorization": f"Bearer {make()}"})
    assert r.status_code == 401
    assert "Session expired" in r.json()["detail"]


def test_an_unspent_token_is_accepted(client, tok):
    assert client.get("/api/dashboard", headers=tok["admin"]).status_code == 200


def test_health_needs_no_token(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
