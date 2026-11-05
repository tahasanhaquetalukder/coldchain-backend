"""Compressor cycle segmentation and the 0-100 health score.

Standard library only, like the rest of app.ai: this runs inside the process Render boots.

The compressor is the one part of the system that wears out, and it wears out quietly - the box can
hold 2-8 C for months while the pull per minute creeps down and the run length creeps up. A
threshold on the temperature cannot see that. A comparison against the fridge's own early cycles
can, which is why the baseline is per fridge: a ward that runs at 4 C in a hot room is not broken,
and a ward that used to pull from 7 to 3 in six minutes and now takes fourteen is.

Nothing here invents a number. Too few clean cycles gives score=None with the reason, and readings
written before the compressor state was stored are counted and named rather than read as "the
compressor was off". Cycles polluted by an open door, a power failure or a fresh load are excluded
rather than scored: those warm the box for reasons the machine is not responsible for.
"""
import statistics

from . import features as F

CUT_IN_C = 7.0          # the thermostat's "start" line, the number the simulator and generator use
CUT_OUT_C = 3.0         # its "stop" line
MIN_CYCLES = 4          # below this many clean cycles there is a description, not a score
BASELINE_CYCLES = 12    # the smallest "healthiest early cycles" pool worth taking a median over
BASELINE_SHARE = 0.40   # and the usual size: the first 40 % of the clean cycles
RECENT_CYCLES = 6       # the score is about the newest behaviour, so the newest so many cycles
PEAK_LOOKBACK_MIN = 3   # how far before a run to search for the warm peak that started it
LOAD_JUMP_C = 2.0       # a one-minute rise this big is warm stock arriving, not a failing pull
SPREAD_TOLERANCE = 2.0  # a cycle must miss its own baseline by this many deviations to count
WINDOW_TOLERANCE = 0.25  # a window rate has no cycle-to-cycle spread, so a stated relative allowance
TREND_RATIO = 0.15      # a shift this fraction of the baseline is enough to call a direction

# (name, weight, which direction is worse). The weights are the argument that cooling speed matters
# more than start frequency; they are fixed rather than fitted, so the report can simply state them.
METRICS = (("cool_c_per_min", 0.35, "down"), ("cool_min_7_to_3", 0.30, "up"),
           ("duty", 0.20, "up"), ("starts_per_hour", 0.15, "up"))


def _median(values):
    return statistics.median(values) if values else None


def _spread(values, median):
    """Median absolute deviation: this fridge's own cycle-to-cycle noise, not a global constant."""
    return statistics.median([abs(v - median) for v in values])


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


def _span_minutes(series, a, b):
    """Minutes between two positions of the resampled series, falling back to the grid count.

    The timestamps are the truth when they differ; when a node sent two samples inside one minute the
    bucket holds one entry and the position difference is the only honest answer.
    """
    secs = series[b]["ts"] - series[a]["ts"]
    return secs / 60.0 if secs > 0 else float(b - a + 1)


def _any_true(series, a, b, key):
    return any(series[i][key] == 1 for i in range(a, b + 1))


def _any_false(series, a, b, key):
    """For the supply flag, where 1 means mains OK - so a power failure is the False case."""
    return any(series[i][key] == 0 for i in range(a, b + 1))


def _runs(series):
    """Maximal stretches of an observed compressor state, as (first index, last index, on).

    A minute whose state was never stored is neither on nor off and breaks the run, because "not
    observed" must not extend a claim about the motor.
    """
    out, start, current = [], 0, None
    for i, s in enumerate(series):
        flag = s["comp"]
        if flag != current:
            if current is not None:
                out.append((start, i - 1, current))
            start, current = i, flag
    if current is not None:
        out.append((start, len(series) - 1, current))
    return out


def _peak_index(series, a):
    """The last minute before a run in which the box was still at or above the cut-in line.

    The thermostat closes on the previous minute's reading, so the row that starts the run has already
    lost a minute of pull and the 7 C crossing sits just before it. Measuring from the run's own first
    row would call every fridge one minute faster than it is - and, worse, a different number of
    minutes faster on a fast compressor than on a slow one.
    """
    for i in range(a - 1, max(-1, a - 1 - PEAK_LOOKBACK_MIN), -1):
        if series[i]["temp"] >= CUT_IN_C:
            return i
    return a


def cycles(series):
    """One entry per completed compressor run: what it achieved, and whether it is fair to blame it.

    A run still going at the newest reading is not a cycle. Half a cooling attempt measures nothing,
    and counting it would score a fridge in the middle of a heat wave as a failing machine.
    """
    runs = _runs(series)
    out = []
    for k, (a, b, on) in enumerate(runs):
        if not on or b == len(series) - 1:
            continue
        start_c, end_c = series[a]["temp"], series[b]["temp"]
        minutes = _span_minutes(series, a, b)
        cut_out = next((i for i in range(a, b + 1) if series[i]["temp"] <= CUT_OUT_C), None)
        entered = None if cut_out is None else _peak_index(series, a)
        fall = _span_minutes(series, entered, cut_out) if entered is not None else None
        # The minute that first reports the supply down is the minute whose compressor is already
        # stopped, so a run that an outage ended does not contain the outage among its own rows. One
        # minute past the end is where the evidence is, and without it every power failure in the
        # stored history would read as the machine having stopped by itself.
        lost_power = _any_false(series, a, min(len(series) - 1, b + 1), "power")
        excluded, because = None, None
        if _any_true(series, a, b, "door"):
            excluded, because = "door", "the door was reported open during the run"
        elif lost_power:
            excluded, because = "power", "the supply was reported down as the run ended"
        elif any(series[i]["temp"] - series[i - 1]["temp"] >= LOAD_JUMP_C for i in range(a + 1, b + 1)):
            excluded, because = "load", f"the stock rose {LOAD_JUMP_C:g} C in a minute during the run"
        nxt = runs[k + 1] if k + 1 < len(runs) else None
        warm = None
        if nxt is not None and not nxt[2] and nxt[0] > b:
            gap = _span_minutes(series, b, nxt[0] - 1)
            if gap > 0:
                warm = (series[nxt[0] - 1]["temp"] - end_c) / gap
        # A thermostat ends a run when the box reaches the cut-out line. A run that ends with the
        # supply fine and the door shut was stopped by something else - a fault relay, a defrost,
        # somebody's switch. That is not a slow compressor, it is a stopped one, and reading it as
        # "still cools fine" would call a fridge whose motor drops out daily a healthy machine.
        out.append({"a": a, "b": b, "start_ts": series[a]["ts"], "end_ts": series[b]["ts"],
                    "minutes": round(minutes, 2), "start_c": round(start_c, 2), "end_c": round(end_c, 2),
                    "drop_c": round(start_c - end_c, 2),
                    "cool_c_per_min": round((start_c - end_c) / minutes, 4) if minutes > 0 else None,
                    "cool_min_7_to_3": round(fall, 2) if fall is not None else None,
                    "reached_cut_out": cut_out is not None,
                    "aborted": cut_out is None and not lost_power and excluded != "door",
                    "warm_c_per_min": round(warm, 4) if warm is not None else None,
                    "excluded": excluded, "excluded_because": because})
    return out


def _baseline_pool(kept):
    """The early cycles this fridge is graded against: the first share of the trace, never the tail.

    A fixed count would build a week's baseline from one two-hour stretch - usually the first night -
    and then compare daytime behaviour to it. A share of the whole history spans both. The recent
    cycles are held outside the pool, so a fridge with real history is not graded against the very
    cycles being graded.
    """
    older = kept[:-RECENT_CYCLES] if len(kept) > 2 * RECENT_CYCLES else kept
    return older[:max(MIN_CYCLES, min(len(older), int(len(kept) * BASELINE_SHARE)))]


def _window_stats(series, a, b):
    """Duty cycle and starts per hour across a stretch of the trace, not per cycle."""
    seen = [s for s in series[a:b + 1] if s["comp"] is not None]
    if len(seen) < 2:
        return None
    minutes = (seen[-1]["ts"] - seen[0]["ts"]) / 60.0
    if minutes <= 0:
        return None
    starts = sum(1 for i, s in enumerate(seen) if s["comp"] and (i == 0 or not seen[i - 1]["comp"]))
    return {"minutes": round(minutes, 1), "duty": round(sum(1 for s in seen if s["comp"]) / len(seen), 4),
            "starts_per_hour": round(starts / (minutes / 60.0), 3)}


def _sub_score(base, recent, worse, tol):
    """0-100 for one metric, monotone in the bad direction, blind to this fridge's own noise.

    A metric only starts to fall once the recent median clears the baseline by more than tol, and it
    reaches 0 a further 100 % of the baseline away, so the scale reads "relative to how this fridge
    has always behaved" instead of an absolute guess about compressors in general.
    """
    gap = (recent - base) if worse == "up" else (base - recent)
    if gap <= tol:
        return 100.0
    return _clamp(100.0 * (1.0 - (gap - tol) / max(abs(base), tol)))


def _reason(metric, base, recent):
    if metric == "cool_c_per_min":
        return f"cools at {recent:.2f} C a minute where it used to manage {base:.2f}"
    if metric == "cool_min_7_to_3":
        pct = 0.0 if not base else (recent - base) / base * 100.0
        return f"takes about {pct:.0f} % longer than usual to cool from {CUT_IN_C:g} to {CUT_OUT_C:g} C"
    if metric == "duty":
        return (f"the compressor runs {recent * 100:.0f} % of the time against its usual "
                f"{base * 100:.0f} %")
    return f"the compressor starts {recent:.1f} times an hour where it used to start {base:.1f}"


def trend(kept):
    """Whether the newest half of the clean cycles cools like the older half. Plain words, and the
    numbers underneath, so the page can draw a line and the operator can disagree with it."""
    rates = [c["cool_c_per_min"] for c in kept if c["cool_c_per_min"] is not None]
    if len(rates) < 4:
        return {"state": "not enough cycles", "values": [round(r, 4) for r in rates]}
    half = len(rates) // 2
    first, last = _median(rates[:half]), _median(rates[half:])
    change = (last - first) / max(abs(first), 1e-6)
    return {"state": ("improving" if change > TREND_RATIO else
                      "declining" if change < -TREND_RATIO else "stable"),
            "first_half_median_c_per_min": round(first, 4),
            "second_half_median_c_per_min": round(last, 4), "change": round(change, 4),
            "values": [round(r, 4) for r in rates]}


def score(rows, device_id="unknown"):
    """The health of one fridge's compressor, or the reason there is no honest number yet."""
    series = F.resample(rows)
    unobserved = sum(1 for r in rows if len(r) > 2 and r[2] is None)
    out = {"device_id": device_id, "score": None, "band": None, "state": "not enough cycles yet",
           "reasons": [], "cycles_used": 0, "cycles_seen": 0, "cycles_excluded": 0,
           "runs_stopped_warm": 0,
           "trend": {"state": "not started"}, "metrics": {},
           "cut_in_c": CUT_IN_C, "cut_out_c": CUT_OUT_C, "min_cycles": MIN_CYCLES,
           "minutes_of_history": round(_span_minutes(series, 0, len(series) - 1)) if len(series) > 1 else 0,
           "rows_without_compressor_state": unobserved, "warnings": []}
    if unobserved:
        out["warnings"].append(f"{unobserved} of {len(rows)} stored readings predate the compressor "
                               "column and were never observed at all")
    every = cycles(series)
    kept = [c for c in every if not c["excluded"] and c["cool_c_per_min"] is not None]
    out.update(cycles_seen=len(every), cycles_excluded=len(every) - len(kept),
               runs_stopped_warm=sum(1 for c in every if c["aborted"]))
    if out["runs_stopped_warm"]:
        out["warnings"].append(f"{out['runs_stopped_warm']} run(s) stopped with the box still above "
                               f"{CUT_OUT_C:g} C and the supply fine: the compressor is being switched "
                               "off, not merely slowing. The score measures the pull, not the relay.")
    if len(kept) < MIN_CYCLES:
        out["reasons"] = [f"{len(kept)} clean compressor cycle(s) in this window; "
                          f"{MIN_CYCLES} are needed before a health score means anything"]
        return out

    base_set, recent_set = _baseline_pool(kept), kept[-RECENT_CYCLES:]
    if len(base_set) >= len(kept):
        out["warnings"].append(f"the {len(kept)} clean cycle(s) on hand are also the baseline, so the "
                               "score compares this fridge with itself rather than with its own past")
    early = _window_stats(series, kept[0]["a"], base_set[-1]["b"])
    late = _window_stats(series, recent_set[0]["a"], kept[-1]["b"])
    scored = []
    for metric, weight, worse in METRICS:
        if metric in ("duty", "starts_per_hour"):
            if not (early and late):
                continue
            base, recent = early[metric], late[metric]
            tol = abs(base) * WINDOW_TOLERANCE
        else:
            vals = [c[metric] for c in base_set if c[metric] is not None]
            rec = [c[metric] for c in recent_set if c[metric] is not None]
            if not vals or not rec:
                continue
            base, recent = _median(vals), _median(rec)
            tol = max(_spread(vals, base) * SPREAD_TOLERANCE, 1e-6)
        sub = _sub_score(base, recent, worse, tol)
        scored.append((metric, weight, base, recent, sub))
        out["metrics"][metric] = {"baseline": round(base, 4), "recent": round(recent, 4),
                                  "worse_if": worse, "sub_score": round(sub, 2)}
    if not scored:
        out["reasons"] = ["the cycles stored here carry no comparable cooling numbers"]
        return out

    total = sum(m[1] for m in scored)
    out.update(state="scored", cycles_used=len(kept),
               score=int(round(_clamp(sum(m[1] * m[4] for m in scored) / total))))
    out["band"] = ("good" if out["score"] >= 80 else "watch" if out["score"] >= 50 else "weak")
    out["reasons"] = [_reason(m[0], m[2], m[3]) for m in sorted(scored, key=lambda m: m[4])[:2]
                      if m[4] < 100.0]
    misses = sum(1 for c in recent_set if not c["reached_cut_out"])
    if misses >= max(2, len(recent_set) // 2):
        out["reasons"].insert(0, f"{misses} of the last {len(recent_set)} runs never reached the "
                                 f"{CUT_OUT_C:g} C cut-out")
    if not out["reasons"]:
        out["reasons"] = [f"every measured number is inside this fridge's own usual spread "
                          f"({len(kept)} cycles watched)"]
    out["trend"] = trend(kept)
    return out
