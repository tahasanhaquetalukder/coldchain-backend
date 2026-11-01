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
the 60-second alert fires. A real ESP32 needs the same server URL and the same signing setup, but a
simulator can only imitate a **fleet-key** node: the two seeded fridges. Any id you register through
the app is issued its own secret and refuses the shared one, so bring hardware online from the
**Devices** tab (§3), not from this script. Its payload format is exactly what `simulator.py` sends.

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
| `admin` | `admin123` | Everything, including **Admin reset**, registering nodes and the audit log |
| `pharmacist` | `pharmacist123` | Dashboard + all inventory. **No Audit log tab at all** |
| `inspector` | `inspector123` | Read-only: dashboard, inventory table, audit log. Cannot add or move batches |

The dark header carries `yourname · role · API https://the-host-it-calls`, then **Sign out**, and the
four tabs under it: **Dashboard**, **Inventory**, **Devices**, **Audit trail**. A refresh keeps you signed
in; closing the tab does not, because the session is kept per tab rather than per browser — a console
left open on a shared ward terminal should not hand its token to the next person. Tokens expire after
8 hours, or immediately if the server is redeployed with a different `JWT_SECRET`; either way the next
request puts you back on the sign-in form.

If a red line appears under the password box:

- `Wrong username or password` — the credentials are wrong; the server checked and refused them.
- `Cannot reach the API at https://…` — the page cannot contact the API at the host shown. That host
  is either wrong (a stale `VITE_API_BASE` baked into the build) or asleep. Open
  `https://that-host/api/health`; JSON back means it's awake, `no-server` means the address is dead.
- `Rejected by the server (HTTP 403)` — the host answered but refused your role. The text after a
  failed write is the server's own reason, which is the answer to "why is this button not working".

Only `admin` and `inspector` see the **Audit trail** tab. A pharmacist who types its address gets a
line saying the view belongs to those roles, not a blank page.

## 3. Devices

The tab for when a device is being connected. It opens on whichever node last reported; the others
are cards across the top, each labelled with how long ago its last accepted reading was, and with
`own key` or `fleet key` — which secret that node is expected to sign with.

| Badge | Means |
| --- | --- |
| `live 3s` | a reading arrived within the last 20 seconds |
| `stale 40s` | nothing for 20 s – 2 min: the node is alive, the link or the API is not |
| `offline 12m` | nothing for more than 2 minutes |
| `never reported` | registered, but no packet from it has ever passed verification |
| `emptying buffer` | the newest accepted reading was replayed from the node's offline queue |

The trace is drawn against the node's own timestamps, so an outage is a visible gap and points
marked with a dot came from the buffer rather than live. Under it:

- **signed 19:50:23 · arrived 2s ago** — the clock inside the packet against the server's clock.
- **node clock is -0.7s against the server** — a few seconds is normal; minutes means the node never
  reached an NTP server, and its packets will start being refused as `stale timestamp`.
- **N readings stored · battery 97%** — the battery percentage the node itself reported.
- the last ten readings, newest first, each tagged `live` or `buffered`.

The range selector keeps the last 60, 180 or 600 readings (600 is the most the server will hand back),
and **pause** stops the 3-second refresh.

### Rejections, in the server's words

A red card lists packets that carried this id and were refused, with what usually causes each:

- `invalid signature` — the `HMAC_KEY` flashed into the node is not the one this server issued for
  that id, or a number was printed differently than it was signed. A registered node refuses to work
  with the shared fleet key; only nodes that predate registration use it.
- `stale timestamp` — the node's clock has not synced, or its backlog is older than 3 hours.
- `replayed nonce` — a resend of something already stored. Harmless: the node consumes that sample
  and moves on.
- `unknown device` — nobody registered that id.

An amber card below lists ids that are sending but unregistered, each with a **register this id**
button, so a node that just arrived can be brought online from this page.

### Registering a node (admin)

Type a name and the exact `DEVICE_ID` from `firmware/coldchain_node/cc_config.h` — or run
`python backend/simulator.py <id>` to feed the page without hardware — then press **Register and get
its key**. The server generates a secret for that one node and shows it exactly once, as the two lines
to paste, with a copy button for each:

```c
#define DEVICE_ID   "fridge-3"
#define HMAC_KEY    "a 32-character hex string only this page ever displays"
```

Paste both into `cc_config.h`, reflash and restart the node. Until you do, its packets arrive with the
old key and pile up as `invalid signature`. The panel closes once you press *I have written it down*,
and there is no way to read that key again — the server stores it in a column no endpoint returns, and
nothing writes it to the audit log. Losing it means rotating, not recovering.

`python backend/simulator.py` cannot imitate a registered node: it signs with the fleet key, which the
server refuses for any id that has its own. Use the two seeded fridges (`fridge-1`, `fridge-2`) for
simulator demos, and the real hardware for a registered id.

**Rotate its key** issues a new secret and the previous one stops working on the next packet, so the
node has to be reflashed with what comes back. **Unregister this node** removes it and deletes its
stored readings; batches stay, they just become unassigned.

Nothing on this page is estimated. If a number is on screen, a packet containing it passed the
signature, timestamp-window and nonce checks.

This page is the server half of onboarding. The board half — which libraries to install, what goes into
`cc_config.h`, what the Serial Monitor should print, and what each refusal means — is §9, written for
whoever is holding the ESP32 and has not seen the repository.

## 4. Dashboard

One card per fridge, refreshed automatically every 5 seconds.

- **Header line** — fridge name, then `device id · online` or `· offline`. *Offline* means no
  reading has arrived in the last 20 seconds; the temperature shown is the last one it received.
- **Colour pill** — `Safe` (2–8 °C), `Warning` (above 8 or below 2), `Breach` (above 12 or below 0),
  or `No data` for a fridge that has never reported. The coloured bar across the top matches it.
- **Big number** — current temperature, one decimal, or `--.-` when there is no reading yet.
- **Sparkline** — the last 40 readings. The shaded band is the 2–8 °C store and the dashed red line is
  its upper limit, so a trace crossing it is visible at a glance.
- **Four tiles** — Door (open/closed), power (Mains, or Battery % when mains has failed),
  Compressor (on/off — the device reports the 7 °C-on / 3 °C-off hysteresis it runs locally), and
  the door alert: *Door alert* once a door has been open past 60 seconds, otherwise *No alerts*.
  That alert is written to the audit log once per opening, not every reading, and if the server has
  Telegram credentials it sends one message at the same moment.
- **Heat budget per batch** — a bar per batch in that fridge, showing minutes remaining and its
  status pill. Empty list says `No batches in this fridge.`

## 5. Inventory

### Add a batch

The form across the top (hidden for `inspector`) takes four fields:

| Field | Notes |
| --- | --- |
| Code | The string printed in the QR. Must not already exist — you get `Batch code already exists` |
| Vaccine | Free text, e.g. `Insulin` |
| Expiry | A date picker; the app rejects anything that is not a real date |
| Fridge | Pick a fridge or leave it **Unassigned** |

**Add batch** stays disabled until code, vaccine and expiry all have something in them. The row
appears in the table below, and whatever the server said appears under the form — an accepted add in
green, a rejection in red with the server's own text, in the same slot so the table cannot jump.

### Move a batch between fridges

Change the dropdown in that batch's **Fridge** column. It saves immediately and the budget starts
accruing against the new fridge's temperature. Unassigned batches sit in no fridge and therefore
accumulate no heat exposure.

### Heat budget, in plain terms

Every batch starts with **60 budget-minutes**. Time above 8 °C spends it one minute per minute;
above 12 °C spends it **two** minutes per minute; in range it never drains. Below 20 % remaining
the batch is **At Risk**; at 0 % it is **Discard**.

`Admin reset` appears next to a batch only for an admin, and only once it is no longer `Safe`. It asks
you to confirm, then refills the budget — for a genuinely new shipment, not to rescue a cooked one.
Every use is written to the audit log as `ADMIN_RESET`. It also clears the fridge's red LED,
indirectly: the server
returns the worst batch status in that fridge with every reading it accepts, the node keeps its LED
lit while that answer is `Discard`, and the first reading after a reset is answered `Safe`.

### QR

The **Label** column holds a thumbnail of the code for `<site>/#/check/<code>`. Click it and the label
opens full size with **Print label** (only the label prints, not the page around it), **Copy link** and
**Open check page**. **Esc** or a click outside closes it. Scanning the printed code needs no app and
no login. The table refreshes every 10 seconds.

If a role is not allowed to do what you clicked, the red line under the form is the server's own
sentence — usually `pharmacist cannot do this` — not a generic failure.

## 6. Public QR check

`https://your-site/#/check/VAX-001` opens a single card, no sign-in and no navigation — the address is
handled before the app even looks for a session, so it works on a locked phone:

- A coloured circle with the verdict — **Safe**, **At Risk** or **Discard**.
- The vaccine name and `Expires <date>`, with **expired** marked once the date has passed.
- One line saying what to do: *Held between 2 and 8 °C for its whole life so far. Use normally.* when
  Safe; *Part of its heat budget is spent. A pharmacist should confirm before it is used.* when At
  Risk; *Its heat budget is gone or it is past expiry. Do not use it.* when Discard.
- A footnote that this is the fridge's automatic reading and a pharmacist's decision overrides it.

An expired batch always reads **Discard**, whatever its temperature history. An unknown code shows a
card titled **Unknown batch** with `No batch <code> is registered`, and a page that loaded but could
not reach its API says `Cannot reach the service that checks batch <code>` — never a blank screen.

## 7. Audit log

Admin and inspector only. The table shows the newest 200 records with `#`, `Event`, `Details`, `Hash`
(the first 12 characters; hovering shows this row's hash and the one before it) and `Time (UTC)`,
printed as the server stored it rather than shifted into the laptop's timezone. Rejections, alerts,
failed logins, moves and resets are printed in red. The list loads when you open the tab and does not
poll — **Reload log** pulls whatever arrived since.

| Event | Written when |
| --- | --- |
| `SEED` | First start: demo users, fridges and batches created |
| `LOGIN_FAILED` | A wrong password was tried |
| `MESSAGE_REJECTED` | A device message arrived with a bad signature, a stale timestamp, a replayed nonce, or an unknown device id. Details name the device and the reason, and `suppressed=N` counts the identical rejections the 60-second throttle folded into this row |
| `DOOR_ALERT` | A door stayed open past 60 seconds |
| `BATCH_STATUS` | A batch crossed into At Risk or Discard |
| `BATCH_CREATED` / `BATCH_MOVED` / `ADMIN_RESET` | The matching inventory action |

**Verify integrity** recomputes the hash chain over every record — not just the 200 on screen — and
answers `Chain intact, N records` in green with the head hash beside it, or
`Tampering detected at record #n: <reason>` in red. Each row's hash covers the previous row's hash, so
editing or deleting one record breaks every link after it and the check points at the first broken one.
Deleting the newest rows is caught separately by the anchor file, which is why the reason can read
`newest records were deleted`. A flood of rejections does not bury the log: they are folded into one
row per device and reason per minute, and the Devices page adds the suppressed counts back.

## 8. Things that surprise people


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
  exposure. The other side of that rule: anything at or before the last accepted timestamp is dropped,
  so a node has to flush its offline buffer **oldest-first, before it sends a live reading**. One live
  sample landing ahead of the backlog marks every queued hour after it as out-of-order, and those
  minutes are gone. The firmware drains its queue at boot; a node that restarts into the middle of a
  backlog loses what it had not replayed yet.
- **A node's key cannot be read back.** If the panel that showed it was closed, or the node was
  reflashed and the file lost, there is nothing to recover — **Rotate its key** issues a new one and
  the old dies on the next packet. That is deliberate: no endpoint and no audit row carries a secret.
## 9. Connect a remote ESP32

For the person holding the board, in another building, who has not seen this repository. You need four
things: the code (this repo, any branch that has `firmware/`), Arduino IDE with the ESP32 board
package, the Wi-Fi the fridge will sit on, and the API's URL — the host the signed-in web app prints in
its header, or whatever the person who deployed it gives you. Nothing on the board can read the
dashboard, and nothing on the dashboard can change the board except the one-word `batch_status` echo.

### What to install first

Arduino IDE 2.x, then **Boards manager → "esp32" by Espressif** and **Library manager →** these four:
`DHT sensor library` (Adafruit), `Adafruit GFX Library`, `Adafruit SSD1306`, and `PubSubClient`
(Nick O'Leary) only if the node will use MQTT. Select **ESP32 Dev Module** as the board. If the port
never appears, hold the board's **BOOT** button while you plug the cable in, then release it.

### Steps

1. **Register the node and get its key.** This needs an admin login on the web app — ask whoever has
   one. **Devices → Register a node**: a name, and the exact `DEVICE_ID` you will flash (1–32
   characters of `A-Z a-z 0-9 . _ -`, because the same string becomes an MQTT topic and has to match
   character for character). Press **Register and get its key** and copy the two-line block:

   ```c
   #define DEVICE_ID   "fridge-3"
   #define HMAC_KEY    "the 32 hex characters this page showed once"
   ```

   The key is shown once and never again, by the page or by any endpoint. If the panel closes before
   you paste it, **Rotate its key** and take the new one.
2. **Copy `firmware/coldchain_node/cc_config.example.h` to `cc_config.h`**, in the same folder as
   `coldchain_node.ino`. The sketch will not build without that file, and `cc_config.h` is gitignored
   so the Wi-Fi password and the node key never end up in the repository. Do not edit the example
   itself — it is the template everyone else starts from.
3. **Fill in `cc_config.h`.** The two identity lines from step 1, then `WIFI_SSID` and `WIFI_PASS`
   (2.4 GHz only — this chip has no 5 GHz radio), then one transport:

   | | direct HTTPS (simplest remote path) | MQTT |
   | --- | --- | --- |
   | pick it | `#define INGEST_TRANSPORT INGEST_HTTP` | `#define INGEST_TRANSPORT INGEST_MQTT` |
   | the API | `API_BASE_URL "https://your-api-host.onrender.com"`, no trailing slash | the bridge that forwards `coldchain/<id>/reading` into `/api/sensor` runs beside the API, not on your laptop |
   | the broker | — | `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `MQTT_USE_TLS`. A hosted broker (HiveMQ Cloud and the rest) is port **8883** with `MQTT_USE_TLS 1` and the user/password from its console; a LAN box running `backend/mqtt_bridge.py` is **1883** with TLS 0 and both login lines left empty |
   | cold start | `USE_HTTPS_DIRECT 1` waits 30 s per send, because a sleeping free Render instance takes that long to answer the first request | the node buffers and retries on its own |

   Leave everything else in that file alone; the pins block is the wiring this board is built with.
4. **Flash it.** Open `coldchain_node.ino` — not `cc_config.h` — press Verify, then Upload. When it
   says "Hard resetting via RTS pin", press the board's **EN** button.
5. **Watch the Serial Monitor at 115200 baud.** The healthy sequence is `node fridge-3 up, transport
   http` (or `mqtt`), then the Wi-Fi connecting dots and an IP, then the first send a few seconds
   after the clock reports itself synced. The OLED shows the id and the current temperature. Two lines
   worth recognising:
   - `broker <host>:<port> refused (state -4)` — no route to that host and port, or `MQTT_USE_TLS 1`
     pointed at a plain 1883 listener (or TLS 0 at an 8883 one).
   - `broker ... refused (state 5)` — the broker is reachable and said no to `MQTT_USER`/`MQTT_PASS`.
6. **Look at the Devices page.** The dot turns green `online` within 20 s of the first accepted reading
   and red again 20 s after the last one. A node that is `offline` with no trace at all has had every
   packet refused — the table below is the whole list of why.

### The four refusals, and what each one costs you

Every one is HTTP **401** from `POST /api/sensor`, printed in the Serial Monitor and written to the
audit log with the device id.

| `detail` | cause | fix |
| --- | --- | --- |
| `invalid signature` | the `HMAC_KEY` in the build is not the one this server issued for that id; or a number was printed differently than it was signed; or the fleet key is still in the file (a registered node refuses it) | re-paste `HMAC_KEY` from the registration card, or rotate and reflash |
| `stale timestamp` | the clock has not synced, is more than 60 s from real time, or the backlog is older than 3 hours | let NTP finish; send offline readings with `buffered: true`, which the server allows for 3 h |
| `unknown device` | nobody registered this `DEVICE_ID` — a typo is enough, and so is a node that was unregistered | register the exact id, or fix the spelling and reflash |
| `replayed nonce` | a packet the server already stored, resent | nothing — the node drops that sample and moves on; it is the expected cost of retrying |

### Two rules that fail silently

- **A number has to be printed the way it was signed: `5.0`, not `5`.** The canonical string is
  `device|temperature|door|ts|nonce|power|battery|compressor|buffered`, each value spelled exactly as
  Python's `str(float)` spells it, and its SHA-256/HMAC is the signature. `5` and `5.0` are the same
  temperature and completely different signatures, so a formatting change on one side is
  `invalid signature` on every packet on the other. The firmware prints through
  `cc::canonical()` in `coldchain_node/coldchain_core.h`; `bash firmware/tests/run_tests.sh` compares
  its output against vectors generated by the real `hmac_auth.canonical()`, so run that before you
  believe a formatting idea is safe.
- **The clock comes from NTP, in UTC.** The signature carries unix seconds, so the node calls
  `configTime(0, 0, NTP_SERVER)` — offset zero on purpose. A node that sets its own local time, or
  applies a timezone or DST offset, is one to three hours out and every reading it sends is `stale
  timestamp`. If the Wi-Fi blocks NTP, point `NTP_SERVER` at whatever time server that network allows;
  the dashboard cannot fix a clock, only show what arrived.

### If the board is a demo rather than a deployment

The TLS paths call `setInsecure()` unless you pin a CA, which means the traffic is encrypted but the
node does not check who it is talking to. That is fine for a hackathon bench and not fine for a fridge
that holds real vaccine: put the server's CA in `cc_config.h` as `API_CA_CERT` (or `MQTT_CA_CERT` for
a broker) and the same block switches to `setCACert()` and verifies the certificate and the host name.

