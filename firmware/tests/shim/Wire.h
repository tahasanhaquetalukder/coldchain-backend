#pragma once
#include <stdint.h>

class TwoWire {
 public:
  bool begin(int sda, int scl) { (void)sda; (void)scl; return true; }
};
inline TwoWire Wire;
