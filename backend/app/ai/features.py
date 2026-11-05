"""The one place the forecast's inputs are defined.

Imported by ml/train.py on the laptop and by the running server on Render. A feature computed one
way at training and another way in production does not show up as an error - it shows up as an
accuracy number that the field never reproduces, so the two must not be allowed to exist separately.

Nothing here reads a sample at or after the prediction time. A window that reaches forward is
leakage: it would let the model see the breach it is supposed to warn about.
"""
import math

GRID_S = 60               # every feature is built on this grid, whatever cadence the node sends
MIN_HISTORY_MIN = 15      # below a contiguous run this long there is no forecast, only an explanation
WINDOW_MIN = 30           # the longest lookback any feature uses
HORIZON_MIN = 30          # how far ahead the two heads predict
THRESHOLD_C = 8.0         # the Task 5 breach line, the same number the heat budget weights on
HYSTERESIS_C = 0.4        # a forecast must fall this far under the line before a new episode counts

FEATURE_NAMES = (
    "temp_last",          # mean of the newest two minutes, so one noisy sample is not the signal
    "mean_5", "mean_15",
    "slope_5", "slope_15",
    "max_15", "min_15",
    "above8_min",         # minutes over the line in the last quarter hour
    "duty_15",            # fraction of those minutes the compressor was observed running
    "door_min_15",        # minutes the door was reported open
    "power_off_min_15",   # minutes the supply was reported down
    "dev_from_mean",      # temp_last - mean_15: where the box is relative to its own recent level
    "flags_known",        # 1 when any of the three signed states was observed in the window
    "hour_sin", "hour_cos",
    "history_min",        # length of the contiguous run the model got, capped at WINDOW_MIN
)


def _flag(value):
    """None stays None: an unobserved compressor is not a stopped one."""
    if value is None:
        return None
    return 1 if value else 0


def resample(rows):
    """(ts, temperature, compressor_on, door_open, power_ok) in any order -> one entry per minute.

    The laptop feeds minute rows and an ESP32 feeds five-second rows; bucketing first is what makes
    one trained number mean one thing on both. Temperature is averaged inside a bucket, the three
    states take the newest sample in it, which is the state the next minute starts from.
    """
    buckets = {}
    for row in rows:
        ts, temp = row[0], row[1]
        if temp is None:
            continue
        buckets.setdefault(int(ts // GRID_S), []).append(
            (ts, float(temp), _flag(row[2]), _flag(row[3]), _flag(row[4])))
    series = []
    for key in sorted(buckets):
        samples = sorted(buckets[key])
        flags = [next((s[k] for s in reversed(samples) if s[k] is not None), None) for k in (2, 3, 4)]
        series.append({"minute": key, "ts": samples[-1][0],
                       "temp": sum(s[1] for s in samples) / len(samples),
                       "comp": flags[0], "door": flags[1], "power": flags[2]})
    return series


def run_length(series, i):
    """Consecutive whole minutes ending at index i, capped at WINDOW_MIN.

    A node that was offline for two hours has plenty of rows and no usable recent history, and those
    two situations must not look the same to the model or to the operator. The cap is what keeps
    building a week of windows linear instead of quadratic.
    """
    run, j = 1, i
    while j > 0 and run < WINDOW_MIN and series[j - 1]["minute"] == series[j]["minute"] - 1:
        run += 1
        j -= 1
    return run


def _slope(values):
    """Least-squares C per minute over a short series, with the guard a flat window needs."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x, mean_y = (n - 1) / 2, sum(values) / n
    den = sum((i - mean_x) ** 2 for i in range(n))
    return 0.0 if not den else sum((i - mean_x) * (values[i] - mean_y) for i in range(n)) / den


def features(series, i=None):
    """The features for the minute at index i (the newest one by default), in FEATURE_NAMES order.

    Returns None when the contiguous run is shorter than MIN_HISTORY_MIN. A number invented from four
    minutes of data is worse than no number: it arrives shaped exactly like a real forecast and
    nothing downstream can tell the difference.
    """
    i = len(series) - 1 if i is None else i
    if i < 0:
        return None
    run = run_length(series, i)
    if run < MIN_HISTORY_MIN:
        return None
    window = series[i - run + 1:i + 1]
    temps = [s["temp"] for s in window]
    m5, m15 = temps[-5:], temps[-15:]
    mean15 = sum(m15) / len(m15)
    comp = [s["comp"] for s in window[-15:] if s["comp"] is not None]
    door = [s["door"] for s in window[-15:] if s["door"] is not None]
    power = [s["power"] for s in window[-15:] if s["power"] is not None]
    hour = (series[i]["ts"] % 86400) / 3600.0
    return {
        "temp_last": sum(temps[-2:]) / 2,
        "mean_5": sum(m5) / len(m5), "mean_15": mean15,
        "slope_5": _slope(m5), "slope_15": _slope(m15),
        "max_15": max(m15), "min_15": min(m15),
        "above8_min": float(sum(1 for x in m15 if x > THRESHOLD_C)),
        "duty_15": (sum(comp) / len(comp)) if comp else 0.0,
        "door_min_15": float(sum(1 for x in door if x)),
        "power_off_min_15": float(sum(1 for x in power if not x)),
        "dev_from_mean": temps[-1] - mean15,
        "flags_known": 1.0 if (comp or door or power) else 0.0,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "history_min": float(run),
    }


def vector(features_dict):
    """The same numbers in the order the exported model expects."""
    return [features_dict[name] for name in FEATURE_NAMES]


def targets(series, i, horizon=HORIZON_MIN):
    """(t+horizon temperature, max over (t, t+horizon]) for the minute at i, or None if incomplete.

    A window whose horizon runs into a gap is dropped rather than filled: a zero, a carry-forward or
    a shorter window would all train the model on a target that does not mean what it says.
    """
    end = i + horizon
    if end >= len(series) or series[end]["minute"] - series[i]["minute"] != horizon:
        return None
    ahead = [series[j]["temp"] for j in range(i + 1, end + 1) if series[j]["minute"] - series[i]["minute"] <= horizon]
    if len(ahead) != horizon:
        return None
    return series[end]["temp"], max(ahead)


def windows(series):
    """Every (ts, feature vector, temp target, max target, minute) this series supports."""
    out = []
    for i in range(MIN_HISTORY_MIN - 1, len(series)):
        f = features(series, i)
        if f is None:
            continue
        target = targets(series, i)
        if target is None:
            continue
        out.append((series[i]["ts"], vector(f), target[0], target[1], series[i]["minute"]))
    return out
