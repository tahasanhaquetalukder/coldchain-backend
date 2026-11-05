#!/usr/bin/env python3
"""Score the shipped model on the simulated streams, and prove the server reads it correctly.

Four things happen here, in this order:

  1. the windows ml/train.py fitted are rebuilt by calling train.collect() and train.time_split(),
     so a metric can never be measured on a matrix the trainer did not use;
  2. the standard-library walk in backend/app/ai/predict.py is compared against sklearn's own
     predict. The deployed image has no sklearn, so if the two ever disagree, every accuracy number
     in this file describes a model the server is not actually running;
  3. the regression and breach-warning metrics are computed from the server's own predictions, next
     to the same metrics for the no-model straight line - "the model works" is only a useful
     sentence beside "and it beats reading the last fifteen minutes with a ruler";
  4. the compressor health score is rolled forward through each stream, six hours at a time, to see
     whether it falls on the wearing compressor and stays put on the healthy one. It is a rule and
     not a fitted model, so there is no accuracy to claim here - only direction, and the rate at
     which it cries "weak" about a fridge that was never given a fault.

The data is SIMULATED by ml/generate_data.py and no row of it came from a fridge, so these figures
describe the pipeline end to end and nothing about a real installation. Nothing here is typed into a
document: the script prints every number and writes the same set to ml/results.json.

    ml/.venv/Scripts/python.exe ml/evaluate.py
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, HERE)

from app.ai import compressor as C   # noqa: E402  the health score being checked, as the server runs it
from app.ai import features as F   # noqa: E402  the feature definitions the server uses
from app.ai import predict as P    # noqa: E402  the walk being checked, and the fallback compared against
import train as T                  # noqa: E402  collect()/time_split()/read_rows(): one builder, both scripts

RESULTS_PATH = os.path.join(HERE, "results.json")
MINUTES_PER_DAY = 1440
EPISODE_MIN_MIN = 3        # a crossing shorter than this is sensor chatter, not a breach
EPISODE_GAP_MIN = 2        # ... unless it dips back for at most this long, which is still one episode
WALK_TOLERANCE_C = 0.02    # a window differing by less than this is a boundary, not a wrong model
WALK_RMSE_TOLERANCE_C = 0.001     # the walk must reproduce the trained model's own accuracy
WALK_OVER_SHARE = 0.001    # ... and the boundary windows must stay one in a thousand
COL = {name: k for k, name in enumerate(F.FEATURE_NAMES)}   # which column of the matrix is which feature


def _ratio(num, den, digits=4):
    return None if not den else round(num / den, digits)


def _stats(pred, actual):
    err = np.asarray(pred, dtype=float) - np.asarray(actual, dtype=float)
    return {"mae_c": round(float(np.mean(np.abs(err))), 4),
            "rmse_c": round(float(np.sqrt(np.mean(err ** 2))), 4),
            "bias_c": round(float(np.mean(err)), 4), "n": int(len(err))}


def _f1(precision, recall):
    if precision is None or recall is None:
        return None
    return None if not (precision + recall) else round(2 * precision * recall / (precision + recall), 4)


def confusion(pred_breach, actual_breach):
    """Precision, recall and F1 for "this box will be over the line inside the horizon".

    One sample is one minute-window, so a nine-minute breach contributes nine positives; the
    per-episode numbers in episodes_on_test are the ones to quote to an operator.
    """
    p, a = np.asarray(pred_breach, dtype=bool), np.asarray(actual_breach, dtype=bool)
    tp, fp = int(np.count_nonzero(p & a)), int(np.count_nonzero(p & ~a))
    fn, tn = int(np.count_nonzero(~p & a)), int(np.count_nonzero(~p & ~a))
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": _f1(precision, recall)}


def scale(model, vec):
    """The exported z-score, in one place, so nothing can drift from what predict.py does."""
    mean, std = model["scaler"]["mean"], model["scaler"]["std"]
    return [(v - m) / s for v, m, s in zip(vec, mean, std)]


def server_predictions(model, x):
    """Both heads for every window, through backend/app/ai/predict.py - the code Render runs."""
    out = np.empty((len(x), 2), dtype=float)
    for k, vec in enumerate(x):
        out[k][0], out[k][1] = P._predict_both(model, list(vec))
    return out


def walk_check(name, model, mine, x, y, train_idx, test_idx, mean, std):
    """sklearn's predict against the exported walk, on the identical learner and the same rows.

    The trees here are the ones train.py flattened: GradientBoostingRegressor is deterministic at
    random_state=0 on the same data with the same parameters, so a difference is the export - a lost
    leaf, a wrong scaling, a feature order mistake - which is the failure this catches.

    It does not demand bit-identical numbers. sklearn casts the feature matrix to float32 before it
    walks its trees and compares those against its float64 thresholds, so a sample lying within half
    a float32 step of a split can take a different branch from the one the exported walk takes;
    rounding the walk's inputs to float32 as well was measured here and made the residue larger
    rather than smaller, so what remains is a boundary effect and not a mis-read model. What has to
    hold is that the walk still reproduces the trained model's accuracy: its test RMSE may not
    separate from sklearn's, and the boundary windows have to stay one in a thousand. A lost leaf or
    a swapped feature order breaks both at once, loudly.
    """
    head = model["heads"][name]
    if head["kind"] != "gbm":
        return {"head": name, "kind": head["kind"], "checked": False,
                "note": "the exported head is not a boosted model, so there are no trees to compare"}
    zx = (x - mean) / std
    gbm = GradientBoostingRegressor(**(head.get("params") or T.GBM_PARAMS)).fit(zx[train_idx], y[train_idx])
    mine, theirs, truth = np.asarray(mine, dtype=float), gbm.predict(zx[test_idx]), y[test_idx]
    diff = np.abs(mine - theirs)
    over = int(np.count_nonzero(diff > WALK_TOLERANCE_C))
    r_walk = float(np.sqrt(np.mean((mine - truth) ** 2)))
    r_sklearn = float(np.sqrt(np.mean((theirs - truth) ** 2)))
    share = over / len(diff)
    return {"head": name, "kind": "gbm", "checked": True, "windows": int(len(diff)),
            "max_abs_diff_c": round(float(diff.max()), 6),
            "mean_abs_diff_c": round(float(diff.mean()), 6),
            "tolerance_c": WALK_TOLERANCE_C, "windows_over_tolerance": over,
            "share_over_tolerance": round(share, 6),
            "test_rmse_walk_c": round(r_walk, 6), "test_rmse_sklearn_c": round(r_sklearn, 6),
            "rmse_gap_c": round(abs(r_walk - r_sklearn), 6),
            "ok": bool(abs(r_walk - r_sklearn) < WALK_RMSE_TOLERANCE_C and share <= WALK_OVER_SHARE)}


def episode_runs(minutes, hot, alarm, horizon_min):
    """Breach episodes in one stream's test minutes, with the lead time the model really gave.

    `minutes` are one stream's contiguous epoch-minutes inside the test split, `hot` is the box
    measured over the line and `alarm` is the model predicting a crossing inside its horizon. An
    episode is a maximal run of hot minutes, joined across a dip of EPISODE_GAP_MIN or less and
    discarded under EPISODE_MIN_MIN. The lead is the onset minute minus the earliest alarm at or
    before the onset, searched back only as far as the horizon - a warning the model never claimed
    to give cannot be credited to it, and a warning after the crossing is not a warning.
    """
    out, i, n = [], 0, len(minutes)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        k, last = i + 1, i
        while k < n:
            if hot[k]:
                last = k
            elif minutes[k] - minutes[last] > EPISODE_GAP_MIN:
                break
            k += 1
        length = int(minutes[last] - minutes[i] + 1)
        if length >= EPISODE_MIN_MIN:
            window = np.arange(int(np.searchsorted(minutes, minutes[i] - horizon_min)), i + 1)
            hits = window[alarm[window]]
            out.append({"onset_minute": int(minutes[i]), "length_min": length,
                        "lead_min": int(minutes[i] - minutes[int(hits[0])]) if len(hits) else None})
        i = last + 1
    return out


def runs_of_true(flags, minutes):
    """Count maximal stretches of True, so one long false alarm is one event and not forty."""
    return int(sum(1 for k in range(len(flags)) if flags[k] and
                   (k == 0 or not flags[k - 1] or minutes[k] - minutes[k - 1] > 1)))


def forward(path):
    """A path that reads the same on the laptop that made it and the machine that reads the report."""
    return path.replace("\\", "/")


# ---------- the compressor health score, rolled across each stream ----------
HEALTH_FIRST_MIN = 1440    # a day of history before a rolling point means anything
HEALTH_ROLL_MIN = 360      # then one point every six hours
HEALTH_EDGES = 3           # start and end are medians of this many points, not one lucky cycle
HEALTH_DROP_POINTS = 10    # a wearing machine must move at least this far between the two edges
HEALTH_FALSE_WEAK_MAX = 0.05   # and a healthy one must be called weak on at most 5 % of its points


def health_points(rows):
    """The score as it would have read at each cut, from the rows up to that cut.

    score() takes its baseline from the earliest share of the cycles it is given and compares it with
    the newest, so feeding it history up to a point in time is the same question an operator asks the
    page on that morning - not a rerun of the whole week's data with the ending hidden.
    """
    out = []
    first, last = int(rows[0][0] // 60), int(rows[-1][0] // 60)
    for cut in range(first + HEALTH_FIRST_MIN, last, HEALTH_ROLL_MIN):
        rep = C.score([r for r in rows if r[0] <= cut * 60], device_id="roll")
        if rep["score"] is not None:
            out.append({"minute_of_stream": cut - first, "score": rep["score"], "band": rep["band"],
                        "cycles_used": rep["cycles_used"], "trend": rep["trend"]["state"],
                        "reasons": rep["reasons"]})
    return out


def _edge(points, at_start):
    half = points[:HEALTH_EDGES] if at_start else points[-HEALTH_EDGES:]
    return float(np.median([p["score"] for p in half])) if half else None


def health_over_time(paths):
    """Per scenario: where the score started, where it ended, and how often it called a healthy
    fridge weak. Nothing here is fitted - the score is a rule, so the honest claim is direction."""
    by_scenario = {}
    for path in paths:
        name, scenario = T.stream_label(path)
        points = health_points(T.read_rows(path))
        if len(points) < 2 * HEALTH_EDGES:
            by_scenario.setdefault(scenario, []).append({"stream": name, "points": points,
                                                        "note": "too few rolling points to compare edges"})
            continue
        start, end = _edge(points, True), _edge(points, False)
        weak = sum(1 for p in points if p["band"] == "weak")
        by_scenario.setdefault(scenario, []).append({
            "stream": name, "start_score": start, "end_score": end, "fall_points": round(start - end, 2),
            "min_score": min(p["score"] for p in points), "max_score": max(p["score"] for p in points),
            "points": len(points), "points_in_weak_band": weak,
            "scores": [p["score"] for p in points], "final_reasons": points[-1]["reasons"]})
    summary = {}
    for scenario, streams in by_scenario.items():
        full = [s for s in streams if "start_score" in s]
        if not full:
            summary[scenario] = {"streams": len(streams), "note": "no stream had enough cycles"}
            continue
        pts = sum(s["points"] for s in full)
        summary[scenario] = {
            "streams": len(streams), "rolling_points": pts,
            "start_score": round(float(np.mean([s["start_score"] for s in full])), 2),
            "end_score": round(float(np.mean([s["end_score"] for s in full])), 2),
            "mean_fall_points": round(float(np.mean([s["fall_points"] for s in full])), 2),
            "lowest_score_seen": min(s["min_score"] for s in full),
            "highest_score_seen": max(s["max_score"] for s in full),
            "points_in_weak_band": sum(s["points_in_weak_band"] for s in full),
            "share_of_points_weak": _ratio(sum(s["points_in_weak_band"] for s in full), pts),
            "per_stream": {s["stream"]: {"start": s["start_score"], "end": s["end_score"],
                                        "scores": s["scores"]} for s in full}}
    return summary


def health_checks(summary):
    """Two claims worth failing a run over, stated as pass or fail rather than as a number to squint at.

    Both compare against None, not falsiness: a score of 0 and a false-weak share of 0 are the two
    most interesting values this table can produce, and `or` would read both as missing.
    """
    weak, norm = summary.get("weak_compressor"), summary.get("normal")
    drop = None if not weak or weak.get("mean_fall_points") is None else weak["mean_fall_points"]
    share = None if not norm else norm.get("share_of_points_weak")
    return [
        {"check": "the score falls on a weakening compressor",
         "expected": f"start minus end at least {HEALTH_DROP_POINTS:g} points",
         "measured": (f"{weak['start_score']} then {weak['end_score']}, a fall of {drop} points"
                      if drop is not None else "no stream scored"),
         "ok": drop is not None and drop >= HEALTH_DROP_POINTS},
        {"check": "a healthy compressor is not called weak",
         "expected": f"at most {HEALTH_FALSE_WEAK_MAX:.0%} of rolling points in the weak band",
         "measured": (f"{norm['points_in_weak_band']} of {norm['rolling_points']} points = {share:.1%}"
                      if share is not None else "no stream scored"),
         "ok": share is not None and share <= HEALTH_FALSE_WEAK_MAX}]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", action="append", help="streams to score; default is every ml/data/sim-*.csv")
    ap.add_argument("--model", default=os.path.join(ROOT, "backend", "app", "ai", "model.json"))
    ap.add_argument("--out", default=RESULTS_PATH)
    ap.add_argument("--horizon", type=int, default=F.HORIZON_MIN, help="how far back an alarm may be found")
    a = ap.parse_args(argv)

    started = time.time()
    paths = a.csv or sorted(os.path.join(T.DATA_DIR, n) for n in os.listdir(T.DATA_DIR)
                            if n.startswith("sim-") and n.endswith(".csv"))
    if not paths:
        print("no streams to score. Run ml/generate_data.py first (see ml/README.md).")
        return 1
    model = P.load_model(a.model)
    if model is None:
        print(f"{a.model}: {P.model_reason(a.model)} - nothing to evaluate. Run ml/train.py first.")
        return 1
    threshold = float(F.THRESHOLD_C)
    if float(model["threshold_c"]) != threshold:
        print(f"NOTE the model file was trained for {model['threshold_c']:g} C and the server warns at "
              f"{threshold:g} C; the server wins, because the server is what an operator reads")

    print(f"scoring {len(paths)} stream(s) against {os.path.relpath(a.model, ROOT)}, "
          f"features from backend/app/ai/features.py")
    w = T.collect(paths)
    x, yt, ym = np.array(w.x, dtype=float), w.temp, w.peak
    if len(x) < 200:
        print(f"only {len(x)} windows: these numbers would describe plumbing, not accuracy")
    train_idx, _val, test_idx, (w1, w2, purged) = T.time_split(w)
    mins = w.minute[test_idx]
    names, scen = np.array(w.stream)[test_idx], np.array(w.scenario)[test_idx]
    print(f"{len(x)} windows; test split = {len(test_idx)} windows from epoch-minute {w2} on, "
          f"{purged} rows purged at the two walls")

    server = server_predictions(model, x[test_idx])
    reg = {"temp30": _stats(server[:, 0], yt[test_idx]), "max30": _stats(server[:, 1], ym[test_idx])}
    breach = confusion(server[:, 1] > threshold, ym[test_idx] > threshold)

    # the same questions with no trained model at all, from the same rows
    slope = np.clip(x[test_idx][:, COL["slope_15"]], -P.MAX_SLOPE_C_PER_MIN, P.MAX_SLOPE_C_PER_MIN)
    base_temp = np.clip(x[test_idx][:, COL["temp_last"]] + slope * F.HORIZON_MIN, *P.FALLBACK_BOUNDS_C)
    base_peak = np.maximum(x[test_idx][:, COL["temp_last"]], base_temp)
    reg["fallback_temp30"] = _stats(base_temp, yt[test_idx])
    reg["fallback_max30"] = _stats(base_peak, ym[test_idx])
    breach["fallback"] = confusion(base_peak > threshold, ym[test_idx] > threshold)

    alarm_test, hot_test = server[:, 1] > threshold, ym[test_idx] > threshold
    fp_test = alarm_test & ~hot_test
    days, fp_minutes, fp_events = {}, {}, {}
    for name in dict.fromkeys(names):
        sel = names == name
        s = scen[sel][0]
        minutes_here = mins[sel]
        # fridge-days are minutes of one fridge's data divided by 1440, which keeps a partial day at
        # the wall from being counted as a whole one and quietly halving the reported rate
        days[s] = days.get(s, 0.0) + len(minutes_here) / MINUTES_PER_DAY
        fp_minutes[s] = fp_minutes.get(s, 0) + int(np.count_nonzero(fp_test[sel]))
        fp_events[s] = fp_events.get(s, 0) + runs_of_true(fp_test[sel], minutes_here)
    breach["false_alarm_events_in_test"] = sum(fp_events.values())
    breach["fridge_days_in_test"] = round(sum(days.values()), 3)
    breach["false_alarms_per_fridge_day"] = _ratio(breach["false_alarm_events_in_test"],
                                                  sum(days.values()))
    breach["per_scenario"] = {s: {"fridge_days": round(days[s], 3), "false_alarm_minutes": fp_minutes[s],
                                  "false_alarm_events": fp_events[s],
                                  "events_per_fridge_day": _ratio(fp_events[s], days[s])}
                              for s in sorted(days)}
    breach["note"] = ("one sample is one minute-window, so a nine-minute breach is nine positives; "
                      "episodes_on_test holds the per-fridge numbers")

    per_scn = {}
    for path in paths:
        scenario = T.stream_label(path)[1]
        series = F.resample(T.read_rows(path))
        grid, hot, alarm = [], [], []
        for i in range(len(series)):
            if series[i]["minute"] < w2:
                continue
            f = F.features(series, i)
            if f is None:
                continue
            grid.append(series[i]["minute"])
            hot.append(series[i]["temp"] > threshold)
            alarm.append(P._head_predict(model["heads"]["max30"], scale(model, F.vector(f))) > threshold)
        per_scn.setdefault(scenario, []).extend(
            episode_runs(np.array(grid, dtype=int), np.array(hot), np.array(alarm), a.horizon))
    episodes = {}
    for scenario in sorted(per_scn):
        eps, leads = per_scn[scenario], [e["lead_min"] for e in per_scn[scenario] if e["lead_min"] is not None]
        episodes[scenario] = {"episodes": len(eps), "detected": len(leads), "missed": len(eps) - len(leads),
                              "alarmed_at_onset": sum(1 for v in leads if v == 0),
                              "alarmed_early": sum(1 for v in leads if v > 0),
                              "mean_lead_min": _ratio(sum(leads), len(leads), 2),
                              "min_lead_min": min(leads) if leads else None,
                              "max_lead_min": max(leads) if leads else None,
                              "mean_length_min": _ratio(sum(e["length_min"] for e in eps), len(eps), 2)}
    all_eps = [e for eps in per_scn.values() for e in eps]
    all_leads = [e["lead_min"] for e in all_eps if e["lead_min"] is not None]
    episodes["overall"] = {"episodes": len(all_eps), "detected": len(all_leads),
                           "missed": len(all_eps) - len(all_leads),
                           "alarmed_early": sum(1 for v in all_leads if v > 0),
                           "mean_lead_min": _ratio(sum(all_leads), len(all_leads), 2)}

    mean, std = x[train_idx].mean(axis=0), x[train_idx].std(axis=0)
    std = np.where(std == 0, 1.0, std)
    walk = [walk_check(n, model, server[:, k], x, y, train_idx, test_idx, mean, std)
            for n, y, k in (("temp30", yt, 0), ("max30", ym, 1))]
    bad = [c for c in walk if c["checked"] and not c["ok"]]

    health = health_over_time(paths)
    checks = health_checks(health)
    bad += [c for c in checks if not c["ok"]]

    results = {
        "generated_by": "ml/evaluate.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_seconds": round(time.time() - started, 1),
        "model": {"path": forward(os.path.relpath(a.model, ROOT)), "bytes": os.path.getsize(a.model),
                  "generated_at": model.get("generated_at"), "seed": model.get("seed"),
                  "trained_on_windows": model.get("windows"),
                  "heads": {k: v["kind"] for k, v in model["heads"].items()},
                  "rmse_c_reported_by_train": {k: v.get("test_rmse") for k, v in model["heads"].items()},
                  "selection": model.get("selection")},
        "data": {"streams": len(paths), "scenarios": sorted(set(w.scenario)), "windows": len(x),
                 "source": "SIMULATED by ml/generate_data.py --seed %s. No row came from a device."
                           % model.get("seed")},
        "split": {"train": len(train_idx), "test": len(test_idx), "walls_at_epoch_minute": [w1, w2],
                  "purged_rows_at_walls": purged, "purge_min": F.HORIZON_MIN,
                  "alarm_searched_back_min": a.horizon, "threshold_c": threshold,
                  "episode_min_minutes": EPISODE_MIN_MIN, "episode_gap_minutes": EPISODE_GAP_MIN},
        "regression_on_test": reg,
        "breach_on_test": breach,
        "episodes_on_test": episodes,
        "compressor_health": {"method": f"backend/app/ai/compressor.py score(), re-run on the rows up to "
                              f"each cut, one cut every {HEALTH_ROLL_MIN} minutes from minute "
                              f"{HEALTH_FIRST_MIN} of the stream",
                              "edges_are_medians_of": HEALTH_EDGES,
                              "per_scenario": health, "checks": checks},
        "stdlib_walk_check": walk,
        "honesty": [
            "the streams scored here come from the same generator, physics and seed as the ones the "
            "model was fitted on; they are separated by a wall in time plus a purge, not by a "
            "different process",
            "no row in this file came from a real fridge, so no number here is a real-fridge accuracy",
            "metrics are computed from the standard-library walk in backend/app/ai/predict.py, which "
            "is the code the deployed backend runs, not from sklearn",
            "normal and weak_compressor never cross the line in the generator, so for those streams "
            "the only thing measured is how often the model cries wolf",
            "a minute-window is one sample, so the precision and recall above weigh a long breach "
            "many times; the episode table weighs each breach once",
            "the exported walk and sklearn do not agree bit for bit - sklearn walks its trees on a "
            "float32 copy of the features, so a few windows per head take the other branch at a "
            "split. stdlib_walk_check prints the gap and the run fails if it grows",
            "compressor_health is a rule, not a fitted model: it has no held-out set and no accuracy "
            "to quote. What is measured is direction (does it fall on the stream where the pull "
            "decays) and the false-alarm rate on the streams that were never given a fault",
            "the health score's baseline is a fridge's own earliest cycles, so it measures drift away "
            "from the start of stored history: a compressor installed already worn, or one whose "
            "history was wiped, is graded against its own bad behaviour and reads healthy. Nothing in "
            "this data can show that limitation, because every stream starts at full pull",
        ],
    }
    blob = json.dumps(results, indent=2)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(blob)

    print(f"\ntemperature on the test split ({reg['temp30']['n']} minute-windows)")
    for k in ("temp30", "max30"):
        print(f"  {k:<12} MAE {reg[k]['mae_c']:.3f} C  RMSE {reg[k]['rmse_c']:.3f} C  "
              f"bias {reg[k]['bias_c']:+.3f} C")
    for k in ("fallback_temp30", "fallback_max30"):
        print(f"  {k:<16} MAE {reg[k]['mae_c']:.3f} C  RMSE {reg[k]['rmse_c']:.3f} C  (no trained model)")
    print(f"\nbreach warning: over {threshold:g} C inside {a.horizon} min, counted per minute-window")
    print(f"  true {breach['tp']}   false alarm {breach['fp']}   missed {breach['fn']}   "
          f"correctly quiet {breach['tn']}")
    print(f"  precision {breach['precision']}   recall {breach['recall']}   F1 {breach['f1']}")
    print(f"  the straight line with no model: precision {breach['fallback']['precision']} "
          f"recall {breach['fallback']['recall']}")
    print(f"  false alarms: {breach['false_alarm_events_in_test']} events over "
          f"{breach['fridge_days_in_test']} fridge-days = "
          f"{breach['false_alarms_per_fridge_day']} per fridge-day")
    print("\nfalse alarms per scenario (normal and weak never cross the line, so all of it is noise)")
    print(f"  {'scenario':<20}{'fridge-days':>12}{'events':>8}{'per day':>10}")
    for s, v in breach["per_scenario"].items():
        print(f"  {s:<20}{v['fridge_days']:>12}{v['false_alarm_events']:>8}"
              f"{str(v['events_per_fridge_day']):>10}")
    print("\nbreach episodes, each counted once, with the warning given before the crossing")
    print(f"  {'scenario':<20}{'episodes':>9}{'detected':>10}{'missed':>8}{'early':>7}{'mean lead':>11}")
    for k, v in episodes.items():
        if k == "overall":
            continue
        print(f"  {k:<20}{v['episodes']:>9}{v['detected']:>10}{v['missed']:>8}"
              f"{v['alarmed_early']:>7}{str(v['mean_lead_min']):>11}")
    o = episodes["overall"]
    print(f"  {'ALL':<20}{o['episodes']:>9}{o['detected']:>10}{o['missed']:>8}"
          f"{o['alarmed_early']:>7}{str(o['mean_lead_min']):>11} min")
    print("\nthe server's tree walk against sklearn's own predict, on the same rows")
    for c in walk:
        if not c["checked"]:
            print(f"  {c['head']}: {c['note']}")
            continue
        print(f"  {c['head']}: {c['windows']} windows, max |diff| {c['max_abs_diff_c']:.6f} C, "
              f"mean {c['mean_abs_diff_c']:.6f} C, {c['windows_over_tolerance']} over "
              f"{c['tolerance_c']:g} C ({c['share_over_tolerance']:.4%}) | test RMSE walk "
              f"{c['test_rmse_walk_c']:.6f} vs sklearn {c['test_rmse_sklearn_c']:.6f} -> "
              f"{'AGREES' if c['ok'] else 'DISAGREES'}")
    print(f"\nrolling the compressor health score forward through each stream, one point every "
          f"{HEALTH_ROLL_MIN // 60} h of trace")
    print(f"  {'scenario':<20}{'start':>7}{'end':>6}{'fell by':>8}{'lowest':>8}{'weak pts':>10}{'share':>8}")
    for s, v in health.items():
        if "start_score" not in v:
            print(f"  {s:<20}  {v['note']}")
            continue
        print(f"  {s:<20}{v['start_score']:>7}{v['end_score']:>6}{v['mean_fall_points']:>8}"
              f"{v['lowest_score_seen']:>8}{v['points_in_weak_band']:>10}"
              f"{(v['share_of_points_weak'] or 0.0):>8.2%}")
    print("  a positive \"fell by\" means the score dropped, which is the direction a wearing "
          "compressor moves it; \"weak pts\" counts rolling points in the below-50 band")
    for c in checks:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}: {c['check']} - expected {c['expected']}, "
              f"measured {c['measured']}")
    print(f"\nwrote {a.out} ({len(blob)} bytes)")
    print("every number above was printed by this run; none of them was typed.")
    print("the data is simulated. None of it came from a fridge, so none of it is a real accuracy.")
    if bad:
        for c in bad:
            print("\nFAIL: " + (c["check"] if "check" in c else
                                f"the exported {c['head']} walk does not reproduce sklearn's model"))
        print("these numbers are not shippable until every FAIL above passes.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
