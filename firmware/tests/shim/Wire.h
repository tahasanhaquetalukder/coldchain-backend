#pragma once
#include <stdint.h>

class TwoWire {
 public:
  bool begin(int sda, int scl) { (void)sda; (void)scl; return true; }
};
static TwoWire Wire;  // static so the single-TU syntax check needs no C++17
