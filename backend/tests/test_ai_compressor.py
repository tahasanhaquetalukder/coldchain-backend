"""Task 5 phase 3: the compressor health score, and the route that serves it.

The algorithmic checks run against app.ai.compressor directly, on traces built minute by minute with
the same thermostat rule the simulator and ml/generate_data.py use. They do not go through HTTP
because a score is a property of a trace, not of a request, and because the interesting cases - a
wearing machine, a door left open, four cycles of history - need hundreds of minutes of data each.
The route tests then send a real trace through signed ingest, so at least one number here came out
of the table the server actually wrote.
"""
import pytest

from app import main
from app.ai import compressor as C
from app.ai.features import resample
from conftest import now, register, send

START = 1_700_000_000      # fixed: these traces are history, and their absolute clock is not the point


def trace(minutes, pull=0.45, leak=0.12, door=(), door_leak=6.0, late_from=None, late_pull=None,
          power_from=None, power_to=None, stops=(), cut_in=7.0, cut_out=3.0, start=START):
    """A fridge that cycles between the two thermostat lines, one reading per minute.

    `pull` is what the compressor takes out per minute and `leak` what the room puts back, so a weak
    machine is the same box with a smaller pull in its second half: the only difference between the
    two traces is the cooling, which is what the score is supposed to be about. The compressor stops
    when the supply fails or when `stops` says it was switched off, and the door multiplies the leak
    instead of merely being a flag, so an open door warms the box the way one really does.
    """
    t, on, rows = cut_in, False, []
    for m in range(minutes):
        powered = not (power_from is not None and power_from <= m < power_to)
        if on and (not powered or m in stops or t <= cut_out):
            on = False
        elif not on and powered and t >= cut_in:
            on = True
        rate = late_pull if late_from is not None and m >= late_from and on else pull
        t += leak * (door_leak if m in door else 1.0) - (rate if on else 0.0)
        rows.append((start + m * 60, round(min(14.0, max(1.0, t)), 3), int(on), int(m in door),
                     1 if powered else 0))
    return rows


HEALTHY = trace(2400)
WEARING = trace(2400, late_from=1200, late_pull=0.20)


def test_a_healthy_fridge_scores_high_and_a_wearing_one_does_not():
    good, weak = C.score(HEALTHY), C.score(WEARING)
    assert good["score"] >= 80 and good["band"] == "good", good["reasons"]
    assert weak["score"] <= good["score"] - 20, (good["score"], weak["score"])
    assert weak["band"] in ("watch", "weak")
    assert weak["trend"]["state"] == "declining", weak["trend"]


def test_the_score_stays_inside_zero_and_a_hundred_whatever_it_is_given():
    shapes = [HEALTHY, WEARING, trace(2400, late_from=1200, late_pull=0.14),
              trace(2400, leak=0.9), trace(2400, door=set(range(900, 1200))),
              trace(2400, power_from=900, power_to=1200), trace(2400, stops={600, 900, 1200}),
              trace(60), trace(0),
              [(ts, temp, None, door, power) for ts, temp, _c, door, power in HEALTHY]]
    for rows in shapes:
        out = C.score(rows)
        assert out["score"] is None or 0 <= out["score"] <= 100, out
        assert out["band"] in (None, "good", "watch", "weak"), out
        assert isinstance(out["reasons"], list) and isinstance(out["warnings"], list)


def test_a_cycle_with_the_door_open_is_excluded_and_not_blamed():
    """The same healthy box, with the door open for twenty minutes in the middle of its history.

    Warming the fridge is the door's fault. Scored, those runs would mark the machine down for
    something the ward did, which is the mistake this exclusion exists to prevent.
    """
    door = set(range(900, 920))
    rows = trace(2400, door=door)
    listed = C.cycles(resample(rows))
    dirty, clean = C.score(rows), C.score(HEALTHY)
    assert any(c["excluded"] == "door" for c in listed)
    assert "door" in next(c["excluded_because"] for c in listed if c["excluded"] == "door")
    assert dirty["cycles_excluded"] > clean["cycles_excluded"]
    assert dirty["score"] >= 80, f"a warm door must not lower a good compressor: {dirty['reasons']}"


def test_a_run_the_supply_stopped_is_excluded_but_a_run_switched_off_while_warm_is_named():
    """Two reasons for a run to end early, only one of which belongs to the machine.

    A supply that drops is not a health signal, so the cycle goes. A run that stops with the box
    still warm and the supply fine is a real signal, and it is reported in words - the score itself
    measures the pull, and a relay that cuts power to a good motor is not a slow motor.

    The window is taken from a run the healthy trace actually contains, because an outage that lands
    while the compressor is already idle ends no run at all and proves nothing either way.
    """
    run = C.cycles(resample(HEALTHY))[5]
    mid = (run["a"] + run["b"]) // 2
    outage = C.score(trace(2400, power_from=mid, power_to=mid + 5))
    assert outage["cycles_excluded"] >= 1, outage
    assert outage["runs_stopped_warm"] == 0, "a run the supply stopped is not a run the machine stopped"
    assert outage["score"] >= 80, outage["reasons"]
    dropped = C.score(trace(2400, stops={mid}))
    assert dropped["runs_stopped_warm"] >= 1, dropped
    assert any("switched off" in w for w in dropped["warnings"]), dropped["warnings"]


def test_too_few_cycles_is_a_refusal_and_not_a_small_number():
    for rows in (trace(30), trace(60), trace(90), []):
        out = C.score(rows)
        assert out["score"] is None and out["band"] is None
        assert out["state"] == "not enough cycles yet"
        assert out["reasons"] and "cycle" in out["reasons"][0]
        assert out["cycles_used"] == 0
    assert C.score(HEALTHY)["cycles_used"] >= C.MIN_CYCLES


def test_a_week_that_never_recorded_the_compressor_state_scores_nothing_rather_than_off():
    """Rows written before the column existed come back NULL. NULL is not "the compressor was stopped"."""
    rows = [(ts, temp, None, door, power) for ts, temp, _c, door, power in HEALTHY]
    out = C.score(rows)
    assert out["score"] is None and out["cycles_seen"] == 0
    assert out["rows_without_compressor_state"] == len(rows)
    assert any("predate the compressor" in w for w in out["warnings"])


def test_the_reasons_are_sentences_and_they_point_at_the_number_that_moved():
    weak = C.score(WEARING)
    assert 1 <= len(weak["reasons"]) <= 3, weak["reasons"]
    assert not any(feature in r for r in weak["reasons"]
                   for feature in ("cool_c_per_min", "starts_per_hour", "sub_score", "duty_")), weak["reasons"]
    worst = min(weak["metrics"].items(), key=lambda kv: kv[1]["sub_score"])[0]
    assert any(word in " ".join(weak["reasons"]) for word in
               {"cool_c_per_min": "cools", "cool_min_7_to_3": "cool from",
                "duty": "runs", "starts_per_hour": "starts"}[worst]), (worst, weak["reasons"])
    healthy = C.score(HEALTHY)
    assert healthy["reasons"], "a score with no explanation is a number, not advice"


def test_the_metrics_it_reports_are_the_ones_the_score_is_made_of():
    out = C.score(WEARING)
    assert set(out["metrics"]) <= {"cool_c_per_min", "cool_min_7_to_3", "duty", "starts_per_hour"}
    assert out["metrics"], "a score made of nothing at all is not a score"
    for name, m in out["metrics"].items():
        assert m["worse_if"] in ("up", "down") and 0 <= m["sub_score"] <= 100, (name, m)
    # the 7-to-3 fall is the cycle an operator would time with a stopwatch; it must be measured here
    fall = out["metrics"]["cool_min_7_to_3"]
    assert fall["recent"] > fall["baseline"], fall


def test_a_run_still_going_at_the_newest_reading_is_not_counted_as_a_cycle():
    """Half a cooling attempt measures nothing, and the newest minute of a live node always sits
    inside some run. Counting it would make the page's number depend on the moment it was asked."""
    rows = ([(START + m * 60, 7.0 - m, 1, 0, 1) for m in range(5)]        # 7 C down to 3 C, run ends
            + [(START + (5 + m) * 60, 4.0 + m, 0, 0, 1) for m in range(4)]   # and warms back to 7 C
            + [(START + (9 + m) * 60, 7.0 - m, 1, 0, 1) for m in range(4)])  # second run, still going
    series = resample(rows)
    every = C.cycles(series)
    assert series[-1]["comp"] == 1 and series[-1]["minute"] == series[0]["minute"] + 12
    assert len(every) == 1 and every[0]["b"] == 4, every
    assert C.score(rows)["state"] == "not enough cycles yet"


def test_the_baseline_is_the_early_cycles_and_not_the_ones_being_graded():
    """A fridge whose last cycles are the only ones measured would always score itself perfect."""
    out = C.score(WEARING)
    assert out["cycles_used"] > C.RECENT_CYCLES
    assert set(out["metrics"]) == {"cool_c_per_min", "cool_min_7_to_3", "duty", "starts_per_hour"}
    short = C.score(trace(100))
    if short["score"] is not None:
        assert any("baseline" in w for w in short["warnings"]), short["warnings"]


# ---------- the route ----------
def compressor_history(client, device_id, key, minutes=150, pull=0.9, leak=0.6, start=None):
    """The same thermostat loop, sent as signed packets one minute apart through /api/sensor.

    150 minutes because the ingest window for a buffered queue is three hours, and a history posted
    outside it is rejected as stale rather than stored: the test would then be scoring nothing.
    """
    start = start if start is not None else now() - minutes * 60
    t, on = 7.0, False
    for m in range(minutes):
        if on and t <= 3.0:
            on = False
        elif not on and t >= 7.0:
            on = True
        t += (-pull if on else leak)
        send(client, device_id, round(min(12.0, max(2.0, t)), 2), ts=start + m * 60,
             buffered=True, key=key, compressor_on=on)


def test_the_compressor_route_needs_a_token(client):
    assert client.get("/api/ai/compressor").status_code == 401


@pytest.mark.parametrize("role", ["admin", "pharmacist", "inspector"])
def test_every_logged_in_role_can_read_it(client, tok, role):
    """A clerk deciding whether to move stock wants the health of the box, and this gives away
    nothing the dashboard does not already show."""
    r = client.get("/api/ai/compressor", headers=tok[role])
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"count", "fridges"}


def test_it_answers_one_shape_for_one_fridge_and_for_all_of_them(client, tok):
    """Filtered and unfiltered must not be two different APIs for the page to branch over."""
    everything = client.get("/api/ai/compressor", headers=tok["admin"]).json()
    registered = client.get("/api/devices", headers=tok["admin"]).json()
    assert everything["count"] == len(everything["fridges"]) == len(registered)
    one = everything["fridges"][0]["device_id"]
    single = client.get(f"/api/ai/compressor?device_id={one}", headers=tok["admin"]).json()
    assert single["count"] == 1 and single["fridges"][0]["device_id"] == one
    assert single["fridges"][0]["device_name"], "the page shows names, and only the route knows them"


def test_an_unknown_device_has_no_compressor_to_score(client, tok):
    assert client.get("/api/ai/compressor?device_id=ghost-9", headers=tok["admin"]).status_code == 404


def test_a_node_with_no_history_is_reported_as_unknown_rather_than_as_zero(client, tok):
    _, device_id, _key = register(client, tok["admin"], name="Never Heard Of")
    out = client.get(f"/api/ai/compressor?device_id={device_id}", headers=tok["admin"]).json()["fridges"][0]
    assert out["score"] is None and out["state"] == "not enough cycles yet"
    assert out["rows_read"] == 0 and out["reasons"]


def test_a_cycling_node_sent_through_ingest_comes_back_scored(client, tok):
    """End to end: signed packets in, the table, the resample, the cycles, a number out."""
    _, device_id, key = register(client, tok["admin"], name="Cycling Node")
    compressor_history(client, device_id, key)
    out = client.get(f"/api/ai/compressor?device_id={device_id}", headers=tok["admin"]).json()["fridges"][0]
    assert out["state"] == "scored", out["reasons"]
    assert out["rows_read"] == 150 and out["score"] is not None
    assert 0 <= out["score"] <= 100 and out["band"] in ("good", "watch", "weak")
    assert out["cycles_used"] >= C.MIN_CYCLES and out["minutes_of_history"] >= 100
    assert out["reasons"] and out["trend"]["state"]


def test_a_window_cut_by_the_row_cap_says_so(client, tok, monkeypatch):
    """The cap exists so a poll of ten fridges stays cheap; it must not silently become less history.

    Lowering the cap is the only way to reach this branch in a test - the real one needs thirty
    thousand stored readings, and posting them would take longer than the check is worth.
    """
    _, device_id, key = register(client, tok["admin"], name="Capped Node")
    compressor_history(client, device_id, key)
    monkeypatch.setattr(main, "COMPRESSOR_MAX_ROWS", 40)
    out = client.get(f"/api/ai/compressor?device_id={device_id}", headers=tok["admin"]).json()["fridges"][0]
    assert out["rows_read"] == 40
    assert any("newest 40 readings" in w for w in out["warnings"]), out["warnings"]
