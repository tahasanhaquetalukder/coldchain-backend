"""The 30-minute forecast, the breach warning, and the state that keeps the warning to one per episode.

Standard library only: this runs inside the process Render boots, where numpy is not in the image.
model.json is a plain description of a linear model or a set of nested decision lists, and the walk
below is checked by ml/evaluate.py against sklearn's own predict, so a deployment cannot quietly
serve forecasts from a model that reads differently from the one that was trained.
"""
import json
import os
import time

from . import features as F

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")
HORIZON_MIN = F.HORIZON_MIN
THRESHOLD_C = F.THRESHOLD_C
MAX_SLOPE_C_PER_MIN = 0.35     # a fridge does not move faster than this; noise must not become a trend
FALLBACK_BOUNDS_C = (-5.0, 30.0)
BREACH_COOLDOWN_S = 30 * 60    # never two rows for the same device inside half an hour
RISK_WATCH_MARGIN_C = 0.5      # one model error: ml/results.json measures the peak head's MAE at about
                               # 0.34 C, so a prediction inside this band of the line is not a promise
                               # that the box stays under it
_BREACH_SEEN = {}              # device_id -> {"raised": bool, "raised_ts": float}

_cache = {"path": None, "mtime": None, "model": None, "reason": ""}


def _tree(node, x):
    """A nested [feature, threshold, left, right] list, or a leaf number.

    A value equal to the threshold goes left, which is the rule sklearn's own trees use; anything
    else and the two disagree on exactly the samples that sit on a boundary.
    """
    while isinstance(node, list):
        node = node[3] if x[node[0]] > node[1] else node[2]
    return node


def _head_predict(head, x):
    if head["kind"] == "ridge":
        return head["intercept"] + sum(c * v for c, v in zip(head["coef"], x))
    if head["kind"] == "gbm":
        # leaf values were scaled by the learning rate on the way out of ml/train.py, so this is a sum
        return head["init"] + sum(_tree(t, x) for t in head["trees"])
    raise ValueError(f"unknown head kind {head['kind']!r}")


def load_model(path=None):
    """The trained model, or None with the reason it is not usable.

    The path is read from the module attribute on every call, not bound as a default, so a test (or a
    second model file) can point it elsewhere. Re-read when the file's mtime changes, which is what a
    redeploy does: a server must not serve forecasts from the model it booted with for the rest of
    its life. Any failure is a fallback, never an exception - a missing model costs a worse number,
    not the dashboard.
    """
    path = path or MODEL_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _cache.update(path=path, mtime=None, model=None, reason="no model file")
        return None
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["model"]
    model = None
    reason = ""
    try:
        with open(path, encoding="utf-8") as fh:
            candidate = json.load(fh)
        if not candidate.get("trained"):
            reason = "model file is a placeholder"
        elif list(candidate.get("feature_names") or []) != list(F.FEATURE_NAMES):
            # a model built for a different feature list would silently score the wrong numbers
            reason = "model file was trained on a different feature list"
        elif set(candidate["heads"]) != {"temp30", "max30"}:
            reason = "model file is missing a head"
        else:
            model = candidate
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = f"model file unreadable ({type(exc).__name__})"
    _cache.update(path=path, mtime=mtime, model=model, reason=reason)
    return model


def model_reason(path=None):
    path = path or MODEL_PATH
    if _cache["path"] != path or _cache["mtime"] is None:
        load_model(path)
    return _cache["reason"]


def _predict_both(model, vec):
    """(t+30 temperature, max over the next 30) after the scaler the model was fitted with."""
    mean, std = model["scaler"]["mean"], model["scaler"]["std"]
    z = [(v - m) / s for v, m, s in zip(vec, mean, std)]
    return (_head_predict(model["heads"]["temp30"], z), _head_predict(model["heads"]["max30"], z))


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def risk_of(peak_c):
    """low / watch / high for a fridge whose next-30-minute peak is `peak_c`.

    The three levels exist because a pharmacist and a relocation rule want different things from one
    number: the page needs a badge that says "look at this", and the rules need a fridge that is safe to
    move stock INTO - which is why a destination must be `low` and not merely `not high`. `watch` is the
    band within one model error of the line, where the forecast has not promised a breach but cannot
    promise against one either.
    """
    if peak_c > THRESHOLD_C:
        return "high"
    if peak_c > THRESHOLD_C - RISK_WATCH_MARGIN_C:
        return "watch"
    return "low"


def _episode(device_id, now_ts, at_risk, predicted_peak):
    """True once per breach episode, and never twice inside the cooldown.

    A forecast is polled, so without this the same five minutes of heat would become fifty audit rows
    and fifty Telegram messages. The hysteresis margin is why a value sitting on the line cannot
    alternate the flag: the episode only closes when the prediction is clearly back under it.
    """
    state = _BREACH_SEEN.setdefault(device_id, {"raised": False, "raised_ts": -BREACH_COOLDOWN_S})
    if len(_BREACH_SEEN) > 2048:
        _BREACH_SEEN.clear()
        state = _BREACH_SEEN.setdefault(device_id, {"raised": False, "raised_ts": -BREACH_COOLDOWN_S})
    newly = False
    if at_risk:
        if not state["raised"] and now_ts - state["raised_ts"] >= BREACH_COOLDOWN_S:
            state["raised"], state["raised_ts"], newly = True, now_ts, True
    elif predicted_peak < THRESHOLD_C - F.HYSTERESIS_C:
        state["raised"] = False
    return newly


def explain(f, forecast_c, peak_c):
    """Plain words for what the numbers are reacting to, newest signal first.

    Not the model's internals - a pharmacist cannot read a gradient-boosted tree, and the useful
    answer to "why does it think this will breach" is the state of the box, not the weights.
    """
    out = []
    if f["slope_15"] >= 0.05:
        out.append(f"warming {f['slope_15'] * 15:.1f} C over the last 15 minutes")
    elif f["slope_15"] <= -0.05:
        out.append(f"cooling {abs(f['slope_15']) * 15:.1f} C over the last 15 minutes")
    else:
        out.append("holding steady over the last 15 minutes")
    if f["above8_min"] >= 3:
        out.append(f"already above {THRESHOLD_C:.0f} C for {f['above8_min']:.0f} of the last 15 minutes")
    if f["door_min_15"] >= 3:
        out.append(f"door reported open {f['door_min_15']:.0f} of the last 15 minutes")
    if f["power_off_min_15"] >= 1:
        out.append(f"supply reported down {f['power_off_min_15']:.0f} of the last 15 minutes")
    if f["flags_known"] and f["duty_15"] >= 0.8:
        out.append(f"compressor ran {f['duty_15'] * 100:.0f}% of the observed minutes and the box is still warm")
    if forecast_c > THRESHOLD_C:
        out.append(f"predicted {forecast_c:.1f} C in {HORIZON_MIN} minutes")
    elif peak_c > THRESHOLD_C:
        out.append(f"peaks near {peak_c:.1f} C before the {HORIZON_MIN}-minute mark")
    return out


def forecast(rows, device_id="unknown", now_ts=None, episode=True):
    """The forecast for one node from its own readings.

    `rows` is (ts, temperature, compressor_on, door_open, power_ok) in any order - what /api/ai/*
    selects straight out of the table, because /api/readings caps at 600 rows and a five-second node
    only covers fifty minutes of history there.

    `episode=False` asks the same question without answering it twice. Raising a breach warning is a
    real event that spends the cooldown, so the routes that only want to know - the relocation rules,
    a page that is refreshing a badge - pass False and get the numbers with `breach_warning_raised`
    permanently False. Whoever does want to raise it passes True.
    """
    series = F.resample(rows)
    newest = series[-1]["ts"] if series else None
    now_ts = now_ts if now_ts is not None else (newest or time.time())
    f = F.features(series)
    base = {"device_id": device_id, "horizon_min": HORIZON_MIN, "threshold_c": THRESHOLD_C,
            "now_ts": newest, "model": "fallback", "reasons": [], "warnings": [], "risk": None}
    if f is None:
        run = F.run_length(series, len(series) - 1) if series else 0
        base.update(state="not enough data", minutes_of_history=run, minutes_needed=F.MIN_HISTORY_MIN,
                    now_c=None, forecast_c=None, max_next_30_c=None, breach=False, lead_min_est=None,
                    history=[{"ts": s["ts"], "c": round(s["temp"], 2)} for s in series[-60:]],
                    projection=[],
                    warnings=[f"this node has {run} contiguous minutes of readings; "
                              f"{F.MIN_HISTORY_MIN} are needed before a forecast means anything"])
        return base

    temp_now = f["temp_last"]
    model = load_model()
    if model is None:
        # persistence is useless here; the slope is the only thing a plain reading of the trace gives
        slope = _clamp(f["slope_15"], -MAX_SLOPE_C_PER_MIN, MAX_SLOPE_C_PER_MIN)
        forecast_c = _clamp(temp_now + slope * HORIZON_MIN, *FALLBACK_BOUNDS_C)
        peak_c = max(temp_now, forecast_c)
        base["warnings"].append(f"no usable trained model ({model_reason() or 'unknown'}); "
                                "this is a straight-line extrapolation of the last 15 minutes")
    else:
        try:
            forecast_c, peak_c = _predict_both(model, F.vector(f))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            # a model that cannot be evaluated is a missing model; the operator still gets a number
            slope = _clamp(f["slope_15"], -MAX_SLOPE_C_PER_MIN, MAX_SLOPE_C_PER_MIN)
            forecast_c = _clamp(temp_now + slope * HORIZON_MIN, *FALLBACK_BOUNDS_C)
            peak_c = max(temp_now, forecast_c)
            base["model"] = "fallback"
            base["warnings"].append(f"trained model could not be evaluated ({type(exc).__name__})")
        else:
            base["model"] = model["heads"]["temp30"]["kind"]
            base["data"] = model.get("data")
            # the peak head is the one that matters for a warning, so it cannot sit below the endpoint
            peak_c = max(peak_c, forecast_c, temp_now)

    breach = peak_c > THRESHOLD_C
    # a straight line from now to the endpoint crosses the threshold at a computable minute; anything
    # finer than that would be a curve the model never predicted
    lead = None
    if breach and forecast_c > temp_now and forecast_c > THRESHOLD_C:
        lead = round(_clamp((THRESHOLD_C - temp_now) / max(forecast_c - temp_now, 1e-6) * HORIZON_MIN, 0, HORIZON_MIN))
    elif breach:
        lead = 0
    base.update(state="forecast", minutes_of_history=int(f["history_min"]), now_c=round(temp_now, 2),
                forecast_c=round(forecast_c, 2), max_next_30_c=round(peak_c, 2), breach=breach,
                risk=risk_of(peak_c), lead_min_est=lead,
                history=[{"ts": s["ts"], "c": round(s["temp"], 2)} for s in series[-60:]],
                projection=[{"ts": now_ts if newest is None else newest + step * 60,
                             "c": round(temp_now + (forecast_c - temp_now) * step / HORIZON_MIN, 2)}
                            for step in range(5, HORIZON_MIN + 1, 5)],
                reasons=explain(f, forecast_c, peak_c))
    # a read-only caller must not be able to spend the episode: the warning belongs to whoever raises it
    base["breach_warning_raised"] = bool(episode) and _episode(device_id, now_ts, breach, peak_c)
    return base
