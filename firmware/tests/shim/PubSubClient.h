#pragma once
#include <stdint.h>
#include "Arduino.h"
#include "WiFi.h"

typedef void (*MqttCallback)(char* topic, uint8_t* payload, unsigned int length);

class PubSubClient {
 public:
  explicit PubSubClient(WiFiClient&) {}
  void setServer(const char* host, uint16_t port) { (void)host; (void)port; }
  void setBufferSize(uint16_t) {}
  void setCallback(MqttCallback) {}
  bool connect(const char*) { return true; }
  bool connected() { return true; }
  bool subscribe(const char*, uint8_t) { return true; }
  bool publish(const char*, const uint8_t*, unsigned int, bool) { return true; }
  void loop() {}
};
