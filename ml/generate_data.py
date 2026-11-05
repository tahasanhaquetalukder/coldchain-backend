#!/usr/bin/env python3
"""Deterministic simulated cold-chain stream -> ml/data/*.csv.

EVERY ROW THIS WRITES IS A SCENARIO, NOT A MEASUREMENT. It is a leaky-box thermal model plus the
failure modes Task 5 is asked to detect, chosen so a forecast has something to learn and so
evaluation can say "this is what the pipeline does on data we constructed to contain the fault".
A number from here never describes a real fridge; see ml/README.md.

Standard library only and fully reproducible: the clock is a fixed start epoch, not now(), every
random draw comes from a seed derived from --seed and the stream name, and the byte digest is
printed so a re-run can be compared instead of re-argued.

  python ml/generate_data.py --seed 7 --days 7
  python ml/generate_data.py --rows 5000 --out /tmp/probe
"""
import argparse
import csv
import hashlib
import math
import os
import random
import sys
from collections import Counter

START_TS = 1_770_000_000   # fixed epoch: the file must not change because of the day it was made
STEP_S = 60                # one row a minute - the same grid backend/app/ai/features.py resamples to
MINUTES_PER_DAY = 1_440

AMBIENT_BASE, AMBIENT_SWING = 20.0, 3.0   # the room, warmest mid-afternoon
LEAK = 0.008               # C/min per degree between box and room, i.e. a closed, healthy lid
PULL = 0.45                # C/min a healthy compressor takes out while it runs
ON_AT, OFF_AT = 7.0, 3.0   # the Task 1 thermostat rule, unchanged here and in the simulator
MIN_OFF_S = 300            # short-cycle protection: five minutes betwen runs

SCENARIOS = ("normal", "door_left_open", "weak_compressor", "power_failure", "heavy_loading")
# short device names, because the stream id ends up in every CSV row and in ml/results.json
LABEL = {"normal": "norm", "door_left_open": "door", "weak_compressor": "weak",
         "power_failure": "powr", "heavy_loading": "load"}

# how much faster the box equalises with the room during an event, as a multiple of a closed lid
EVENT_LEAK = {"door": 6.0, "load": 4.0, "outage": 3.0}


def events_for(scenario, minutes, rng):
    """Event windows drawn once at the start, so the stream is stable and readable.

    Each entry is (start_minute, length_minutes, kind). normal has none - it is the control that
    tells the evaluator how many false alarms the model raises on a fridge doing nothing wrong.
    """
    days = max(1, minutes // MINUTES_PER_DAY)
    out = []
    if scenario == "door_left_open":
        for d in range(days):
            out.append((d * MINUTES_PER_DAY + rng.randint(420, 1000), 90, "door"))
    elif scenario == "power_failure":
        for d in range(days):
            start = d * MINUTES_PER_DAY + rng.randint(300, 600)
            out.append((start, rng.randint(35, 70), "outage"))
            out.append((start + rng.randint(500, 700), rng.randint(20, 45), "outage"))
    elif scenario == "heavy_loading":
        for d in range(0, days, 2):
            start = d * MINUTES_PER_DAY + rng.randint(500, 720)
            out.append((start, 18, "load"))
    return out


def simulate(name, scenario, minutes, seed):
    """One fridge, minute by minute. Returns rows in the header order of ROW_FIELDS."""
    rng = random.Random(f"{seed}:{name}:{scenario}")
    events = events_for(scenario, minutes, rng)
    decay = scenario == "weak_compressor"
    t, comp_on, off_until = 5.0 + rng.uniform(-0.5, 0.5), False, 0.0
    rows = []
    for i in range(minutes):
        ts = START_TS + i * STEP_S
        ambient = AMBIENT_BASE + AMBIENT_SWING * math.sin(2 * math.pi * ((ts // 3600) % 24 - 15) / 24)
        kind = next((e[2] for e in events if e[0] <= i < e[0] + e[1]), None)
        door_open = kind in ("door", "load")
        power_ok = kind != "outage"
        # a wearing compressor loses pull steadily across the window; 1.0 everywhere else
        factor = max(0.32, 1.0 - 0.70 * (i / minutes)) if decay else 1.0
        if comp_on and (not power_ok or t <= OFF_AT):
            comp_on, off_until = False, ts + MIN_OFF_S
        elif (not comp_on and t >= ON_AT and power_ok and ts >= off_until):
            comp_on = True
        if kind == "load" and i == next((e[0] for e in events if e[0] == i), None):
            t += 3.5    # the stock itself arrives at room temperature
        # an overloaded box cannot circulate air either, so a load blunts the pull, not just the lid
        pull = PULL * factor * (0.4 if kind == "load" else 1.0)
        t += (ambient - t) * LEAK * EVENT_LEAK.get(kind, 1.0) \
            - (pull if comp_on else 0.0) + rng.gauss(0, 0.06)
        rows.append([name, ts, round(t, 2), int(comp_on), int(door_open), int(power_ok), scenario])
    return rows


ROW_FIELDS = ["fridge", "ts", "temperature", "compressor_on", "door_open", "power_ok", "scenario"]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(ROW_FIELDS)
        w.writerows(rows)
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:12]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=7, help="every draw derives from this")
    p.add_argument("--days", type=int, default=7, help="length of each scenario stream")
    p.add_argument("--rows", type=int, default=500, help="rows in the committed ml/data/sample.csv")
    p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    p.add_argument("--only", action="append", choices=SCENARIOS, help="limit to these scenarios")
    a = p.parse_args(argv)
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    minutes = max(MINUTES_PER_DAY, a.days * MINUTES_PER_DAY)
    chosen = a.only or list(SCENARIOS)

    merged = []
    print(f"scenario          rows  >8C-min  breach-episodes  duty    digest")
    for scenario in chosen:
        # two streams per scenario: an evaluator needs a population, not a single lucky fridge
        for n in ("A", "B"):
            rows = simulate(f"sim-{LABEL[scenario]}-{n}", scenario, minutes, a.seed)
            digest = write_csv(os.path.join(a.out, f"{rows[0][0]}.csv"), rows)
            warm = sum(1 for r in rows if r[2] > 8)
            duty = sum(r[3] for r in rows) / len(rows)
            episodes = sum(1 for j in range(1, len(rows)) if rows[j][2] > 8 >= rows[j - 1][2])
            print(f"{scenario:<16}{len(rows):>6}{warm:>9}{episodes:>17}{duty:>8.2f}  {digest}")
            merged.extend(rows)
    # the committed sample is the merged stream in time order, so it holds several scenarios
    merged.sort(key=lambda r: (r[1], r[0]))
    sample = merged[:max(0, a.rows)]
    digest = write_csv(os.path.join(a.out, "sample.csv"), sample)
    print(f"\n{len(merged)} rows across {len(chosen) * 2} streams into {a.out}")
    print(f"sample.csv: {len(sample)} rows, {len(sample) and sample[-1][1] - sample[0][1]} seconds "
          f"of history, digest {digest}")
    # it is the head of the stream, so it holds no event: enough to prove the format and the plumbing,
    # not enough to train on. Regenerate the full set (the ignored sim-*.csv files) before training.
    print("sample.csv is the first rows of each stream - a format smoke test, not a training set.")
    print("scenarios present:", dict(Counter(r[6] for r in sample)))
    print("all rows above are simulated. None of them came from a device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
