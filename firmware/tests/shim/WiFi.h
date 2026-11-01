#pragma once
#include "Arduino.h"

#define WL_CONNECTED 3
#define WL_DISCONNECTED 6
#define WIFI_STA 1

class WiFiClient {
 public:
  void stop() {}
};

class WiFiClass {
 public:
  int status() { return WL_CONNECTED; }
  void begin(const char*, const char*) {}
  void mode(uint8_t) {}
  void disconnect() {}
};
static WiFiClass WiFi;  // static so the single-TU syntax check needs no C++17
