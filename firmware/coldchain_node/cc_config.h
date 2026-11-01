// The one file to edit before flashing. Two boards in the demo differ only here.
#ifndef CC_CONFIG_H
#define CC_CONFIG_H

// ---------------------------------------------------------------- identity
// Must equal a Fridge.device_id row. The API seeds fridge-1 and fridge-2, and an unknown id is
// rejected and written to the audit chain, so a typo shows up as MESSAGE_REJECTED in the log rather
// than as a silent gap on the dashboard.
#define DEVICE_ID       "fridge-1"

// Must equal HMAC_SECRET_KEY on the server (backend/app/hmac_auth.py falls back to this string).
#define HMAC_KEY        "super-secret-hackathon-key"

// ---------------------------------------------------------------- network
#define WIFI_SSID       "your-wifi-name"
#define WIFI_PASS       "your-wifi-password"
#define NTP_SERVER      "pool.ntp.org"

// Which half of the spec carries the reading. 1 = MQTT, which is what Task 1 asks for and what the
// OLED/bridge demo uses. 2 = the node POSTs signed JSON straight to /api/sensor, which is Task 4's
// path and needs no broker - useful when the venue Wi-Fi has no broker to point at.
// Both send the identical signed body; only the transport changes. Pass -DINGEST_TRANSPORT=2 to
// firmware/tests/run_tests.sh's syntax check to compile the other one.
#define INGEST_MQTT     1
#define INGEST_HTTP     2
#ifndef INGEST_TRANSPORT
#define INGEST_TRANSPORT INGEST_MQTT
#endif

#if INGEST_TRANSPORT == INGEST_MQTT
#define MQTT_HOST       "192.168.1.10"     // the machine running backend/mqtt_bridge.py
#define MQTT_PORT       1883
#else
#define API_BASE_URL    "https://your-api-host.onrender.com"  // no trailing slash
#define API_SENSOR_PATH "/api/sensor"
#define API_TLS         1    // 1 for an https host, 0 for a plain http one on the LAN
#endif

// ---------------------------------------------------------------- pins (ESP32 devkit v1)
// GPIO 6-11 drive the flash chip and 34-39 are input-only; none of them are used here.
#define PIN_DHT_DATA    4     // DHT22 data, 10k pull-up to 3V3
#define PIN_OLED_SDA    21    // SSD1306 I2C, address 0x3C
#define PIN_OLED_SCL    22
#define PIN_DOOR        16    // reed switch to GND; INPUT_PULLUP, LOW means open
#define PIN_PWR_BTN     17    // Task 3's mains-failure button, to GND, INPUT_PULLUP
#define PIN_RELAY       14    // compressor relay module, IN
#define PIN_BUZZER      27    // active-high piezo
#define PIN_LED_GREEN   25    // Safe
#define PIN_LED_RED     26    // Warning, and latched solid while the server says Discard

// Most ESP32 relay modules are wired active-low (relay clicks when IN is pulled to GND).
#define RELAY_ACTIVE_LOW  1
#define BUZZER_ACTIVE_HIGH 1

// ---------------------------------------------------------------- sizing
#define SAMPLE_EVERY_S  5
#define BUFFER_MINUTES  40    // Task 3 asks for at least 30
// 480 samples x sizeof(cc::Sample) ~ 48 B, so roughly 20 KB of DRAM held statically.
#define BUFFER_CAPACITY (BUFFER_MINUTES * 60 / SAMPLE_EVERY_S)

#define DOOR_OPEN_LIMIT_S 60

// Payload buffers: canonical is ~100 B, the signed JSON ~260 B.
#define CANON_BUF 192
#define PAYLOAD_BUF 512

#endif
