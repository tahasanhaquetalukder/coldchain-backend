#pragma once
#include <stdint.h>
#include <cmath>

#define DHT22 0x11
#define SENSOR_UNREADABLE (NAN)

class DHT {
 public:
  DHT(uint8_t pin, uint8_t type) : pin_(pin), type_(type) {}
  void begin() {}
  float readTemperature() { return NAN; }

 private:
  uint8_t pin_, type_;
};
