// Stubs for the two Adafruit display libraries, split the way the real headers split them: GFX is the
// base class and this file adds the SSD1306 device on top. The sketch includes both, in that order.
#pragma once
#include "Adafruit_GFX.h"

class Adafruit_SSD1306 : public Adafruit_GFX {
 public:
  Adafruit_SSD1306(int16_t w, int16_t h, TwoWire* wire, int16_t rst)
      : w_(w), h_(h), rst_(rst), wire_(wire) {}
  bool begin(uint8_t vcc, uint8_t addr) { (void)vcc; (void)addr; return true; }

 private:
  int16_t w_, h_, rst_;
  TwoWire* wire_;
};
