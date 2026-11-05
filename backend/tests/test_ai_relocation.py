"""Task 5 phase 4: the relocation rules, then the two routes that serve them.

The rules are tested twice on purpose. First as pure functions on hand-written fridge states, because
every branch of 'may this fridge receive stock' is a sentence someone could get wrong and a unit test
is the only way to make each one fail on its own. Then through the API on traces that arrived as signed
packets, because the state the rules read is computed by the forecast and the health score, and a rule
that only works against a fixture is not the rule that runs in the ward.
"""
import uuid

import pytest

from app import main
from app.ai import predict
from app.ai import relocation as R
from conftest import audit_rows, budget, history, node, now, register, add_batch, send, set_fridge


def state(fid, name=None, **over):
    """One fridge, in the shape app.ai.relocation reads, with the boring defaults filled in."""
    st = {"id": fid, "device_id": f"dev-{fid}", "name": name or f"Fridge {fid}",
          "online": True, "power_ok": True, "door_open": False, "temperature": 4.0,
          "risk": "low", "max_next_30_c": 5.0, "lead_min_est": None, "score": None, "band": None,
          "batches": []}
    st.update(over)
    return st


def lot(bid, code, remaining_min, expiry="2030-01-01"):
    return {"id": bid, "code": code, "vaccine": "Test Vaccine", "expiry": expiry,
            "remaining_min": remaining_min, "remaining_pct": round(remaining_min / 60 * 100, 1),
            "status": "Discard" if remaining_min <= 0 else "At Risk" if remaining_min < 12 else "Safe"}


def plan(states, capacity=6, now_ts=1_000_000.0):
    return R.suggest(states, capacity=capacity, now=now_ts)


# ---------- which fridges are flagged ----------
def test_every_reason_a_fridge_is_at_risk_is_reported_not_only_the_first():
    p = plan([state(1, risk="high", max_next_30_c=11.0, lead_min_est=9, temperature=11.4, score=30,
                    band="weak", batches=[lot(1, "VAX-1", 40)])])
    reasons = p["fridges"][0]["risk_reasons"]
    assert len(reasons) == 3, reasons
    assert any("11" in r and "8 C" in r for r in reasons)
    assert any("30/100" in r for r in reasons)
    assert p["at_risk_fridges"] == [1]


def test_a_watch_forecast_on_a_healthy_fridge_is_not_a_reason_to_move():
    p = plan([state(1, risk="watch", max_next_30_c=7.4, temperature=6.0, score=80,
                    batches=[lot(1, "VAX-1", 40)])])
    assert p["at_risk_fridges"] == [] and p["suggestions"] == []
    assert "no fridge is currently at risk" in p["message"]


def test_a_tired_compressor_alone_flags_a_fridge():
    p = plan([state(1, risk="low", score=49, batches=[lot(1, "VAX-1", 40)])])
    assert p["at_risk_fridges"] == [1]
    assert p["fridges"][0]["risk_reasons"] == ["compressor health 49/100"]


def test_a_score_of_exactly_fifty_is_not_weak_and_no_score_is_not_weak_either():
    assert plan([state(1, score=50)])["at_risk_fridges"] == []
    assert plan([state(1, score=None)])["at_risk_fridges"] == []


def test_a_fridge_sitting_hot_with_no_forecast_is_still_at_risk():
    """A node with too little history has risk None; 12 C in the box is not a reason to do nothing."""
    p = plan([state(1, risk=None, max_next_30_c=None, temperature=12.0,
                    batches=[lot(1, "VAX-1", 40)])])
    assert p["at_risk_fridges"] == [1]
    assert "reporting 12.0 C now" in p["fridges"][0]["risk_reasons"]


# ---------- which fridges may receive ----------
@pytest.mark.parametrize("field,value,wanted", [
    ("online", False, "offline"),
    ("power_ok", False, "not on mains"),
    ("door_open", True, "door open"),
    ("risk", None, "no forecast yet"),
    ("risk", "watch", "forecast risk watch"),
    ("risk", "high", "forecast risk high"),
    ("score", 20, "compressor health 20/100"),
])
def test_each_rule_that_disqualifies_a_destination(field, value, wanted):
    others = {"high": 11.0, "watch": 7.5}.get(value)
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)]),
              state(2, **{field: value, **({"max_next_30_c": others} if others else {})})])
    assert p["eligible_destinations"] == [], p["fridges"]
    assert wanted in p["fridges"][1]["destination_blockers"]


def test_a_full_fridge_is_not_a_destination():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)]),
              state(2, batches=[lot(i, f"VAX-{i}", 50) for i in (2, 3)])], capacity=2)
    assert "no free place" in p["fridges"][1]["destination_blockers"]
    assert p["eligible_destinations"] == []


def test_a_fridge_that_is_itself_at_risk_is_never_a_destination():
    """Both flags can be true of the same fridge; the destination rules have to notice."""
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)]),
              state(2, temperature=8.5, batches=[lot(2, "VAX-2", 40)])])
    assert p["at_risk_fridges"] == [1, 2] and p["eligible_destinations"] == []
    assert any(b.startswith("itself flagged for relocation") for b in p["fridges"][1]["destination_blockers"])


# ---------- which batch goes where ----------
def test_the_most_urgent_batch_is_offered_first_and_earliest_expiry_breaks_the_tie():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0,
                    batches=[lot(1, "VAX-LATE", 40, "2027-01-01"), lot(2, "VAX-URGENT", 5),
                             lot(3, "VAX-TIE", 5, "2026-01-01")]),
              state(2)])
    assert [s["batch_code"] for s in p["suggestions"]] == ["VAX-TIE", "VAX-URGENT", "VAX-LATE"]


def test_the_coolest_healthy_fridge_wins_when_two_are_eligible():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)]),
              state(2, temperature=6.0, score=90),
              state(3, temperature=2.5, score=61),
              state(4, temperature=2.5, score=None)])
    assert p["eligible_destinations"] == [3, 4, 2], "coolest first, then healthiest, then id"
    assert p["suggestions"][0]["to_fridge_id"] == 3


def test_batches_spread_over_the_next_destination_when_the_first_runs_out():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0,
                    batches=[lot(1, "VAX-1", 40), lot(2, "VAX-2", 30), lot(3, "VAX-3", 20)]),
              state(2, temperature=4.0), state(3, temperature=5.0)], capacity=2)
    assert [(s["batch_code"], s["to_fridge_id"]) for s in p["suggestions"]] == \
        [("VAX-3", 2), ("VAX-2", 2), ("VAX-1", 3)]
    # the card quotes the room the batch arrives at, not the room left after it was promised
    assert [s["to_free_slots"] for s in p["suggestions"]] == [2, 1, 2]
    assert ["2 of 2 places free" in s["reason"] for s in p["suggestions"]] == [True, False, True]


def test_no_eligible_destination_says_so_and_names_the_rule_for_every_fridge():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0,
                    batches=[lot(1, "VAX-1", 40), lot(2, "VAX-2", 30)]),
              state(2, power_ok=False, name="Fridge B"), state(3, risk="watch", max_next_30_c=7.6)])
    assert p["suggestions"] == []
    assert [u["batch_code"] for u in p["unplaced"]] == ["VAX-2", "VAX-1"], "least budget first"
    why = p["unplaced"][0]["why"]
    assert "Fridge B: not on mains" in why and "Fridge 3: forecast risk watch" in why
    assert "no other fridge qualifies as a destination" in p["message"]


def test_a_single_fridge_site_says_there_is_nowhere_to_go():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)])])
    assert "only registered fridge" in p["unplaced"][0]["why"]
    assert p["suggestions"] == []


def test_an_unhealthy_destination_is_not_chosen_even_though_it_is_the_coolist():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, batches=[lot(1, "VAX-1", 40)]),
              state(2, temperature=1.0, score=30, band="weak"),
              state(3, temperature=6.0, score=95)])
    assert p["suggestions"][0]["to_fridge_id"] == 3


# ---------- the id ----------
def test_a_suggestion_id_is_reproducible_from_the_numbers_alone():
    a = R.suggestion_id(7, 1, 2, now=1_000_000.0)
    assert a == R.suggestion_id(7, 1, 2, now=1_000_000.0)
    assert a != R.suggestion_id(7, 1, 3, now=1_000_000.0)
    assert len(a) == 16


def test_an_id_still_counts_as_current_one_window_later_and_expired_two_later():
    issued = R.suggestion_id(7, 1, 2, now=1_000_000.0)
    # minted inside window 1666 (999600-1000200), so anything up to the end of 1667 still honours it
    assert R.suggestion_is_current(7, 1, 2, issued, now=1_000_000.0 + 599)
    assert not R.suggestion_is_current(7, 1, 2, issued, now=1_000_000.0 + 1300)
    assert not R.suggestion_is_current(7, 1, 9, issued, now=1_000_000.0), "a different fridge, a different id"


def test_a_suggestion_carries_the_numbers_and_an_expiry_about_ten_minutes_out():
    p = plan([state(1, risk="high", max_next_30_c=11.0, temperature=10.0, lead_min_est=8,
                    score=30, batches=[lot(1, "VAX-1", 12.0)]),
              state(2, temperature=2.0)], capacity=4, now_ts=1_000_000.0)
    s = p["suggestions"][0]
    assert s["expires_at"] == 1_000_600.0 and s["ttl_s"] == 600
    assert s["capacity"] == 4 and s["to_free_slots"] == 4
    for fragment in ["VAX-1", "Fridge 1", "Fridge 2", "12.0", "compressor health 30/100", "2.0 C"]:
        assert fragment in s["reason"], s["reason"]
    assert "4 of 4 places free" in s["reason"]


# ---------- the capacity assumption ----------
def test_the_capacity_setting_is_a_count_of_batches(monkeypatch):
    monkeypatch.delenv("MAX_BATCHES_PER_FRIDGE", raising=False)
    assert main.read_capacity() == 6, "the documented default"
    monkeypatch.setenv("MAX_BATCHES_PER_FRIDGE", " 2 ")
    assert main.read_capacity() == 2


@pytest.mark.parametrize("value", ["four", "6.5", "0", "-3", "two batches"])
def test_a_capacity_the_rules_cannot_use_is_refused_rather_than_guessed(monkeypatch, value):
    """A fridge that 'holds nothing' would make every batch unmovable and every card silent, which is
    the same failure as a typo, so neither is allowed to boot."""
    monkeypatch.setenv("MAX_BATCHES_PER_FRIDGE", value)
    with pytest.raises(RuntimeError, match="MAX_BATCHES_PER_FRIDGE"):
        main.read_capacity()


# ---------- the two routes ----------
def trace(client, device, key, live_c, minutes=30, base=5.0, trend=0.1, **flags):
    """Signed readings one minute apart, ending with one live packet at the current second.

    The history is anchored to the live reading's own timestamp instead of to the clock when the call
    started, because conftest.history() walks forward from `now`: if the minute boundary passes while
    those posts are being made, the live reading lands two buckets after the last historical one and
    leaves a one-minute hole. The forecast counts contiguous minutes, so a fridge with half an hour of
    perfect data answers "not enough data" - a failure that appears about once a minute and looks like
    a bug in the rules.
    """
    live = now()
    history(client, device, key, minutes=minutes, base=base, trend=trend,
            start=live - minutes * 60, **flags)
    send(client, device, live_c, key=key, ts=live, **flags)


@pytest.fixture()
def hot_and_cool(client, tok):
    """A breaching fridge holding one batch, and an empty fridge at 2.8 C, both fed through ingest.

    Built from signed packets rather than hand-written rows, so the risk levels the rules read are the
    ones the trained model actually returns. The destination is deliberately the coldest node in the
    suite: every test shares one database, and a ranking that depends on no other fridge existing would
    be a ranking that changes when the suite grows.
    """
    tag = uuid.uuid4().hex[:6]
    src_id, src_device, src_key = node(client, tok["admin"], f"REL-SRC-{tag}")
    dst_id, dst_device, dst_key = register(client, tok["admin"], name=f"REL-DST-{tag}")
    trace(client, src_device, src_key, 14.5, base=8.5, trend=0.2)
    trace(client, dst_device, dst_key, 2.8, base=3.2, trend=-0.01, compressor_on=True)
    return {"src_id": src_id, "src_device": src_device, "dst_id": dst_id, "dst_device": dst_device,
            "batch": budget(client, tok["admin"], f"REL-SRC-{tag}")}


def relocations(client, tok):
    return client.get("/api/ai/relocations", headers=tok["admin"]).json()


def for_batch(p, batch_id):
    """The suggestion for one batch inside a plan somebody already fetched.

    Scoped by batch rather than counted: with the whole fleet in one database there are other suggestions
    in every response, and 'the plan is empty' was never the assertion worth making.
    """
    return next((s for s in p["suggestions"] if s["batch_id"] == batch_id), None)


def row_for(p, fridge_id):
    return next(f for f in p["fridges"] if f["id"] == fridge_id)


def confirm(client, tok, s, role="pharmacist"):
    return client.post("/api/ai/relocations/confirm",
                       json={"batch_id": s["batch_id"], "to_fridge_id": s["to_fridge_id"],
                             "suggestion_id": s["suggestion_id"]}, headers=tok[role])


def test_the_relocation_route_needs_a_token(client):
    assert client.get("/api/ai/relocations").status_code == 401


@pytest.mark.parametrize("role", ["admin", "pharmacist", "inspector"])
def test_any_logged_in_role_may_read_the_suggestions(client, tok, role):
    r = client.get("/api/ai/relocations", headers=tok[role])
    assert r.status_code == 200, r.text
    out = r.json()
    assert {"suggestions", "unplaced", "fridges", "capacity_per_fridge", "message",
            "at_risk_fridges", "eligible_destinations"} <= set(out)


def test_a_breaching_fridge_is_offered_a_cool_destination(client, tok, hot_and_cool):
    p = relocations(client, tok)
    src, dst = row_for(p, hot_and_cool["src_id"]), row_for(p, hot_and_cool["dst_id"])
    assert src["at_risk"] is True and src["risk"] == "high" and src["eligible_destination"] is False
    assert dst["at_risk"] is False and dst["risk"] == "low" and dst["eligible_destination"] is True
    s = for_batch(p, hot_and_cool["batch"]["id"])
    assert s is not None and s["to_fridge_id"] == hot_and_cool["dst_id"]
    assert s["batch_code"] == hot_and_cool["batch"]["code"]
    assert s["suggestion_id"] == R.suggestion_id(s["batch_id"], src["id"], dst["id"],
                                                 now=s["created_at"])
    assert "heat-budget minutes" in s["reason"] and "REL-DST" in s["reason"]


def test_a_calm_fridge_next_to_a_calm_fridge_is_not_offered_anything(client, tok):
    tag = uuid.uuid4().hex[:6]
    fid, device_id, key = node(client, tok["admin"], f"REL-CALM-{tag}")
    trace(client, device_id, key, 2.9, base=3.2, trend=-0.01, compressor_on=True)
    p = relocations(client, tok)
    assert row_for(p, fid)["at_risk"] is False
    assert for_batch(p, budget(client, tok["admin"], f"REL-CALM-{tag}")["id"]) is None


def test_reading_a_suggestion_does_not_spend_the_breach_warning(client, tok, hot_and_cool):
    """The page polls; the episode does not belong to it.

    A GET that consumed the episode would leave the ingest path with nothing to raise, and the ward would
    get no message on the day the forecast was right.
    """
    device = hot_and_cool["src_device"]
    assert for_batch(relocations(client, tok), hot_and_cool["batch"]["id"]) is not None
    assert device not in predict._BREACH_SEEN, "reading the plan must not touch the episode state"
    out = client.get(f"/api/ai/forecast?device_id={device}", headers=tok["admin"]).json()
    assert out["breach"] is True and out["breach_warning_raised"] is True


def test_confirm_is_pharmacist_and_admin_only(client, tok, hot_and_cool):
    s = for_batch(relocations(client, tok), hot_and_cool["batch"]["id"])
    r = confirm(client, tok, s, role="inspector")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "inspector cannot do this"
    assert budget(client, tok["admin"], s["batch_code"])["fridge_id"] == hot_and_cool["src_id"]


def test_an_admin_may_confirm_the_same_move(client, tok, hot_and_cool):
    """The refusal above only means something if the two roles it names get through, so the admin half is
    asserted on a fresh suggestion rather than only on a repeat click.
    """
    s = for_batch(relocations(client, tok), hot_and_cool["batch"]["id"])
    out = confirm(client, tok, s, role="admin")
    assert out.status_code == 200, out.text
    assert out.json()["already_confirmed"] is False
    assert budget(client, tok["admin"], s["batch_code"])["fridge_id"] == s["to_fridge_id"]
    logged = audit_rows("RELOCATION_CONFIRMED", contains=f"batch={s['batch_id']} ")
    assert len(logged) == 1 and "by=admin" in logged[0][1]


def test_confirming_moves_the_batch_and_records_who_did_it(client, tok, hot_and_cool):
    s = for_batch(relocations(client, tok), hot_and_cool["batch"]["id"])
    r = confirm(client, tok, s)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["already_confirmed"] is False and out["from_fridge_id"] == hot_and_cool["src_id"]
    assert out["to_fridge_id"] == s["to_fridge_id"] and out["reason"] == s["reason"]
    assert budget(client, tok["admin"], s["batch_code"])["fridge_id"] == s["to_fridge_id"]
    logged = audit_rows("RELOCATION_CONFIRMED", contains=f"batch={s['batch_id']} ")
    assert len(logged) == 1 and "by=pharmacist" in logged[0][1]
    assert audit_rows("BATCH_MOVED", contains=s["batch_code"]), "the move is audited as a move too"
    assert client.get("/api/audits/verify", headers=tok["admin"]).json()["valid"] is True


def test_confirming_a_second_time_is_the_same_answer_not_a_second_move(client, tok, hot_and_cool):
    s = for_batch(relocations(client, tok), hot_and_cool["batch"]["id"])
    first = confirm(client, tok, s).json()
    again = confirm(client, tok, s, role="admin")
    assert again.status_code == 200, again.text
    out = again.json()
    assert out["already_confirmed"] is True and out["audit_id"] == first["audit_id"]
    assert out["from_fridge_id"] == hot_and_cool["src_id"], "read back off the record, not off the client"
    assert "moved nothing" in out["reason"]
    assert len(audit_rows("RELOCATION_CONFIRMED", contains=f"batch={s['batch_id']} ")) == 1
    assert len(audit_rows("BATCH_MOVED", contains=s["batch_code"])) == 1
    assert client.get("/api/audits/verify", headers=tok["admin"]).json()["valid"] is True


def test_a_suggestion_id_that_is_not_the_current_one_is_refused(client, tok, hot_and_cool):
    """Two windows old: the move is still the right one, and the server still refuses it.

    The id is what proves the click was made against the card the page is showing. Without the check a
    pharmacist could confirm a recommendation the rules stopped making five minutes ago, and the numbers
    quoted in the audit row would not be the numbers anybody agreed to.
    """
    s = for_batch(relocations(client, tok), hot_and_cool["batch"]["id"])
    stale = R.suggestion_id(s["batch_id"], s["from_fridge_id"], s["to_fridge_id"],
                            now=now() - 2 * R.SUGGESTION_TTL_S)
    assert stale != s["suggestion_id"]
    r = client.post("/api/ai/relocations/confirm",
                    json={"batch_id": s["batch_id"], "to_fridge_id": s["to_fridge_id"],
                          "suggestion_id": stale}, headers=tok["pharmacist"])
    assert r.status_code == 409 and "expired" in r.json()["detail"], r.json()
    assert budget(client, tok["admin"], s["batch_code"])["fridge_id"] == hot_and_cool["src_id"]


def test_a_move_the_server_no_longer_recommends_is_refused(client, tok, hot_and_cool):
    """The page named a fridge; then that fridge went quiet for an hour. The client does not win."""
    p = relocations(client, tok)
    s = for_batch(p, hot_and_cool["batch"]["id"])
    chosen = row_for(p, s["to_fridge_id"])
    set_fridge(chosen["device_id"], last_ts=now() - 3600)
    r = confirm(client, tok, s)
    assert r.status_code == 409, r.text
    assert "no longer" in r.json()["detail"] or "have changed" in r.json()["detail"], r.json()
    assert budget(client, tok["admin"], s["batch_code"])["fridge_id"] == hot_and_cool["src_id"]
    assert audit_rows("RELOCATION_CONFIRMED", contains=f"batch={s['batch_id']} ") == []


def test_no_suggestion_ever_overfills_a_fridge(client, tok, hot_and_cool, monkeypatch):
    """Capacity as a rule the whole plan obeys, whatever else is in the database.

    Asserted as an invariant over the response rather than as a count of my own suggestions: with one
    shared database the fleet holds every other test's fridges, and a test that assumed they would stay
    out of the way would fail the day one of them moves house.
    """
    monkeypatch.setattr(main, "MAX_BATCHES_PER_FRIDGE", 1)
    p = relocations(client, tok)
    assert p["capacity_per_fridge"] == 1
    room = {f["id"]: f["free_slots"] for f in p["fridges"]}
    arrivals = {}
    for s in p["suggestions"]:
        arrivals[s["to_fridge_id"]] = arrivals.get(s["to_fridge_id"], 0) + 1
    assert all(n <= room[tid] for tid, n in arrivals.items()), (arrivals, room)
    assert not [tid for tid, n in arrivals.items() if room[tid] <= 0], "a full fridge received a move"
    owed = sum(f["batch_count"] for f in p["fridges"] if f["at_risk"])
    assert owed >= 1 and len(p["suggestions"]) + len(p["unplaced"]) == owed, \
        "every batch in an at-risk fridge is either offered a move or listed as unplaced"


def test_a_destination_that_is_full_is_not_offered(client, tok, hot_and_cool, monkeypatch):
    tag = uuid.uuid4().hex[:6]
    add_batch(client, tok["admin"], f"REL-IN-DST-{tag}", hot_and_cool["dst_id"])
    monkeypatch.setattr(main, "MAX_BATCHES_PER_FRIDGE", 1)
    p = relocations(client, tok)
    assert [s["to_fridge_id"] for s in p["suggestions"]
            if s["batch_id"] == hot_and_cool["batch"]["id"]] != [hot_and_cool["dst_id"]]
    dst = row_for(p, hot_and_cool["dst_id"])
    assert "no free place" in dst["destination_blockers"] and dst["eligible_destination"] is False


def test_confirm_needs_a_batch_and_a_fridge_that_exist(client, tok):
    body = {"batch_id": 999999, "to_fridge_id": 1, "suggestion_id": "0" * 16}
    assert client.post("/api/ai/relocations/confirm", json=body,
                       headers=tok["admin"]).status_code == 404
    real = client.get("/api/batches", headers=tok["admin"]).json()[0]
    body.update(batch_id=real["id"], to_fridge_id=999999)
    assert client.post("/api/ai/relocations/confirm", json=body,
                       headers=tok["admin"]).status_code == 404
