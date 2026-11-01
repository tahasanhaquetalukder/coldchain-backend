// Stand-ins for the Arduino core, enough of it that the compiler can check coldchain_node.ino for
// typos, wrong member names and unreachable branches. They do NOT model the real libraries'
// behaviour, so a clean syntax check proves the sketch is self-consistent - not that it runs, and
// not that a library signature changed. Flashing a board is still the only real test.
#pragma once
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HIGH 0x1
#define LOW  0x0
#define OUTPUT 0x1
#define INPUT 0x0
#define INPUT_PULLUP 0x2

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int digitalRead(uint8_t) { return HIGH; }
inline uint32_t millis() { static uint32_t t = 0; t += 40; return t; }
inline void delay(uint32_t) {}
// esp32-hal-time.h declares this on the real core, with the two extra servers defaulted.
inline void configTime(long, int, const char*, const char* = nullptr, const char* = nullptr) {}

class String {
 public:
  String() { buf_[0] = '\0'; }
  String(const char* s) { strncpy(buf_, s ? s : "", sizeof buf_ - 1); buf_[sizeof buf_ - 1] = '\0'; }
  size_t length() const { return strlen(buf_); }
  const char* c_str() const { return buf_; }
  void toCharArray(char* dest, size_t n) const { strncpy(dest, buf_, n - 1); dest[n - 1] = '\0'; }

 private:
  char buf_[512];
};

class SerialShim {
 public:
  void begin(unsigned long) {}
  void print(const char*) {}
  void println(const char*) {}
  void printf(const char* fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); }
};
static SerialShim Serial;  // static, not inline: inline variables need C++17 and this check has to run on the toolchain the tests use
