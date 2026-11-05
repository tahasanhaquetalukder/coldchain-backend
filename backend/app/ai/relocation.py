"""Relocation: which batches should leave which fridge, and why.

Standard library only, and deliberately not a model. A pharmacist is being asked to press a button that
moves live vaccine, so every decision here is a rule written out in the open, with the numbers that
triggered it in the sentence - not a weight nobody can argue with. `ml/` trains the forecast that
feeds these rules; nothing in this file reads a model.

The caller (app.main) supplies one dict per fridge holding everything the rules need:

    id, device_id, name, online, power_ok, door_open, temperature
    risk        'low' / 'watch' / 'high' / None, straight from predict.forecast()
    score       the compressor health score, or None when there are too few cycles to have one
    batches     [{id, code, vaccine, expiry, remaining_min, remaining_pct, status}, ...]

This module never touches a database, a clock that matters, or a session: `suggest()` is a pure function
of those dicts and a capacity number, which is what lets the confirm route recompute the answer and
compare it against what the browser was shown.
"""
import hashlib
import time

from . import features as F

WEAK_SCORE = 50            # a compressor this tired is on its own a reason to take stock out
SUGGESTION_TTL_S = 600     # ten minutes: longer than a page refresh, shorter than a shift
COOL_UNKNOWN = 99.0        # an unseen temperature ranks as the warmest possible, never the coolest
UNKNOWN_HEALTH_RANK = 200.0    # past a fridge that has been measured and is entirely broken (100 - 0)


def _window(now):
    """The clock bucket ids are minted in. Buckets, not timestamps, so an id is reproducible."""
    return int(now // SUGGESTION_TTL_S)


def _digest(batch_id, from_id, to_id, window):
    raw = f"{batch_id}|{from_id}|{to_id}|{window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def suggestion_id(batch_id, from_id, to_id, now=None):
    """An id that is not stored anywhere.

    Suggestions are computed fresh on every request, so a confirm has to be able to prove it is acting
    on the same recommendation the page is showing without a table to keep them in. The id is a digest
    of the batch, the two fridges and the current window: recompute, compare, and a client cannot
    invent an id or replay one it read ten minutes ago.
    """
    now = time.time() if now is None else now
    return _digest(batch_id, from_id, to_id, _window(now))


def suggestion_is_current(batch_id, from_id, to_id, sid, now=None):
    """Whether `sid` is still the id this move carries.

    The previous window counts as current. Without that, a card opened two seconds before a rollover
    would be refused two seconds later for no reason connected to the fridges at all - the server had
    simply changed the bucket it hashes. That costs at most one extra window of staleness (ten
    minutes), which is why `expires_at` below promises the shorter, honest interval.
    """
    now = time.time() if now is None else now
    window = _window(now)
    return sid == _digest(batch_id, from_id, to_id, window) or \
        sid == _digest(batch_id, from_id, to_id, window - 1)


def breach_now(st):
    """The box is over the line right now, not merely predicted to get there.

    Read off the newest temperature rather than off the forecast, because a node with no history has
    no forecast and a fridge sitting at 11 C does not need one to be a bad place for stock.
    """
    return st.get("temperature") is not None and st["temperature"] > F.THRESHOLD_C


def risk_reasons(st):
    """Every rule that flags this fridge as somewhere stock should leave, with its numbers.

    Empty means the fridge is not at risk. Three separate reasons are collected rather than the first
    one found: a fridge that is both hot and has a dying compressor should be described as both.
    """
    out = []
    if st.get("risk") == "high":
        peak, temp, lead = st.get("max_next_30_c"), st.get("temperature"), st.get("lead_min_est")
        if peak is None:
            words = "forecast risk high"
        elif temp is not None and peak > temp:
            words = f"predicted to pass {F.THRESHOLD_C:g} C (peak {peak} C)"
        else:
            words = f"already over {F.THRESHOLD_C:g} C, at {temp} C"
        if lead:
            # lead 0 is the 'it is already over the line' answer, which the sentence above says better
            words += f" in about {lead} min"
        out.append(words)
    score = st.get("score")
    if score is not None and score < WEAK_SCORE:
        out.append(f"compressor health {score}/100")
    if breach_now(st):
        out.append(f"reporting {st['temperature']} C now")
    return out


def destination_blockers(st, free_slots):
    """Why this fridge may not receive stock, in the order the rules are asked.

    Every one of these is a fact the node itself reported. An empty list is the only answer that makes
    a fridge eligible, which is why the reason a suggestion carries names the numbers and not a score.
    """
    out = []
    if not st.get("online"):
        out.append("offline")
    if st.get("power_ok") is False:
        out.append("not on mains")
    if st.get("door_open"):
        out.append("door open")
    risk = st.get("risk")
    if risk is None:
        out.append("no forecast yet")
    elif risk != "low":
        out.append(f"forecast risk {risk}")
    score = st.get("score")
    if score is not None and score < WEAK_SCORE:
        out.append(f"compressor health {score}/100")
    if free_slots <= 0:
        out.append("no free place")
    return out


def _health_words(st):
    score = st.get("score")
    return "health not yet measured" if score is None else f"health {score}/100"


def _temp_words(st):
    return "temperature unknown" if st.get("temperature") is None else f"{st['temperature']} C"


def _ranked_destinations(candidates):
    """Coolest first, then the fridge we know is healthy before the one we have never measured, then
    lowest id so the order never depends on dict luck.

    An unknown score is allowed as a destination - most new nodes have one - but a fridge that has been
    watched for a week and scores 96 is the better answer when both are the same temperature.
    """
    return sorted(candidates, key=lambda st: (
        COOL_UNKNOWN if st.get("temperature") is None else st["temperature"],
        100.0 - st["score"] if st.get("score") is not None else UNKNOWN_HEALTH_RANK,
        st["id"]))


def suggest(states, capacity=6, now=None):
    """The moves a pharmacist should be offered right now, plus the batches that have nowhere to go.

    `capacity` is how many batches a fridge is assumed to be able to hold: a number the operator sets
    per site (MAX_BATCHES_PER_FRIDGE), not one this code could measure. It is applied to the count of
    batches currently stored there, so a destination that is already full is not a destination.

    An at-risk fridge's batches are offered up in order of least remaining heat budget first, then
    earliest expiry - the stock that can afford to wait waits, and the first destination on the list is
    the one the most urgent batch gets.

    Nothing is ever suggested into a fridge that fails a rule. If no destination qualifies the batch
    appears under `unplaced` with the reason, because 'stay where you are and call somebody' is the
    correct answer and a move into a warm fridge is not.
    """
    now = time.time() if now is None else now
    fridges = []
    for st in states:
        batches = st.get("batches") or []
        reasons = risk_reasons(st)
        free = max(0, capacity - len(batches))
        blockers = destination_blockers(st, free)
        if reasons:
            # "not itself at risk" is a rule like the others, so it is reported as one: a fridge whose own
            # stock needs rescuing is not a rescue destination.
            blockers.append(f"itself flagged for relocation: {'; '.join(reasons)}")
        fridges.append({**st, "batches": batches, "at_risk": bool(reasons), "risk_reasons": reasons,
                        "free_slots": free, "destination_blockers": blockers})

    destinations = _ranked_destinations([f for f in fridges if not f["destination_blockers"]])
    risky = sorted([f for f in fridges if f["at_risk"]],
                   key=lambda f: (min([b["remaining_min"] for b in f["batches"]], default=0), f["id"]))

    room = {f["id"]: f["free_slots"] for f in destinations}
    suggestions, unplaced = [], []
    for src in risky:
        for b in sorted(src["batches"], key=lambda b: (b["remaining_min"], b["expiry"], b["id"])):
            dst = next((d for d in destinations if d["id"] != src["id"] and room[d["id"]] > 0), None)
            if dst is None:
                unplaced.append({"batch_id": b["id"], "batch_code": b["code"], "vaccine": b["vaccine"],
                                 "expiry": b["expiry"], "remaining_min": b["remaining_min"],
                                 "from_fridge_id": src["id"], "from_fridge_name": src["name"],
                                 "from_risk": src["risk"], "from_reasons": src["risk_reasons"],
                                 "why": _why_none(src, fridges, room)})
                continue
            # quoted before it is spent, so the number on the card is the room the batch arrives at
            free_before = room[dst["id"]]
            room[dst["id"]] -= 1
            suggestions.append({
                "suggestion_id": suggestion_id(b["id"], src["id"], dst["id"], now),
                "batch_id": b["id"], "batch_code": b["code"], "vaccine": b["vaccine"],
                "expiry": b["expiry"], "batch_status": b["status"],
                "remaining_min": b["remaining_min"], "remaining_pct": b["remaining_pct"],
                "from_fridge_id": src["id"], "from_fridge_name": src["name"],
                "from_risk": src["risk"], "from_reasons": src["risk_reasons"],
                "to_fridge_id": dst["id"], "to_fridge_name": dst["name"],
                "to_temperature": dst.get("temperature"), "to_risk": dst.get("risk"),
                "to_score": dst.get("score"), "to_free_slots": free_before,
                "capacity": capacity,
                "created_at": round(now, 2), "expires_at": round(now + SUGGESTION_TTL_S, 2),
                "ttl_s": SUGGESTION_TTL_S,
                "reason": _reason(b, src, dst, capacity, free_before),
            })
    return {"generated_at": round(now, 2), "capacity_per_fridge": capacity,
            "threshold_c": F.THRESHOLD_C, "weak_score": WEAK_SCORE,
            "suggestion_ttl_s": SUGGESTION_TTL_S,
            "count": len(suggestions), "suggestions": suggestions, "unplaced": unplaced,
            "at_risk_fridges": [f["id"] for f in risky],
            "eligible_destinations": [d["id"] for d in destinations],
            "fridges": [{"id": f["id"], "name": f["name"], "device_id": f["device_id"],
                         "online": f.get("online"), "power_ok": f.get("power_ok"),
                         "door_open": f.get("door_open"), "temperature": f.get("temperature"),
                         "risk": f.get("risk"), "score": f.get("score"), "band": f.get("band"),
                         "at_risk": f["at_risk"], "risk_reasons": f["risk_reasons"],
                         "batch_count": len(f["batches"]), "free_slots": f["free_slots"],
                         "eligible_destination": not f["destination_blockers"],
                         "destination_blockers": f["destination_blockers"]}
                        for f in fridges],
            "message": _summary(risky, suggestions, unplaced)}


def _reason(b, src, dst, capacity, free_before):
    """One sentence, every number in it, so the card can be argued with before the button is pressed."""
    return (f"move {b['code']} out of {src['name']} ({'; '.join(src['risk_reasons'])}) into "
            f"{dst['name']}, which is {_temp_words(dst)} with forecast risk {dst.get('risk')}, "
            f"{_health_words(dst)} and {free_before} of {capacity} places free; "
            f"{b['code']} has {b['remaining_min']} of its heat-budget minutes left")


def _why_none(src, fridges, room):
    """The honest 'nowhere to go', naming each other fridge and the rule that ruled it out.

    The alternative is silence, and silence on a page whose headline is a warning reads as 'nothing is
    wrong' to whoever is holding the phone during an outage.
    """
    others = [f for f in fridges if f["id"] != src["id"]]
    if not others:
        return (f"nowhere to move it: {src['name']} is the only registered fridge, and its stock is at "
                f"risk ({'; '.join(src['risk_reasons'])})")
    parts = []
    for f in sorted(others, key=lambda f: f["id"]):
        blockers = list(f["destination_blockers"])
        if not blockers and room.get(f["id"], 0) <= 0:
            # eligible on its own merits, but this function is being asked after its room was spent on
            # the batches that were more urgent than this one
            blockers = ["every free place is already promised to a more urgent batch"]
        parts.append(f"{f['name']}: {'; '.join(blockers)}")
    return (f"no other fridge qualifies as a destination - {'; '.join(parts)}")


def _summary(risky, suggestions, unplaced):
    if not risky:
        return "no fridge is currently at risk, so nothing needs to be moved"
    if not suggestions:
        return (f"{len(risky)} fridge(s) are at risk and {len(unplaced)} batch(es) have nowhere to go: "
                "no other fridge qualifies as a destination")
    if unplaced:
        return (f"{len(suggestions)} move(s) suggested; {len(unplaced)} batch(es) have nowhere eligible "
                "to go and are listed under unplaced")
    return f"{len(suggestions)} move(s) suggested from {len(risky)} at-risk fridge(s)"
