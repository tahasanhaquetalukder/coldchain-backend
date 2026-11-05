# Task 5 - machine learning, on the laptop only

Nothing in this folder is deployed. Render builds `backend/`, which imports `backend/app/ai/`
and that package is standard library only. The libraries here live in `ml/.venv`, which git
ignores, so a backend that grew a numpy import would still deploy - and this README is the reason
it is worth checking before you add one.

## Setup

```powershell
python -m venv ml/.venv
ml/.venv/Scripts/python.exe -m pip install -r ml/requirements-ml.txt
```

Run every script from the repository root with that interpreter, not the system one:

```powershell
ml/.venv/Scripts/python.exe ml/generate_data.py --seed 7
ml/.venv/Scripts/python.exe ml/train.py
ml/.venv/Scripts/python.exe ml/evaluate.py
ml/.venv/Scripts/python.exe ml/make_report.py
```

## What each script does

| Script | Reads | Writes |
| --- | --- | --- |
| `generate_data.py` | nothing (deterministic, `--seed`) | `ml/data/*.csv` |
| `train.py` | `ml/data/*.csv` | `backend/app/ai/model.json` |
| `evaluate.py` | `ml/data/*.csv` + `model.json` | `ml/results.json`, stdout |
| `make_report.py` | `ml/results.json` + `model.json` | `docs/task5_report.md` |

`backend/app/ai/features.py` is imported by both `train.py` and the running server. That is
deliberate: a feature computed one way at training and another way in production produces an
accuracy the field never sees.

`evaluate.py` imports `backend/app/ai/compressor.py` for the same reason, and rolls its 0-100 health
score forward through every stream six hours at a time: the number `GET /api/ai/compressor` serves is
checked on the same simulated wear curve as the forecast, and on the streams that were never given a
fault, to see how often it calls a healthy machine weak.

## Committed and ignored

`ml/data/*.csv` is generated, so it is ignored - except `ml/data/sample.csv`, 500 rows, committed
so `train.py` can be started at all without a generator run. It is the first ~41 minutes of each of
the twelve streams, and every fault in the generator starts later than that, so it contains no
fault: it proves the format and the plumbing, and `train.py` says so loudly when that is all it
has. The committed model was trained on the full regenerated set.
`ml/results.json` and `backend/app/ai/model.json` are committed because the deployed backend needs
the model and the report needs the metrics.

## The honest limit

Every row `generate_data.py` writes is a scenario: a physics-ish rule plus noise, chosen to produce
the failure modes Task 5 is asked to detect. Accuracy measured on it says the pipeline works, not
that the model knows your fridge. Real numbers need a real stream - run `backend/simulator.py` or
an ESP32 against the backend for a day, export the readings, and evaluate on those before quoting
any figure to anybody.
