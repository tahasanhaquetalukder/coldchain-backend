# ColdChain — user manual

For whoever operates the web app: staff signing in to monitor fridges and batches, and the public
who scan a QR code. Written against the deployed build; button names below are the ones on screen.

## 1. Before you open the site

The dashboard is only as alive as the devices feeding it. A freshly started server has two fridges
reporting **5.0 °C** and **offline**, because nothing has sent a reading yet.

Start a device feed first:

```bash
API_BASE=https://your-api-host.onrender.com backend/venv/Scripts/python.exe backend/simulator.py fridge-1
API_BASE=https://your-api-host.onrender.com backend/venv/Scripts/python.exe backend/simulator.py fridge-2 hot
API_BASE=https://your-api-host.onrender.com backend/venv/Scripts/python.exe backend/simulator.py fridge-1 door
```

Each line impersonates one ESP32 and posts a signed reading every 5 seconds. `hot` makes that
fridge climb past 12 °C, which is what drains a heat budget on screen. `door` holds the door open so
the 60-second alert fires. A real ESP32 needs the same server URL and the same `HMAC_SECRET_KEY`; its
payload format is exactly what `simulator.py` sends.

If your fridges publish MQTT instead of calling the API, run one bridge per site:

```bash
mosquitto -p 1883
API_BASE=https://your-api-host.onrender.com MQTT_HOST=127.0.0.1 backend/venv/Scripts/python.exe backend/mqtt_bridge.py
```

It subscribes to `coldchain/+/reading` and forwards each message to `/api/sensor` byte for byte. It
does not sign anything, so a compromised bridge still cannot invent a reading.

Leave the feed running. On the free hosting tier an idle API goes to sleep after about 15 minutes,
and the readings it misses while waking up are lost unless the device marks them `buffered: true`.

## 2. Signing in

Open the site. The sign-in form arrives prefilled with `admin` / `admin123`; press **Enter** or
click **Sign in**.

| Account | Password | Can do |
| --- | --- | --- |
| `admin` | `admin123` | Everything, including **Admin reset** and the audit log |
| `pharmacist` | `pharmacist123` | Dashboard + all inventory. **No Audit log tab at all** |
| `inspector` | `inspector123` | Read-only: dashboard, inventory table, audit log. Cannot add or move batches |

Your name and role are shown at the top right, and **Sign out** is the door icon beside it.
You stay signed in through a page refresh. Sessions expire after 8 hours, or immediately if the
server is redeployed with a different `JWT_SECRET` — either way you land back on the sign-in form.

If a red line appears under the password box:

- `Wrong username or password` — the credentials are wrong; the server checked and refused them.
- `Server not reachable: https://…` — the page cannot contact the API at the host shown. That host
  is either wrong (a stale `VITE_API_URL` baked into the build) or asleep. Open
  `https://that-host/api/health`; JSON back means it's awake, `no-server` means the address is dead.
- `Request rejected by the server` — the host answered but refused. Look at the API's log.

## 3. Dashboard

One card per fridge, refreshed automatically every 4 seconds.

- **Header line** — fridge name, then `device id · online` or `· offline`. *Offline* means no
  reading has arrived in the last 20 seconds; the temperature shown is the last one it received.
- **Colour pill** — `Safe` (2–8 °C), `Warning` (above 8 or below 2), `Breach` (above 12, below 0,
  or no reading at all). The coloured bar across the top of the card matches it.
- **Big number** — current temperature, one decimal.
- **Sparkline** — the last 40 readings. The dashed red line is the 8 °C limit, so a trace crossing
  it is visible at a glance.
- **Four tiles** — Door (open/closed), power (Mains, or Battery % when mains has failed),
  Compressor (on/off — the device reports the 7 °C-on / 3 °C-off hysteresis it runs locally), and
  the door alert: *Door alert* once a door has been open past 60 seconds, otherwise *No alerts*.
  That alert is written to the audit log once per opening, not every reading, and if the server has
  Telegram credentials it sends one message at the same moment.
- **Heat budget per batch** — a bar per batch in that fridge, showing minutes remaining and its
  status pill. Empty list says `No batches in this fridge.`

## 4. Inventory

### Add a batch

The form across the top (hidden for `inspector`) takes four fields:

| Field | Notes |
| --- | --- |
| `code` | The string printed in the QR. Must not already exist — you get `Batch code already exists` |
| `vaccine` | Free text, e.g. `Insulin` |
| `expiry` | A date picker; the app rejects anything that is not a real date |
| fridge dropdown | Pick a fridge or leave it **Unassigned** |

Click **Add batch**. The row appears in the table below.

### Move a batch between fridges

Change the dropdown in that batch's **Fridge** column. It saves immediately and the budget starts
accruing against the new fridge's temperature. Unassigned batches sit in no fridge and therefore
accumulate no heat exposure.

### Heat budget, in plain terms

Every batch starts with **60 budget-minutes**. Time above 8 °C spends it one minute per minute;
above 12 °C spends it **two** minutes per minute; in range it never drains. Below 20 % remaining
the batch is **At Risk**; at 0 % it is **Discard**.

`Admin reset` appears next to a batch only for an admin, and only once it is no longer `Safe`. It
refills the budget — for a genuinely new shipment, not to rescue a cooked one. Every use is written
to the audit log as `ADMIN_RESET`. It also clears the fridge's red LED, indirectly: the server
returns the worst batch status in that fridge with every reading it accepts, the node keeps its LED
lit while that answer is `Discard`, and the first reading after a reset is answered `Safe`.

### QR

Each row renders a QR code encoding `<site>/#/check/<code>`. **Open QR page** is the same link as
text. Scanning it needs no app and no login.

## 5. Public QR check

`https://your-site/#/check/VAX-001` opens a single card, no sign-in:

- A coloured circle with the verdict — **Safe**, **At Risk** or **Discard**.
- The vaccine name and `Expires <date>`, with `(expired)` appended once the date has passed.
- A footnote: *Stored within its temperature budget.* when Safe, otherwise
  *Do not use until a pharmacist confirms.*

An expired batch always reads **Discard**, whatever its temperature history. An unknown code shows
`No batch with this code.`

## 6. Audit log

Admin and inspector only. The table shows `#`, `Event`, `Details`, `Hash` (first 12 characters;
hover for the whole thing) and `Time` in your browser's local timezone. Rejections, alerts and
failed logins are printed in red.

| Event | Written when |
| --- | --- |
| `SEED` | First start: demo users, fridges and batches created |
| `LOGIN_FAILED` | A wrong password was tried |
| `MESSAGE_REJECTED` | A device message arrived with a bad signature, a stale timestamp, a replayed nonce, or an unknown device id. Details name the device and the reason |
| `DOOR_ALERT` | A door stayed open past 60 seconds |
| `BATCH_STATUS` | A batch crossed into At Risk or Discard |
| `BATCH_CREATED` / `BATCH_MOVED` / `ADMIN_RESET` | The matching inventory action |

**Verify integrity** recomputes the hash chain over every record and reports
`Chain intact (N records)` or `Tampering detected at record #n: <reason>`. Each row's hash covers
the previous row's hash, so editing or deleting one record breaks every link after it and the check
points at the first broken one.

## 7. Things that surprise people

- **A redeploy wipes the database.** The hosted disk is temporary, so after any deploy or rename you
  get two empty fridges and the two demo batches back, and the audit chain starts fresh.
- **A stale chain is not tampering.** If `Verify integrity` reports a broken record immediately
  after you attach a database created by an older build, the rows were hashed by different code.
  Archive the file and let it re-seed.
- **`offline` with a normal temperature is a feed problem, not a fridge problem.** Check the
  simulator or the ESP32's signal, then its clock — a device whose clock drifts more than 60 seconds
  from real time gets every reading rejected as `stale timestamp`.
- **Duplicate readings are ignored, not counted twice.** A device that resends the same or an older
  timestamp gets `duplicate-ignored` and no budget change, so a flaky network cannot inflate
  exposure.
