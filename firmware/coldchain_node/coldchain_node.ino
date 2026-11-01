/*
  ColdChain fridge node - Task 1 (sensing + MQTT + compressor), Task 2 (red-LED latch),
  Task 3 (power failure, 40 min offline buffer, door buzzer).

  Every decision lives in coldchain_core.h so it can be compiled and asserted off-device; this file
  only reads pins, drives pins and moves bytes. Configuration - pins, Wi-Fi, transport, device id -
  is in cc_config.h: copy cc_config.example.h to cc_config.h and fill it in before flashing. The
  firmware will not build without that file, and cc_config.h is gitignored because it holds secrets.

  The node does not track the heat budget. It is per batch, batches move between fridges, and the
  server owns it - so the node signs each reading and the server's answer carries the worst batch
  status in this fridge. A "Discard" answer latches the red LED until an admin reset makes the next
  answer something else.

  Two clocks are in play on purpose. Durations (compressor minimum off-time, the 60-second door
  window) are measured on monotonic millis(), which is valid from the first loop and survives an NTP
  failure. Only the signed ts needs unix seconds, and a reading taken before NTP answers waits in the
  buffer until its timestamp can be backfilled.
*/
#include <Arduino.h>
#include <time.h>
#include "esp_system.h"

#include <WiFi.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "cc_config.h"
#include "coldchain_core.h"
#include "sha256_hmac.h"

#if INGEST_TRANSPORT == INGEST_MQTT
#include <PubSubClient.h>
#if MQTT_USE_TLS
#include <WiFiClientSecure.h>
#endif
#else
#include <HTTPClient.h>
#if API_TLS || USE_HTTPS_DIRECT
#include <WiFiClientSecure.h>
#endif
#endif

static const cc::Limits LIMITS = cc::Limits::taskSpec();
// Not named `clock`: <time.h> is included for time() and declares ::clock(), and a namespace-scope
// object of the same name is a redeclaration error. nodeClock is spelled that way for no other reason.
static cc::Clock nodeClock;
static cc::Compressor compressor;
static cc::DoorWatch doorWatch;
static cc::RedLed redLed;
static cc::PowerModel power;
static cc::Sample backing[BUFFER_CAPACITY];
static cc::ReadingLog rlog(backing, BUFFER_CAPACITY);

static DHT dht(PIN_DHT_DATA, DHT22);
static Adafruit_SSD1306 oled(128, 64, &Wire, -1);
static WiFiClient wifiClient;
#if INGEST_TRANSPORT == INGEST_MQTT
#if MQTT_USE_TLS
// PubSubClient speaks MQTT over any Stream it is handed, so TLS is a different transport object and
// not a different protocol: same topics, same body, same signature.
static WiFiClientSecure brokerTransport;
static PubSubClient net(brokerTransport);
#else
static PubSubClient net(wifiClient);
#endif
static char readTopic[64], cmdTopic[64];
#endif

static uint32_t lastSampleMs = 0, lastPowerTickMs = 0, lastSendMs = 0, lastBrokerMs = 0;
static uint32_t sentLive = 0, sentBacklog = 0, droppedByServer = 0;
static bool doorOpen = false, mainsOk = true, clockSynced = false;
static int lastDoorRaw = HIGH, lastPwrRaw = HIGH;
static uint32_t doorStableMs = 0, pwrStableMs = 0;
static float lastTempC = NAN;

// ---------------------------------------------------------------- pins
static void writeRelay(bool on) {
#if RELAY_ACTIVE_LOW
  digitalWrite(PIN_RELAY, on ? LOW : HIGH);      // most ESP32 relay modules click on a LOW
#else
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
#endif
}
static void writeBuzzer(bool on) {
#if BUZZER_ACTIVE_HIGH
  digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
#else
  digitalWrite(PIN_BUZZER, on ? LOW : HIGH);
#endif
}

static void makeNonce(char out[33]) {
  static const char* HEX = "0123456789abcdef";
  for (int i = 0; i < 16; i++) {
    uint8_t b = static_cast<uint8_t>(esp_random() & 0xff);
    out[i * 2] = HEX[b >> 4];
    out[i * 2 + 1] = HEX[b & 15];
  }
  out[32] = '\0';
}

static uint32_t monoS() { return millis() / 1000u; }

// ---------------------------------------------------------------- transport
struct Verdict {
  int http;              // 0 = the transport itself failed, so the sample stays queued
  char detail[64];       // the server's HTTPException body, empty when there was none
};

#if INGEST_TRANSPORT == INGEST_MQTT
static void onCommand(char* topic, uint8_t* payload, unsigned int len) {
  char body[224];
  unsigned int n = len < sizeof body - 1 ? len : sizeof body - 1;
  memcpy(body, payload, n);
  body[n] = '\0';
  char status[16];
  if (cc::findStringField(body, "batch_status", status, sizeof status)) {
    redLed.step(status);
    Serial.printf("command %s -> batch_status=%s\n", topic, status);
  } else if (cc::jsonHasNull(body, "batch_status")) {
    redLed.step("");                             // no batches left in this fridge: nothing to discard
    Serial.println("command -> batch_status=null");
  }
}

#if MQTT_USE_TLS
// Bring-up only, and the one line you should change before this node goes anywhere real:
// setInsecure() still encrypts, but it checks nothing about the certificate it was given, so anyone on
// the path can impersonate the broker and feed this node fake commands or drop its readings. Put the
// broker's CA in cc_config.h as   #define MQTT_CA_CERT "-----BEGIN CERTIFICATE-----\n...\n"
// and this same block verifies the certificate and the host name instead.
static void configureBrokerTls() {
#ifdef MQTT_CA_CERT
  brokerTransport.setCACert(MQTT_CA_CERT);
  Serial.println("broker TLS: verifying against the pinned CA");
#else
  brokerTransport.setInsecure();
  Serial.println("broker TLS: setInsecure - bring-up only, pin MQTT_CA_CERT for the final build");
#endif
}
#endif

// An empty MQTT_USER is the anonymous connect that backend/mqtt_bridge.py and a local mosquitto
// answer, so the defaults stay exactly as they were; a hosted broker sets both.
static bool brokerConnect() {
  const char* user = MQTT_USER;
  bool ok = (user && user[0]) ? net.connect("esp32-" DEVICE_ID, user, MQTT_PASS)
                              : net.connect("esp32-" DEVICE_ID);
  if (ok) {
    net.subscribe(cmdTopic, 1);
  } else {
    // state() separates the two failures a remote teammate actually hits: -4 is no route to the
    // broker (wrong host/port, or TLS turned on against a plain port), 5 is the login refused.
    Serial.printf("broker %s:%d refused (state %d) - readings keep buffering\n",
                  MQTT_HOST, MQTT_PORT, net.state());
  }
  return ok;
}

// Handing the JSON to the broker is the whole of the MQTT contract; the bridge that subscribes to
// coldchain/<device>/reading is the thing that POSTs it. A publish returns true once the broker has
// accepted it at QoS 1, and the node counts the sample from that moment: it cannot see the bridge's
// HTTP answer, which is why the bridge runs beside the API and keeps a session for this client.
static void transportSend(const char* body, Verdict* v) {
  v->http = 0;
  v->detail[0] = '\0';
  if (net.publish(readTopic, reinterpret_cast<const uint8_t*>(body), strlen(body), true)) {
    net.loop();                                  // QoS 1 needs the ack to actually go out
    v->http = 202;
  }
}
#else
// USE_HTTPS_DIRECT is the remote-teamate setting: the node POSTs the same signed body straight to the
// hosted API, so nobody has to run a broker or the bridge for it to appear on the dashboard.
static void transportSend(const char* body, Verdict* v) {
  v->http = 0;
  v->detail[0] = '\0';
  HTTPClient http;
#if API_TLS || USE_HTTPS_DIRECT
  static WiFiClientSecure secureClient;
  // Encrypting but unverified: setInsecure() accepts any certificate, which is fine while the node is
  // proving it can reach the API and not fine afterwards. A fake endpoint still cannot get a forged
  // reading accepted - the signature is over the body, not over the TLS - but it can drop readings and
  // it can serve a page that lies about a batch. Pin the CA for the final build:
  //   #define API_CA_CERT "-----BEGIN CERTIFICATE-----\n...\n"
#ifdef API_CA_CERT
  secureClient.setCACert(API_CA_CERT);
#else
  secureClient.setInsecure();
#endif
  if (!http.begin(secureClient, API_BASE_URL API_SENSOR_PATH)) return;
#else
  if (!http.begin(wifiClient, API_BASE_URL API_SENSOR_PATH)) return;
#endif
  http.addHeader("Content-Type", "application/json");
#if USE_HTTPS_DIRECT
  // A free Render instance sleeps after ~15 idle minutes and the first request is the one that wakes
  // it, which takes 30-50 s. A short timeout gives up first, and the node then looks broken while it
  // is really buffering.
  http.setTimeout(30000);
#else
  http.setTimeout(8000);
#endif
  int code = http.POST(body);
  if (code > 0) {
    String reply = http.getString();
    char text[256];
    reply.toCharArray(text, sizeof text);
    cc::findStringField(text, "detail", v->detail, sizeof v->detail);
    char status[16];
    if (cc::findStringField(text, "batch_status", status, sizeof status)) redLed.step(status);
    else if (cc::jsonHasNull(text, "batch_status")) redLed.step("");
    v->http = code;
  }
  http.end();
}
#endif

// ---------------------------------------------------------------- sampling
static void takeSample(uint32_t boot) {
  cc::Sample s;
  s.tempC = lastTempC;
  s.bootMs = boot;
  s.tsS = nodeClock.at(boot);
  makeNonce(s.nonce);
  s.doorOpen = doorOpen;
  s.powerOk = mainsOk;
  s.compressorOn = compressor.on();
  s.batteryPct = power.pct();
  if (!rlog.push(s)) Serial.println("buffer full, oldest reading lost");
  if (!s.tsS) Serial.println("clock not synced yet, reading held in buffer");
}

static void syncClock(uint32_t boot) {
  time_t now = time(nullptr);
  if (now < 1600000000) return;                  // still 1970-ish: NTP has not answered yet
  if (!clockSynced) {
    clockSynced = true;
    Serial.println("ntp synced");
  }
  nodeClock.sync(static_cast<uint32_t>(now), boot);
  uint16_t filled = rlog.backfill(nodeClock, boot);
  if (filled) Serial.printf("backfilled %u buffered readings\n", filled);
}

// ---------------------------------------------------------------- sending
static void drainQueue(uint32_t boot) {
  const cc::Sample* s = rlog.oldest();
  if (!s || boot - lastSendMs < 1000) return;
  bool up = WiFi.status() == WL_CONNECTED;
#if INGEST_TRANSPORT == INGEST_MQTT
  up = up && net.connected();
#endif
  if (!up) return;
  lastSendMs = boot;

  int mode = cc::sendMode(rlog.pending(), clockSynced, s->tsS);
  if (!mode) return;
  bool fromBacklog = (mode == 2);

  cc::Wire w = cc::wireOf(s->tempC, s->tsS, s->batteryPct);
  char canon[CANON_BUF], sig[65], body[PAYLOAD_BUF];
  // Must be byte-identical to backend/app/hmac_auth.py canonical()+sign() - same field order, same
  // "X.Y" floats, "buffered" inside the signature - which firmware/tests/run_tests.sh proves per commit.
  cc::canonical(canon, sizeof canon, DEVICE_ID, w, s->doorOpen, s->nonce, s->powerOk,
                s->compressorOn, fromBacklog);
  cc::hmacHex(HMAC_KEY, canon, sig);
  cc::payload(body, sizeof body, DEVICE_ID, w, s->doorOpen, s->nonce, sig, s->powerOk,
              s->compressorOn, fromBacklog);

  Verdict v;
  transportSend(body, &v);
  cc::Action a = cc::decide(v.http, v.detail[0] ? v.detail : nullptr,
                            rlog.oldestAgeS(nodeClock.at(boot)), 1, LIMITS);
  if (a == cc::ACT_ACCEPTED) {
    rlog.advance();
    if (fromBacklog) sentBacklog++; else sentLive++;
  } else if (a == cc::ACT_DROP) {
    rlog.advance();
    droppedByServer++;
    Serial.printf("dropping an unreadable sample: %s\n", v.detail);
  }
}

// ---------------------------------------------------------------- outputs
static void drawScreen() {
  cc::Reading r = cc::classify(LIMITS, lastTempC);
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(2);
  oled.setCursor(0, 0);
  if (isnan(lastTempC)) oled.print("--.-");
  else oled.printf("%2.1f", lastTempC);
  oled.setTextSize(1);
  oled.setCursor(96, 0);
  oled.print("C");
  oled.setCursor(0, 18);
  oled.printf("%s  %s", cc::readingName(r), redLed.on() ? "DISCARD" : (mainsOk ? "mains" : "BATT"));
  oled.setCursor(0, 28);
  oled.printf("door %s %lus  comp %s", doorOpen ? "OPEN" : "shut",
              (unsigned long)doorWatch.openForS(monoS()), compressor.on() ? "on" : "off");
  oled.setCursor(0, 38);
  oled.printf("buf %u/%u lost %lu pwr %u%%", (unsigned)rlog.pending(), (unsigned)rlog.capacity(),
              (unsigned long)rlog.dropped(), (unsigned)power.pct());
  oled.setCursor(0, 48);
  if (!clockSynced) oled.print("waiting for NTP time");
  else oled.printf("live %lu back %lu drop %lu", (unsigned long)sentLive,
                   (unsigned long)sentBacklog, (unsigned long)droppedByServer);
  oled.display();
}

static void updateOutputs() {
  cc::Reading r = cc::classify(LIMITS, lastTempC);
  digitalWrite(PIN_LED_GREEN, r == cc::RD_SAFE ? HIGH : LOW);
  bool blink = (monoS() % 2) == 0;               // one heartbeat per second, cheap and legible
  if (redLed.on()) digitalWrite(PIN_LED_RED, HIGH);            // Task 2: solid until an admin reset
  else if (r != cc::RD_SAFE || doorWatch.buzzer()) digitalWrite(PIN_LED_RED, blink ? HIGH : LOW);
  else digitalWrite(PIN_LED_RED, LOW);
  writeBuzzer(doorWatch.buzzer());
  writeRelay(compressor.on());
  drawScreen();
}

// ---------------------------------------------------------------- buttons and switch
static void pollDoor() {
  int raw = digitalRead(PIN_DOOR);
  if (raw != lastDoorRaw) { lastDoorRaw = raw; doorStableMs = millis(); return; }
  if (millis() - doorStableMs < 50) return;
  bool open = (raw == LOW);                      // reed switch to GND: LOW = magnet away = open
  if (open == doorOpen) return;
  doorOpen = open;
  Serial.printf("door %s -> publishing now\n", open ? "OPEN" : "closed");
  takeSample(millis());                          // Task 1: send on a door-state change, not on the tick
}

static void pollPowerButton() {
  static bool latched = false;                   // one toggle per press, not one per loop
  int raw = digitalRead(PIN_PWR_BTN);
  if (raw != lastPwrRaw) { lastPwrRaw = raw; pwrStableMs = millis(); return; }
  if (millis() - pwrStableMs < 50) return;
  bool pressed = (raw == LOW);
  if (!pressed) { latched = false; return; }
  if (latched) return;
  latched = true;
  mainsOk = !mainsOk;
  Serial.printf("mains %s (battery %u%%)\n", mainsOk ? "restored" : "SIMULATED FAILURE", power.pct());
  takeSample(millis());
}

static void stepBattery(uint32_t boot) {
  uint32_t dt = (boot - lastPowerTickMs) / 1000u;
  if (dt < 10) return;
  lastPowerTickMs = boot;
  power.step(mainsOk, dt);
}

// ---------------------------------------------------------------- lifecycle
void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY, OUTPUT); writeRelay(false);
  pinMode(PIN_BUZZER, OUTPUT); writeBuzzer(false);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_DOOR, INPUT_PULLUP);
  pinMode(PIN_PWR_BTN, INPUT_PULLUP);
  lastDoorRaw = digitalRead(PIN_DOOR);
  lastPwrRaw = digitalRead(PIN_PWR_BTN);
  doorOpen = (lastDoorRaw == LOW);

  dht.begin();
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) Serial.println("OLED not found at 0x3C");
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);
  oled.printf("ColdChain %s", DEVICE_ID);
  oled.display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  configTime(0, 0, NTP_SERVER);                  // UTC: the signature carries unix seconds

#if INGEST_TRANSPORT == INGEST_MQTT
  snprintf(readTopic, sizeof readTopic, "coldchain/%s/reading", DEVICE_ID);
  snprintf(cmdTopic, sizeof cmdTopic, "coldchain/%s/command", DEVICE_ID);
#if MQTT_USE_TLS
  configureBrokerTls();
#endif
  net.setServer(MQTT_HOST, MQTT_PORT);
  net.setBufferSize(PAYLOAD_BUF);                // PubSubClient defaults to 256; the body is ~270 B
  net.setCallback(onCommand);
#endif
  Serial.printf("node %s up, transport %s\n", DEVICE_ID,
                INGEST_TRANSPORT == INGEST_MQTT ? "mqtt" : "http");
}

void loop() {
  uint32_t boot = millis();

  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t lastWifi = 0;
    if (boot - lastWifi > 5000) { lastWifi = boot; WiFi.begin(WIFI_SSID, WIFI_PASS); }
  }
#if INGEST_TRANSPORT == INGEST_MQTT
  if (!net.connected() && WiFi.status() == WL_CONNECTED && boot - lastBrokerMs > 5000) {
    lastBrokerMs = boot;
    brokerConnect();
  }
  net.loop();
#endif

  syncClock(boot);
  pollDoor();
  pollPowerButton();

  if (boot - lastSampleMs >= LIMITS.sampleEveryS * 1000u) {
    lastSampleMs = boot;
    float t = dht.readTemperature();
    if (isnan(t)) Serial.println("DHT read failed");
    else {
      lastTempC = t;
      compressor.step(LIMITS, t, monoS());       // decided before the sample signs it
    }
    takeSample(boot);
  }

  stepBattery(boot);
  doorWatch.step(doorOpen, monoS(), LIMITS);     // monotonic: a dead NTP must not silence the buzzer
  drainQueue(boot);
  updateOutputs();
  delay(40);
}
