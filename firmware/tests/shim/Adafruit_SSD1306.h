// Stubs for the two Adafruit display libraries, as one pair of headers.
#pragma once
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include "Arduino.h"
#include "Wire.h"

#define SSD1306_WHITE 1
#define SSD1306_SWITCHCAPVCC 0x3C

class Adafruit_GFX {
 public:
  virtual ~Adafruit_GFX() {}
  void setTextSize(uint8_t) {}
  void setTextColor(uint16_t) {}
  void setCursor(int16_t, int16_t) {}
  void clearDisplay() {}
  virtual void display() {}
  size_t print(const char* s) { return strlen(s); }
  size_t printf(const char* fmt, ...) { va_list a; va_start(a, fmt); int n = vprintf(fmt, a); va_end(a); return n; }
};

class Adafruit_SSD1306 : public Adafruit_GFX {
 public:
  Adafruit_SSD1306(int16_t w, int16_t h, TwoWire* wire, int16_t rst)
      : w_(w), h_(h), wire_(wire), rst_(rst) {}
  bool begin(uint8_t vcc, uint8_t addr) { (void)vcc; (void)addr; return true; }

 private:
  int16_t w_, h_, rst_;
  TwoWire* wire_;
};
