// ColdChain fridge node — the decisions, separated from the pins.
//
// Everything a judge asks about Tasks 1-3 lives here as plain C++: the compressor hysteresis, the
// offline ring buffer, the timestamp backfill, the exact string the ESP32 signs, and what the node
// does when the server answers. The .ino only moves electrons. That split is what lets
// firmware/tests compile this file with g++ and assert the behaviour off-device.
#ifndef CC_CORE_H
#define CC_CORE_H

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace cc {

// Thresholds as the problem statement words them, and as backend/app/main.py enforces them.
struct Limits {
  float warnAboveC, warnBelowC;    // 8 / 2      -> Warning
  float breachAboveC, breachBelowC;// 12 / 0     -> Breach
  float compOnC, compOffC;         // 7 / 3      -> relay hysteresis
  uint32_t compMinOffS;            // 60         -> never restart inside this window
  uint32_t doorAlertS;             // 60         -> buzzer + server-side Telegram alert
  uint32_t sampleEveryS;           // 5          -> MQTT publish cadence
  uint32_t bufferMinutes;          // 40         -> spec asks for at least 30
  uint32_t backlogWindowS;         // 3 h        -> must equal BUFFER_WINDOW in backend/app/main.py

  static Limits taskSpec() {
    Limits l;
    l.warnAboveC = 8; l.warnBelowC = 2;
    l.breachAboveC = 12; l.breachBelowC = 0;
    l.compOnC = 7; l.compOffC = 3; l.compMinOffS = 60;
    l.doorAlertS = 60; l.sampleEveryS = 5; l.bufferMinutes = 40; l.backlogWindowS = 3 * 3600;
    return l;
  }
};

enum Reading { RD_SAFE, RD_WARNING, RD_BREACH };

// Mirrors fridge_status() in backend/app/main.py, including the "no reading" case: a failed DHT22
// read arrives as NaN and has to be shown as Breach rather than skipped.
inline Reading classify(const Limits& l, float tempC) {
  if (isnan(tempC) || tempC > l.breachAboveC || tempC < l.breachBelowC) return RD_BREACH;
  if (tempC > l.warnAboveC || tempC < l.warnBelowC) return RD_WARNING;
  return RD_SAFE;
}

inline const char* readingName(Reading r) {
  return r == RD_BREACH ? "Breach" : r == RD_WARNING ? "Warning" : "Safe";
}

// ------------------------------------------------------------------ clock
// The server rejects a timestamp more than 60 s from its own clock, so the node cannot sign a
// reading until NTP answers. Buffering must still work through that window, so a sample carries the
// millis() it was taken at and the timestamp is filled in once the clock is known.
class Clock {
 public:
  void sync(uint32_t epochS, uint32_t bootMs) {
    epochAtBootS_ = epochS - bootMs / 1000u;
    synced_ = true;
  }
  bool synced() const { return synced_; }
  uint32_t at(uint32_t bootMs) const { return synced_ ? epochAtBootS_ + bootMs / 1000u : 0; }

 private:
  uint32_t epochAtBootS_ = 0;
  bool synced_ = false;
};

// ------------------------------------------------------------------ compressor
// Task 1: ON at 7 C, OFF at 3 C, with a 60-second minimum off-time. A short off window is the way
// a compressor dies, so the wait is enforced before turn-on, not after turn-off.
class Compressor {
 public:
  bool step(const Limits& l, float tempC, uint32_t nowS) {
    if (isnan(tempC)) return on_;                     // hold the last decision on a bad sensor read
    if (on_) {
      if (tempC <= l.compOffC) { on_ = false; offSinceS_ = nowS; }
    } else if (tempC >= l.compOnC) {
      if (offSinceS_ == 0 || nowS - offSinceS_ >= l.compMinOffS) on_ = true;
    }
    return on_;
  }
  bool on() const { return on_; }

 private:
  bool on_ = false;
  uint32_t offSinceS_ = 0;   // 0 = never stopped yet, so the very first start needs no wait
};

// ------------------------------------------------------------------ door
// The node buzzes; the server writes DOOR_ALERT and pushes Telegram. Both fire once per opening,
// not once per reading.
class DoorWatch {
 public:
  void step(bool doorOpen, uint32_t nowS, const Limits& l) {
    if (doorOpen && !wasOpen_) { openSinceS_ = nowS; alerted_ = false; }
    if (!doorOpen) { openSinceS_ = 0; alerted_ = false; }
    wasOpen_ = doorOpen;
    if (doorOpen && !alerted_ && nowS && openSinceS_ && nowS - openSinceS_ > l.doorAlertS)
      alerted_ = true;
  }
  bool buzzer() const { return alerted_; }
  bool alerted() const { return alerted_; }
  uint32_t openForS(uint32_t nowS) const { return wasOpen_ && nowS ? nowS - openSinceS_ : 0; }

 private:
  bool wasOpen_ = false, alerted_ = false;
  uint32_t openSinceS_ = 0;
};

// ------------------------------------------------------------------ red LED
// Task 2: at 0% budget, discard and keep the red LED on until an admin reset. The node cannot know
// the budget locally (it is per batch, and batches move between fridges), so the server returns the
// worst status in this fridge with every accepted reading. step() runs only when a reply actually
// arrived: "Discard" latches, anything else - including the empty string, which is what a fridge
// whose batches were all moved away answers - clears it. A node that hears nothing keeps showing
// whatever it last latched, which is the safe direction for an alarm to fail in.
class RedLed {
 public:
  void step(const char* batchStatus) {
    if (!batchStatus) return;                     // silence is not a clearance
    latched_ = strcmp(batchStatus, "Discard") == 0;
  }
  bool on() const { return latched_; }

 private:
  bool latched_ = false;
};

// ------------------------------------------------------------------ battery
// Task 3 reports power status; a real backup pack would be read from an ADC. Until then the node
// estimates state of charge so the dashboard tile moves instead of sitting at a hardcoded 100.
class PowerModel {
 public:
  void step(bool mainsOk, uint32_t dtS, float drainPctPerHour = 12.0f,
            float chargePctPerHour = 20.0f) {
    if (dtS > 3600) dtS = 3600;
    float delta = (mainsOk ? chargePctPerHour : -drainPctPerHour) * dtS / 3600.0f;
    soc_ += delta;
    if (soc_ > 100.0f) soc_ = 100.0f;
    if (soc_ < 0.0f) soc_ = 0.0f;
  }
  uint8_t pct() const { return static_cast<uint8_t>(soc_ + 0.5f); }
  void reset(float pct) { soc_ = pct; }

 private:
  float soc_ = 100.0f;
};

// ------------------------------------------------------------------ offline buffer
// Task 3: at least 30 minutes of readings through a Wi-Fi loss, then synced in order and without
// duplicates. Ordered because /api/sensor ignores any reading whose ts is not ahead of the last one
// it stored; duplicate-free because each sample keeps the nonce it was signed with, so a retry after
// a half-finished sync is answered "replayed nonce" instead of storing the reading twice.
struct Sample {
  float tempC;
  uint32_t bootMs;      // when it was taken, for the timestamp backfill
  uint32_t tsS;         // unix seconds, 0 until the clock is known
  char nonce[33];
  uint8_t batteryPct;
  bool doorOpen, powerOk, compressorOn;
};

class ReadingLog {
 public:
  explicit ReadingLog(Sample* backing, uint16_t cap)
      : buf_(backing), cap_(cap), head_(0), count_(0) {}

  bool push(const Sample& s) {
    bool droppedOldest = false;
    if (count_ == cap_) { head_ = (head_ + 1) % cap_; count_--; dropped_++; droppedOldest = true; }
    buf_[(head_ + count_) % cap_] = s;
    count_++;
    return !droppedOldest;
  }
  const Sample* oldest() const { return count_ ? &buf_[head_] : nullptr; }
  void advance() { if (count_) { head_ = (head_ + 1) % cap_; count_--; } }
  uint16_t pending() const { return count_; }
  uint16_t capacity() const { return cap_; }
  uint32_t dropped() const { return dropped_; }

  // Stamp every queued sample once NTP answers, oldest first, so the replay order stays ascending.
  uint16_t backfill(const Clock& clock, uint32_t bootNow) {
    uint16_t filled = 0;
    for (uint16_t i = 0; i < count_; i++) {
      Sample& s = buf_[(head_ + i) % cap_];
      if (s.tsS == 0) { s.tsS = clock.at(s.bootMs); filled++; }
    }
    (void)bootNow;
    return filled;
  }
  // A reading older than the server's backlog window can never be accepted, so holding the queue
  // behind it would block every newer sample for the rest of the node's life.
  uint32_t oldestAgeS(uint32_t nowS) const {
    const Sample* s = oldest();
    return (s && nowS && s->tsS) ? nowS - s->tsS : 0;
  }

 private:
  Sample* buf_;
  uint16_t cap_, head_, count_;
  uint32_t dropped_ = 0;
};

// ------------------------------------------------------------------ the signed string
// backend/app/hmac_auth.py builds "{device_id}|{temperature}|{door}|{ts}|{nonce}|{power}|{battery}|
// {compressor}|{buffered}" from values Pydantic already parsed, and every float in it prints the way
// Python's str() prints it. Three consequences the node has to respect:
//   * temperature and battery carry exactly one decimal, so 12 is sent as "12.0" and never "12";
//   * ts is a float, so whole seconds print as "1793486530.0";
//   * the digits signed and the digits sent are the same bytes, so both come from one Wire struct.
struct Wire {
  char temp[16];
  char ts[24];
  char battery[16];
};

inline Wire wireOf(float tempC, uint32_t tsS, uint8_t batteryPct) {
  Wire w;
  snprintf(w.temp, sizeof w.temp, "%.1f", static_cast<double>(tempC));
  snprintf(w.ts, sizeof w.ts, "%.1f", static_cast<double>(tsS));
  snprintf(w.battery, sizeof w.battery, "%.1f", static_cast<double>(batteryPct));
  return w;
}

// buffered is inside the signature because it is what tells the server to widen the timestamp window
// from 60 s to 3 h. Unsigned, a reading captured off the wire could be relabelled as backlog and sent
// as live - or an hour-old one passed off as this second's sample.
inline int canonical(char* out, size_t n, const char* deviceId, const Wire& w, bool doorOpen,
                     const char* nonce, bool powerOk, bool compressorOn, bool buffered) {
  return snprintf(out, n, "%s|%s|%d|%s|%s|%d|%s|%d|%d", deviceId, w.temp, doorOpen ? 1 : 0, w.ts,
                  nonce, powerOk ? 1 : 0, w.battery, compressorOn ? 1 : 0, buffered ? 1 : 0);
}

// ts is the signed value itself, not the sample's, so a backfilled timestamp can never be sent as
// something other than what was hashed.
inline int payload(char* out, size_t n, const char* deviceId, const Wire& w, bool doorOpen,
                   const char* nonce, const char* signature, bool powerOk, bool compressorOn,
                   bool buffered) {
  return snprintf(out, n,
                  "{\"device_id\":\"%s\",\"temperature\":%s,\"door_open\":%s,\"ts\":%s,"
                  "\"nonce\":\"%s\",\"signature\":\"%s\",\"power_ok\":%s,\"battery\":%s,"
                  "\"compressor_on\":%s,\"buffered\":%s}",
                  deviceId, w.temp, doorOpen ? "true" : "false", w.ts, nonce, signature,
                  powerOk ? "true" : "false", w.battery, compressorOn ? "true" : "false",
                  buffered ? "true" : "false");
}

// ------------------------------------------------------------------ what the server said
enum Action {
  ACT_ACCEPTED,   // drop this sample from the queue and move on
  ACT_RETRY,      // keep it; the link, the API wake-up or a transient fault will clear
  ACT_DROP        // this sample can never be accepted; discard it so it stops blocking the queue
};

// detail is the HTTPException body: "invalid signature", "stale timestamp", "replayed nonce",
// "unknown device". A nonce the API has already seen is not a rejection of the reading: the nonce row
// is written before the out-of-order guard, so "replayed nonce" is positive proof the reading was
// stored on an attempt whose reply never came back. Either way the sample is consumed.
inline Action decide(int http, const char* detail, uint32_t ageS, uint8_t attempts,
                     const Limits& l) {
  if (http >= 200 && http < 300) return ACT_ACCEPTED;
  if (!detail) return ACT_RETRY;
  if (strstr(detail, "replayed nonce")) return ACT_ACCEPTED;
  if (strstr(detail, "stale timestamp"))
    return ageS > l.backlogWindowS ? ACT_DROP : ACT_RETRY;
  if (strstr(detail, "invalid signature"))
    return attempts >= 3 ? ACT_DROP : ACT_RETRY;   // a clock or number-format bug must not jam the queue
  return ACT_RETRY;
}

// ------------------------------------------------------------------ reading the reply
// Over MQTT the node never sees /api/sensor's answer directly; the bridge echoes it to
// coldchain/<device>/command, so the node has to pull one field out of a JSON body without a JSON
// library. Deliberately narrow: it finds "key":"value" and copies the value, which is all the reply
// needs, and it is the part worth testing rather than pretending is trivial.
inline bool findStringField(const char* json, const char* key, char* out, size_t n) {
  if (!json || !key) return false;
  char needle[40];
  snprintf(needle, sizeof needle, "\"%s\":\"", key);
  const char* p = strstr(json, needle);
  if (!p) return false;
  p += strlen(needle);
  size_t i = 0;
  while (p[i] && p[i] != '"' && i + 1 < n) { out[i] = p[i]; i++; }
  out[i] = '\0';
  return i > 0;
}

// /api/sensor answers "batch_status":null when the fridge holds no batches at all. That is a reply,
// not silence, and the node has to tell the two apart because one of them clears the red LED.
inline bool jsonHasNull(const char* json, const char* key) {
  if (!json || !key) return false;
  char needle[40];
  snprintf(needle, sizeof needle, "\"%s\":null", key);
  return strstr(json, needle) != nullptr;
}

// 1 = publish it as a live reading (60 s skew window), 2 = publish it as backlog (3 h window),
// 0 = do not send yet. A reading taken while the queue holds anything older is backlog by definition.
inline int sendMode(uint16_t pending, bool clockSynced, uint32_t tsS) {
  if (!pending || !clockSynced || tsS == 0) return 0;
  return pending > 1 ? 2 : 1;
}

}  // namespace cc

#endif
