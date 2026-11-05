"""Task 5 phase 2: the forecast route, its refusal to guess, and one warning per heat wave.

The traces below are built from signed ingest packets, one minute apart, exactly as a node sends them
- not by writing rows straight into the table. A forecast that only works on fabricated history would
be worth nothing, because the thing it is asked to predict is what the table actually holds.
"""
import pytest

from conftest import audit_rows, history, now, register, send

SHARED = "fridge-1"


def test_the_forecast_requires_a_token(client):
    assert client.get(f"/api/ai/forecast?device_id={SHARED}").status_code == 401


@pytest.mark.parametrize("role", ["admin", "pharmacist", "inspector"])
def test_every_logged_in_role_can_ask(client, tok, role):
    """Not a role check to relax later: the clerk who has to decide whether to move the stock now is
    often the inspector, and the forecast gives away nothing the dashboard does not already show."""
    r = client.get(f"/api/ai/forecast?device_id={SHARED}", headers=tok[role])
    assert r.status_code == 200, r.text


def test_an_unknown_device_is_not_forecast(client, tok):
    assert client.get("/api/ai/forecast?device_id=ghost-9", headers=tok["admin"]).status_code == 404


def test_a_trace_shorter_than_the_window_refuses_to_forecast(client, tok):
    _, device_id, key = register(client, tok["admin"])
    history(client, device_id, key, minutes=8)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["state"] == "not enough data"
    assert out["minutes_needed"] == 15 and out["minutes_of_history"] == 8
    assert out["forecast_c"] is None and out["max_next_30_c"] is None
    assert out["breach"] is False and out["now_c"] is None


def test_a_longer_trace_gives_a_number_and_says_which_model_it_came_from(client, tok):
    _, device_id, key = register(client, tok["admin"])
    history(client, device_id, key, minutes=30, base=5.0, trend=0.12)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["state"] == "forecast"
    assert out["model"] in ("ridge", "gbm", "fallback")
    assert out["horizon_min"] == 30 and out["threshold_c"] == 8.0
    assert out["now_c"] == pytest.approx(5.0 + 0.12 * 29, abs=0.2)
    # a box climbing 0.12 C a minute is not going to be colder in half an hour, whichever model won
    assert out["forecast_c"] > out["now_c"]
    assert out["max_next_30_c"] >= out["forecast_c"]
    assert out["reasons"], "a number nobody can explain is not a decision support tool"


def test_a_hot_trace_raises_one_warning_and_a_cold_one_raises_none(client, tok):
    _, hot, hot_key = register(client, tok["admin"], name="Forecast Hot")
    history(client, hot, hot_key, minutes=30, base=8.5, trend=0.2)
    first = client.get(f"/api/ai/forecast?device_id={hot}", headers=tok["admin"]).json()
    assert first["breach"] is True and first["lead_min_est"] is not None
    assert len(audit_rows("BREACH_WARNING", hot)) == 1

    # the same page polled again, and the next ingest check: still one episode, so still one row
    for _ in range(3):
        assert client.get(f"/api/ai/forecast?device_id={hot}", headers=tok["admin"]).json()["breach"] is True
    send(client, hot, 14.0, ts=now() - 30, buffered=True, key=hot_key)
    assert len(audit_rows("BREACH_WARNING", hot)) == 1, "one row per episode, not one per poll"

    _, cold, cold_key = register(client, tok["admin"], name="Forecast Cold")
    history(client, cold, cold_key, minutes=30, base=4.0, trend=-0.02)
    out = client.get(f"/api/ai/forecast?device_id={cold}", headers=tok["admin"]).json()
    assert out["breach"] is False and out["forecast_c"] < 8.0
    assert audit_rows("BREACH_WARNING", cold) == []


def test_the_warning_can_fire_from_ingest_alone(client, tok, monkeypatch):
    """No request to /api/ai/forecast anywhere here: a hot node must warn while the page is closed.

    The interval is shortened so a test that posts thirty packets in a second can exercise the path;
    in production it is what keeps one evaluation per node per minute instead of one per reading.
    """
    from app import main as app_main

    monkeypatch.setattr(app_main, "AI_CHECK_INTERVAL", 0.0)
    _, device_id, key = register(client, tok["admin"], name="Ingest Breach")
    history(client, device_id, key, minutes=30, base=9.0, trend=0.2)
    rows = audit_rows("BREACH_WARNING", device_id)
    assert len(rows) == 1, f"expected exactly one warning row, got {len(rows)}"
    assert "model" in rows[0][1], rows[0][1]


def test_a_new_episode_needs_the_forecast_to_have_closed_and_the_cooldown_to_have_passed(client, tok):
    """The device clock is used for the episode, and the contract lets a buffered packet carry a
    timestamp up to three hours away, so a test can move that clock the way a day moving does."""
    _, device_id, key = register(client, tok["admin"], name="Episode Reset")
    history(client, device_id, key, minutes=30, base=9.0, trend=0.2)
    assert client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()["breach"] is True
    assert len(audit_rows("BREACH_WARNING", device_id)) == 1

    # still hot, thirty device-minutes later: the episode never closed, so nothing new is raised
    history(client, device_id, key, minutes=6, base=14.0, trend=0.0, start=now() + 1800)
    assert len(audit_rows("BREACH_WARNING", device_id)) == 1

    # the box comes back down and stays down: the episode closes
    history(client, device_id, key, minutes=30, base=6.0, trend=-0.05, start=now() + 2400)
    assert client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()["breach"] is False
    assert len(audit_rows("BREACH_WARNING", device_id)) == 1

    # and a fresh heat wave after the cooldown is a second, separate warning. The forecast is asked for
    # explicitly: the ingest-side check runs once per node per minute of wall clock, and thirty packets
    # posted in a second do not advance that clock, so the posts alone would never evaluate this trace.
    history(client, device_id, key, minutes=30, base=9.0, trend=0.2, start=now() + 6000)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["breach"] is True, out
    rows = audit_rows("BREACH_WARNING", device_id)
    assert len(rows) == 2, f"a closed episode must be able to open again, got {len(rows)} rows"


def test_a_missing_model_falls_back_and_says_so(client, tok, tmp_path, monkeypatch):
    """The deployed image can ship without a usable model.json and must still answer.

    A forecast endpoint that 500s is worse than a crude one: the operator stops trusting the tab.
    """
    from app.ai import predict

    monkeypatch.setattr(predict, "MODEL_PATH", str(tmp_path / "absent-model.json"))
    _, device_id, key = register(client, tok["admin"], name="Fallback Fridge")
    history(client, device_id, key, minutes=30, base=6.0, trend=0.1)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["state"] == "forecast" and out["model"] == "fallback"
    assert any("no usable trained model" in w for w in out["warnings"]), out["warnings"]
    assert out["forecast_c"] is not None


def test_a_corrupt_model_file_falls_back_too(client, tok, tmp_path, monkeypatch):
    from app.ai import predict

    bad = tmp_path / "model.json"
    bad.write_text('{"trained": true, "heads": {}, "feature_names": ["nonsense"]}', encoding="utf-8")
    monkeypatch.setattr(predict, "MODEL_PATH", str(bad))
    _, device_id, key = register(client, tok["admin"], name="Corrupt Model Fridge")
    history(client, device_id, key, minutes=20, base=6.0, trend=0.1)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["model"] == "fallback" and out["forecast_c"] is not None
    assert any("different feature list" in w or "missing a head" in w for w in out["warnings"]), out["warnings"]


def test_the_forecast_reads_the_new_signed_columns(client, tok):
    """duty_15, door_min_15 and power_off_min_15 only exist because ingest kept what it verified."""
    _, device_id, key = register(client, tok["admin"], name="Flagged Trace")
    history(client, device_id, key, minutes=30, base=6.0, trend=0.05, compressor_on=True, door=True)
    out = client.get(f"/api/ai/forecast?device_id={device_id}", headers=tok["admin"]).json()
    assert out["state"] == "forecast"
    assert any("door reported open" in r for r in out["reasons"]), out["reasons"]
    assert any("compressor ran" in r for r in out["reasons"]), out["reasons"]
