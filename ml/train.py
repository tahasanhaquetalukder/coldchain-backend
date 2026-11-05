#!/usr/bin/env python3
"""Fit the 30-minute heads and write backend/app/ai/model.json.

Ridge first, because a linear model on these features is explainable, tiny and hard to beat.
Gradient boosting is tried second and kept only if it wins on the validation split by more than the
5 % margin below - otherwise the extra 200 trees buy noise, not accuracy.

The split is ordered by time, not shuffled. Shuffled rows let the model see next Tuesday while it is
being asked about this Tuesday; the deployed server only ever has the past, and a score measured on
leaked future data is a score you cannot get again.

    ml/.venv/Scripts/python.exe ml/train.py [--seed 7] [--csv ml/data/sim-norm-A.csv ...]
"""
import argparse
import collections
import csv
import json
import os
import sys
import time

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app.ai import features as F      # noqa: E402  the same module the server imports

MODEL_PATH = os.path.join(ROOT, "backend", "app", "ai", "model.json")
DATA_DIR = os.path.join(ROOT, "ml", "data")
GBM_PARAMS = dict(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0)
GBM_MARGIN = 0.95        # boosting has to beat ridge's validation RMSE by 5 % to be worth the trees
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)
SPLIT_AT = (0.70, 0.85)  # where the train/val and val/test walls fall, as a fraction of the minutes

Windows = collections.namedtuple("Windows", "x temp peak minute stream scenario span")


def read_rows(path):
    """A CSV in the shape ml/generate_data.py writes -> the tuples features.resample() wants."""
    with open(path, newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            out.append((float(r["ts"]), float(r["temperature"]),
                        int(r["compressor_on"]) if r["compressor_on"] != "" else None,
                        int(r["door_open"]) if r["door_open"] != "" else None,
                        int(r["power_ok"]) if r["power_ok"] != "" else None))
    return out


def stream_label(path):
    """The file name and the scenario the generator stamped into it."""
    with open(path, newline="", encoding="utf-8") as fh:
        first = next(csv.DictReader(fh), None)
    return os.path.basename(path), (first or {}).get("scenario") or "unknown"


def collect(paths):
    """Every window in every stream, sorted by minute, tagged by stream and scenario.

    The trainer and ml/evaluate.py both call this one function. Two builders would mean two feature
    orders, and a score computed on a matrix the deployed server cannot rebuild is not a score.
    """
    xs, yt, ym, minute, stream, scenario = [], [], [], [], [], []
    for path in paths:
        name, scen = stream_label(path)
        wins = F.windows(F.resample(read_rows(path)))
        if not wins:
            print(f"  {name}: no complete window - skipped, not padded")
            continue
        for ts, vec, temp, peak, m in wins:
            xs.append(vec)
            yt.append(temp)
            ym.append(peak)
            minute.append(m)
            stream.append(name)
            scenario.append(scen)
        print(f"  {name}: {len(wins)} windows ({scen})")
    if not xs:
        return Windows([], np.array([]), np.array([]), np.array([], dtype=int), [], [], (0, 0))
    minutes = np.array(minute, dtype=int)
    order = np.argsort(minutes, kind="stable")
    return Windows(*[[xs[i] for i in order], np.array(yt)[order], np.array(ym)[order], minutes[order],
                     [stream[i] for i in order], [scenario[i] for i in order],
                     (int(minutes[order][0]), int(minutes[order][-1]))])


def time_split(windows, at=SPLIT_AT, purge_min=F.HORIZON_MIN):
    """Train / val / test index arrays, cut on the minute and purged by one horizon.

    Two things this guards against. Every stream is generated on the same minute grid, so a
    positional cut lands in the middle of a minute and hands the model the same minute from a
    neighbouring fridge that it is then scored on; the walls below are walls in time. And a row's
    target is the temperature 30 minutes later, so a row just before a wall labels itself with data
    from the next set - the last purge_min minutes before each wall are therefore dropped from the
    earlier set instead of leaking into it. ml/evaluate.py rebuilds the same three index arrays.
    """
    m = windows.minute
    n = len(m)
    if n == 0:
        empty = np.array([], dtype=int)
        return empty, empty.copy(), empty.copy(), (0, 0, 0)
    w1, w2 = int(m[int(n * at[0])]), int(m[int(n * at[1])])
    train = np.where(m < w1 - purge_min)[0]
    val = np.where((m >= w1) & (m < w2 - purge_min))[0]
    test = np.where(m >= w2)[0]
    return train, val, test, (w1, w2, n - len(train) - len(val) - len(test))


def fit_head(name, x, y, train, val, test, scaler):
    """One head: standardised ridge at its best alpha, and boosting if boosting clearly wins."""
    zx = (x - scaler[0]) / scaler[1]
    rows = {"head": name, "ridge": {}}
    best = None
    for alpha in ALPHAS:
        model = Ridge(alpha=alpha).fit(zx[train], y[train])
        rmse = float(np.sqrt(np.mean((model.predict(zx[val]) - y[val]) ** 2)))
        rows["ridge"][str(alpha)] = round(rmse, 4)
        if best is None or rmse < best[1]:
            best = (alpha, rmse, model)
    alpha, val_rmse, model = best
    test_rmse = float(np.sqrt(np.mean((model.predict(zx[test]) - y[test]) ** 2)))
    candidate = {"kind": "ridge", "alpha": alpha, "val_rmse": round(val_rmse, 4), "test_rmse": round(test_rmse, 4),
                 "intercept": float(model.intercept_), "coef": [float(c) for c in model.coef_]}
    # kept whether or not ridge wins: the report and the operator both need to know which inputs
    # actually move the number, and a boosted model cannot say so in one line
    rows["ridge_reference"] = {"alpha": alpha, "intercept": round(float(model.intercept_), 4),
                               "coef": {k: round(float(v), 4) for k, v in zip(F.FEATURE_NAMES, model.coef_)}}
    print(f"{name}: ridge alpha={alpha} val RMSE {val_rmse:.4f}  test RMSE {test_rmse:.4f} "
          f"(alphas {rows['ridge']})")

    gbm = GradientBoostingRegressor(**GBM_PARAMS).fit(zx[train], y[train])
    g_val = float(np.sqrt(np.mean((gbm.predict(zx[val]) - y[val]) ** 2)))
    g_test = float(np.sqrt(np.mean((gbm.predict(zx[test]) - y[test]) ** 2)))
    print(f"{name}: gradient boosting      val RMSE {g_val:.4f}  test RMSE {g_test:.4f}")
    rows["gbm_val_rmse"] = round(g_val, 4)
    rows["gbm_test_rmse"] = round(g_test, 4)
    if g_val > val_rmse * GBM_MARGIN:
        print(f"{name}: ridge kept - boosting is inside the {GBM_MARGIN:.0%} margin, "
              "so the extra trees would be fitting noise")
        return candidate, rows, zx
    # the hyper-parameters travel with the model so evaluate.py refits the identical learner and can
    # prove the server's own tree walk lands on the same number as sklearn's
    rows["gbm_params"] = dict(GBM_PARAMS)
    print(f"{name}: boosting kept")
    trees = [_flatten(stage[0].tree_, gbm.learning_rate) for stage in gbm.estimators_]
    # sklearn's constant init comes back as a (1, 1) array; the server's evaluator wants one number
    init = float(np.ravel(gbm.init_.constant_)[0])
    return ({"kind": "gbm", "val_rmse": round(g_val, 4), "test_rmse": round(g_test, 4),
             "init": init, "learning_rate": float(gbm.learning_rate),
             "trees": trees, "n_estimators": len(trees), "params": dict(GBM_PARAMS)}, rows, zx)


def _flatten(tree, learning_rate):
    """A sklearn regression tree as nested lists a standard-library walk can evaluate.

    Leaf values are multiplied by the learning rate here, so the server's evaluator sums the trees
    with no extra scaling; ml/evaluate.py checks that walk against sklearn's own predict and fails
    the run if the two disagree, because that is the one bug that makes an exported model lie.

    Thresholds and leaves go into the file at full float precision rather than rounded: the server
    divides by the numbers in the scaler block and compares against the numbers here, and json
    writes a float exactly, so the round trip costs bytes (the file is 135 KB) and not truth.
    """
    features, threshold, left, right, value = tree.feature, tree.threshold, tree.children_left, tree.children_right, tree.value

    def walk(i):
        if left[i] == -1:
            return float(value[i][0][0]) * learning_rate
        return [int(features[i]), float(threshold[i]), walk(left[i]), walk(right[i])]

    return walk(0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=7, help="recorded in the model for reproducibility")
    p.add_argument("--csv", action="append", help="specific streams; default is every ml/data/sim-*.csv")
    p.add_argument("--out", default=MODEL_PATH)
    a = p.parse_args(argv)

    paths = a.csv or sorted(os.path.join(DATA_DIR, n) for n in os.listdir(DATA_DIR)
                            if n.startswith("sim-") and n.endswith(".csv"))
    # sample.csv is deliberately not in the default: its rows are the first 500 of the streams above,
    # and counting the same minute twice would inflate every number in the report
    if not paths:
        print("no streams found. Run ml/generate_data.py first (see ml/README.md).")
        return 1
    print(f"reading {len(paths)} stream(s); features from backend/app/ai/features.py")
    w = collect(paths)
    x, yt, ym = np.array(w.x, dtype=float), w.temp, w.peak
    if len(x) < 200:
        print(f"only {len(x)} windows. That is enough to prove the plumbing and nothing else: "
              "train on the regenerated streams (ml/generate_data.py) before quoting any number.")

    n = len(x)
    train, val, test, (w1, w2, dropped) = time_split(w)
    print(f"{n} windows over {len(set(w.stream))} streams, minute-cut split "
          f"{len(train)}/{len(val)}/{len(test)} (train/val/test), walls at epoch-minute "
          f"{w1}/{w2}, {dropped} rows purged so no label reaches across a wall, "
          f"{w.span[1] - w.span[0]} minutes of simulated history")

    mean = x[train].mean(axis=0)
    std = x[train].std(axis=0)
    std[std == 0] = 1.0      # a feature that never varies carries no information and must not divide by zero
    # full precision, for the reason in _flatten(): the server divides by the number written here
    scaler = ([float(v) for v in mean], [float(v) for v in std])

    heads, notes = {}, {}
    started = time.time()
    heads["temp30"], notes["temp30"], _ = fit_head("temp30", x, yt, train, val, test, scaler)
    heads["max30"], notes["max30"], _ = fit_head("max30", x, ym, train, val, test, scaler)

    model = {
        "trained": True,
        "generated_by": "ml/train.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": a.seed,
        "data": "SIMULATED by ml/generate_data.py. No row here came from a device, so every number "
                "in this file describes the pipeline, not a real fridge.",
        "streams": sorted(set(w.stream)),
        "scenarios": sorted(set(w.scenario)),
        "libraries": {"numpy": np.__version__, "sklearn": __import__("sklearn").__version__},
        "windows": n,
        "split": {"train": len(train), "val": len(val), "test": len(test),
                  "ordered_by": "minute-and-purged", "walls": [w1, w2], "purged_rows": dropped,
                  "purge_min": F.HORIZON_MIN},
        "horizon_min": F.HORIZON_MIN,
        "threshold_c": F.THRESHOLD_C,
        "min_history_min": F.MIN_HISTORY_MIN,
        "feature_names": list(F.FEATURE_NAMES),
        "scaler": {"mean": scaler[0], "std": scaler[1]},
        "heads": heads,
        "selection": notes,
        "fit_seconds": round(time.time() - started, 1),
    }
    blob = json.dumps(model, separators=(",", ":"))
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(blob)
    print(f"wrote {a.out}: {len(blob)} bytes ({len(blob) / 1048576:.2f} MiB), "
          f"heads {', '.join(h['kind'] for h in heads.values())}")
    if len(blob) >= 1_000_000:
        print("OVER THE 1 MB LIMIT - the model has to travel inside the deployed backend")
        return 1
    ref = notes["temp30"]["ridge_reference"]["coef"]
    print("temp30 strongest standardised ridge weights:",
          ", ".join(f"{k} {v:+.3f}" for k, v in sorted(ref.items(), key=lambda kv: -abs(kv[1]))[:5]))
    print("(weights of the ridge reference, even when boosting was the one kept)")
    print("every number above was printed by this run; none of them was typed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
