#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>

constexpr int occupiedBelowMm = 400;
constexpr int clearAboveMm = 550;
constexpr unsigned long confirmMs = 500;
constexpr unsigned long invalidTimeoutMs = 1000;
constexpr int depthChangeMm = 80;
constexpr uint8_t depthSamplesToConfirm = 3;
constexpr unsigned long ledPulseMs = 600;

enum class StallState { Unknown, Clear, Occupied };
ModulinoDistance distance;
bool distanceReady = false;
StallState stall = StallState::Unknown;
StallState pending = StallState::Unknown;
unsigned long pendingSince = 0;
unsigned long lastValidAt = 0;
float depthReferenceMm = 0;
uint8_t depthChangeSamples = 0;
unsigned long depthPulseAt = 0;
unsigned long motionPulseAt = 0;
bool depthPulse = false;
bool motionPulse = false;

void signalCameraMotion() {
  motionPulseAt = millis();
  motionPulse = true;
}

void checkDepthChange(float mm, unsigned long now) {
  if (depthReferenceMm == 0) {
    depthReferenceMm = mm;
    return;
  }
  const float change = mm - depthReferenceMm;
  if (change > -depthChangeMm && change < depthChangeMm) {
    depthChangeSamples = 0;
    return;
  }
  if (++depthChangeSamples >= depthSamplesToConfirm) {
    depthReferenceMm = mm;
    depthChangeSamples = 0;
    depthPulseAt = now;
    depthPulse = true;
  }
}

String stallState() {
  switch (stall) {
    case StallState::Clear: return "clear";
    case StallState::Occupied: return "occupied";
    default: return "unknown";
  }
}

void setup() {
  pinMode(LED3_G, OUTPUT);
  pinMode(LED3_B, OUTPUT);
  digitalWrite(LED3_G, HIGH);
  digitalWrite(LED3_B, HIGH);
  Modulino.begin(Wire1);
  distanceReady = distance.begin();
  Bridge.begin();
  Bridge.provide_safe("stall_state", stallState);
  Bridge.provide_safe("signal_camera_motion", signalCameraMotion);
}

void loop() {
  const unsigned long now = millis();
  const float mm = distanceReady && distance.available() ? distance.get() : -1;

  if (!(mm > 0)) {
    pending = StallState::Unknown;
    depthChangeSamples = 0;
    if (now - lastValidAt >= invalidTimeoutMs) {
      stall = StallState::Unknown;
      depthReferenceMm = 0;
    }
  } else {
    lastValidAt = now;
    checkDepthChange(mm, now);
    StallState observed = StallState::Unknown;
    if (mm < occupiedBelowMm) {
      observed = StallState::Occupied;
    } else if (mm > clearAboveMm) {
      observed = StallState::Clear;
    }

    if (observed != pending) {
      pending = observed;
      pendingSince = now;
    }
    if (pending != StallState::Unknown && now - pendingSince >= confirmMs) {
      stall = pending;
    }
  }
  depthPulse = depthPulse && now - depthPulseAt < ledPulseMs;
  motionPulse = motionPulse && now - motionPulseAt < ledPulseMs;
  digitalWrite(LED3_G, depthPulse ? LOW : HIGH);
  digitalWrite(LED3_B, motionPulse ? LOW : HIGH);
  delay(50);
}
