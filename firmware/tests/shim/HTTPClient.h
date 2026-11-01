#pragma once
#include <stddef.h>
#include "Arduino.h"
#include "WiFi.h"
#include "WiFiClientSecure.h"

class HTTPClient {
 public:
  bool begin(WiFiClient&, const char*) { return true; }
  bool begin(WiFiClientSecure&, const char*) { return true; }
  void addHeader(const char*, const char*) {}
  void setTimeout(int) {}
  int POST(const char*) { return 201; }
  String getString() { return String("{\"status\":\"ok\",\"batch_status\":\"Safe\"}"); }
  void end() {}
};
