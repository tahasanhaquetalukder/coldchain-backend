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

## The live demo, with the committed model

`backend/scripts/demo_task5.py` needs no training run and no hardware - it uses the `model.json` that
is already in the repo. Start the API, then from the repository root:

```powershell
$env:DEMO_PASSWORD = "admin123"        # the seeded demo admin; required, and never printed
backend/venv/Scripts/python.exe backend/scripts/demo_task5.py

# against a deployed backend, and against another admin on that backend
$env:API_BASE = "https://your-api-host.onrender.com"; $env:DEMO_USERNAME = "admin"
backend/venv/Scripts/python.exe backend/scripts/demo_task5.py
```

It registers `demo-warm-1` and `demo-cold-1`, puts `DEMO-A01` and `DEMO-A02` in the warm one and posts
about 155 signed readings per node - oldest first, `buffered=true`, the way a node that lost its Wi-Fi
empties its queue. The warm fridge cools normally for four compressor cycles, then slowly for three,
then stops cutting in and creeps up to about 7.6 °C; the cold one keeps cycling and stops mid-pull so it
qualifies as a destination. It then prints what the three routes answer for those two nodes, which is
the demo: a forecast that says the warm box crosses 8 °C inside the horizon, a health score that has
fallen on it with the reason, and the moves the rules suggest.

Two things to know before a judge sees it:

- **Run it, then look at the page immediately.** The online rule is 20 seconds and the script stops
  feeding when it is done, so a fridge left alone for a minute is honestly reported as offline and the
  relocation rules refuse to move stock into a fridge nobody can vouch for. Run the script again to
  refresh it; that is what it is for.
- **The readings are a scenario**, the same kind `ml/generate_data.py` writes, not a fridge. The
  forecast and the score are the real code on the real ingest path, but the failure they are catching
  was authored for the demo.

It is safe to run repeatedly: it appends the minutes a node is missing, anchored to the current clock,
rather than trying to re-write history the ingest has already accepted (anything at or before a node's
newest stored timestamp is ignored). It never confirms a move - pressing that button as pharmacist is
the point of the exercise.

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
