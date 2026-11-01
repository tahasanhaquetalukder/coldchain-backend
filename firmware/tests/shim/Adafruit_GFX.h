// Stubs for the two Adafruit display libraries, split the way the real headers split them: this is the
// graphics base class, and Adafruit_SSD1306.h adds the display that derives from it.
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

