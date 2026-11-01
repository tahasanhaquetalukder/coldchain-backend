#pragma once
#include <stdint.h>
#include "Arduino.h"
#include "WiFi.h"

typedef void (*MqttCallback)(char* topic, uint8_t* payload, unsigned int length);

class PubSubClient {
 public:
  // The real client is templated over any Stream; the sketch only ever hands it a WiFiClient or a
  // WiFiClientSecure, both of which derive from the first.
  explicit PubSubClient(WiFiClient&) {}
  void setServer(const char* host, uint16_t port) { (void)host; (void)port; }
  void setBufferSize(uint16_t) {}
  void setCallback(MqttCallback) {}
  bool connect(const char*) { return true; }
  bool connect(const char*, const char*, const char*) { return true; }
  int8_t state() { return 0; }
  bool connected() { return true; }
  bool subscribe(const char*, uint8_t) { return true; }
  bool publish(const char*, const uint8_t*, unsigned int, bool) { return true; }
  void loop() {}
};
