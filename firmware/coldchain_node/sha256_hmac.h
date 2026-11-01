// Self-contained SHA-256 + HMAC-SHA256 for the ColdChain fridge node.
//
// The ESP32 core ships mbedTLS, but reaching for it means the signing path cannot be compiled and
// tested off-device. This header uses only <stdint.h>/<string.h>, so the same bytes that sign a
// reading on the ESP32 are the bytes the host test suite checks against Python's hmac module.
//
// K and H were generated from their definitions (floor(cuberoot(prime) * 2^32) and
// floor(sqrt(prime) * 2^32), first 32 bits of the fractional part) rather than copied, so a typo in
// a constant shows up as a failed FIPS/RFC 4231 vector in firmware/tests instead of a silent drift.
#ifndef CC_SHA256_HMAC_H
#define CC_SHA256_HMAC_H

#include <stdint.h>
#include <string.h>

namespace cc {

inline const uint32_t* sha256K() {
  static const uint32_t k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  };
  return k;
}

class Sha256 {
 public:
  void update(const uint8_t* data, size_t len) {
    totalLen += len;
    while (len) {
      size_t take = 64 - bufLen;
      if (take > len) take = len;
      memcpy(buf + bufLen, data, take);
      bufLen += take; data += take; len -= take;
      if (bufLen == 64) { compress(buf); bufLen = 0; }
    }
  }
  void update(const char* s) { update(reinterpret_cast<const uint8_t*>(s), strlen(s)); }

  void finish(uint8_t out[32]) {
    uint64_t bitLen = totalLen * 8ull;
    uint8_t pad = 0x80;
    update(&pad, 1);
    uint8_t zero = 0;
    while (bufLen != 56) update(&zero, 1);
    uint8_t lenBe[8];
    for (int i = 0; i < 8; i++) lenBe[i] = static_cast<uint8_t>(bitLen >> (56 - 8 * i));
    update(lenBe, 8);
    for (int i = 0; i < 8; i++)
      for (int b = 3; b >= 0; b--) out[i * 4 + (3 - b)] = static_cast<uint8_t>(h[i] >> (8 * b));
  }

 private:
  void compress(const uint8_t* block) {
    const uint32_t* K = sha256K();
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
      w[i] = (uint32_t(block[i * 4]) << 24) | (uint32_t(block[i * 4 + 1]) << 16) |
             (uint32_t(block[i * 4 + 2]) << 8) | block[i * 4 + 3];
    for (int i = 16; i < 64; i++) {
      uint32_t s0 = ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >> 3);
      uint32_t s1 = ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
      uint32_t S1 = ror(e, 6) ^ ror(e, 11) ^ ror(e, 25);
      uint32_t ch = (e & f) ^ (~e & g);
      uint32_t t1 = hh + S1 + ch + K[i] + w[i];
      uint32_t S0 = ror(a, 2) ^ ror(a, 13) ^ ror(a, 22);
      uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      uint32_t t2 = S0 + maj;
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  static uint32_t ror(uint32_t x, uint32_t n) { return (x >> n) | (x << (32 - n)); }

  uint32_t h[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
  uint8_t buf[64] = { 0 };
  size_t bufLen = 0;
  uint64_t totalLen = 0;
};

inline void sha256(const uint8_t* data, size_t len, uint8_t out[32]) {
  Sha256 s; s.update(data, len); s.finish(out);
}

inline void hmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t msgLen,
                       uint8_t out[32]) {
  uint8_t block[64], kPad[64], inner[32];
  memset(block, 0, sizeof block);
  if (keyLen > 64) { sha256(key, keyLen, block); }        // keys longer than a block are hashed first
  else memcpy(block, key, keyLen);
  for (int i = 0; i < 64; i++) kPad[i] = block[i] ^ 0x36;  // ipad
  Sha256 s; s.update(kPad, 64); s.update(msg, msgLen); s.finish(inner);
  for (int i = 0; i < 64; i++) kPad[i] = block[i] ^ 0x5c;  // opad
  Sha256 t; t.update(kPad, 64); t.update(inner, 32); t.finish(out);
}

// The signature field the server compares with hmac.compare_digest(sign(msg), signature):
// lowercase hex, which is what Python's hexdigest() produces.
inline void hmacHex(const char* key, const char* msg, char out[65]) {
  uint8_t digest[32];
  hmacSha256(reinterpret_cast<const uint8_t*>(key), strlen(key),
             reinterpret_cast<const uint8_t*>(msg), strlen(msg), digest);
  static const char* HEX = "0123456789abcdef";
  for (int i = 0; i < 32; i++) {
    out[i * 2] = HEX[digest[i] >> 4];
    out[i * 2 + 1] = HEX[digest[i] & 15];
  }
  out[64] = '\0';
}

}  // namespace cc

#endif
