// Copy this file to cc_config.h and fill it in before flashing.
//
// cc_config.h is gitignored because it holds the Wi-Fi password and the node's HMAC key; nothing in
// this example is a working credential. Two boards in the demo differ only here.
#ifndef CC_CONFIG_H
#define CC_CONFIG_H

// ---------------------------------------------------------------- identity
// Must equal a Fridge.device_id row. Register the node on the Devices page and copy the id from the
// paste block it shows. An unknown id is rejected and written to the audit chain, so a typo shows up
// as MESSAGE_REJECTED in the log rather than as a silent gap on the dashboard.
#define DEVICE_ID       "CHANGE_ME_DEVICE_ID"

// The key the Devices page showed once for this node. It is never stored anywhere readable, so if it
// is lost you rotate the key and reflash rather than looking for the old one. For a node that has
// never been given its own key this is the server's fleet HMAC_SECRET_KEY.
#define HMAC_KEY        "CHANGE_ME_KEY"

// ---------------------------------------------------------------- network
#define WIFI_SSID       "CHANGE_ME_WIFI"
#define WIFI_PASS       "CHANGE_ME_WIFI_PASSWORD"
#define NTP_SERVER      "pool.ntp.org"

// Which half of the spec carries the reading. 1 = MQTT, which is what Task 1 asks for and what the
// OLED/bridge demo uses. 2 = the node POSTs signed JSON straight to /api/sensor, which is Task 4's
// path and needs no broker - useful when the venue Wi-Fi has no broker to point at.
// Both send the identical signed body; only the transport changes. The rest of this file picks up the
// defines for whichever one you chose, so switching means re-reading the block that appears.
#define INGEST_MQTT     1
#define INGEST_HTTP     2
#ifndef INGEST_TRANSPORT
#define INGEST_TRANSPORT INGEST_MQTT
#endif

#if INGEST_TRANSPORT == INGEST_MQTT
#define MQTT_HOST       "CHANGE_ME_MQTT_HOST"   // a LAN box running backend/mqtt_bridge.py, or a cloud broker
#define MQTT_PORT       1883                    // 8883 with MQTT_USE_TLS, 1883 for the local bridge
#define MQTT_USER       ""                      // empty keeps today's anonymous connect, which is what
#define MQTT_PASS       ""                      // backend/mqtt_bridge.py listens for unless MQTT_USER is set
#define MQTT_USE_TLS    0                       // 1 for a cloud broker; needs WiFiClientSecure
// Optional, and the difference between a bring-up build and a shipping one. With MQTT_USE_TLS=1 and
// no CA here the node encrypts but accepts any certificate; paste the broker's CA PEM to verify it.
// #define MQTT_CA_CERT  "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
#else
// USE_HTTPS_DIRECT is how a node in another building gets onto the dashboard: it POSTs the signed
// reading straight to the deployed API, so nobody runs a broker or the bridge. It also lengthens the
// wait per send to 30 s, because the first request to a sleeping free Render instance is the one that
// wakes it. Set it to 0 for an API on the LAN that is already running.
#define USE_HTTPS_DIRECT 1
#define API_BASE_URL    "https://your-api-host.onrender.com"  // no trailing slash
#define API_SENSOR_PATH "/api/sensor"
#define API_TLS         1    // 1 for an https host, 0 for a plain http one on the LAN
// Same trade-off as MQTT_CA_CERT: without this the node encrypts and verifies nothing.
// #define API_CA_CERT    "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
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
