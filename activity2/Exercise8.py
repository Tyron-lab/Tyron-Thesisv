# Exercise 8 (Activity 1): Noise Level Classifier using INMP441 I2S (Google VoiceHAT SoundCard)
# Input: sound intensity from digital mic (I2S -> ALSA)
# What happens: system checks noise level
# Output:
#   Green LED  = quiet
#   Orange LED = moderate
#   Red LED    = too noisy
#
# Uses SAMPLE_RATE=48000 + explicit INPUT_DEVICE (same style as Exercise 6)

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# ---------------- LED PINS ----------------
LED_RED_PIN    = board.D5     # Red = too noisy
LED_GREEN_PIN  = board.D6     # Green = quiet
LED_ORANGE_PIN = board.D13    # Orange = moderate

red = digitalio.DigitalInOut(LED_RED_PIN)
green = digitalio.DigitalInOut(LED_GREEN_PIN)
orange = digitalio.DigitalInOut(LED_ORANGE_PIN)

red.direction = digitalio.Direction.OUTPUT
green.direction = digitalio.Direction.OUTPUT
orange.direction = digitalio.Direction.OUTPUT

def set_level(level: str):
    """level: 'quiet' | 'moderate' | 'noisy'"""
    if level == "quiet":
        green.value = True
        orange.value = False
        red.value = False
    elif level == "moderate":
        green.value = False
        orange.value = True
        red.value = False
    else:  # noisy
        green.value = False
        orange.value = False
        red.value = True

# Start in quiet
set_level("quiet")

# ---------------- Stop handling ----------------
_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# ---------------- Audio settings ----------------
SAMPLE_RATE = 48000
BLOCK_MS = 20
CHANNELS = 1
BLOCK_SIZE = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))

# ✅ same device index you used in Exercise 6
INPUT_DEVICE = 1

# ---------------- Noise level tuning ----------------
# Using PEAK amplitude as "intensity" (fast, works well on indicators).
# Auto thresholds adapt to room noise.

USE_AUTO_THRESHOLD = True

AUTO_MULTIPLIER_QUIET_TO_MOD = 4.5   # baseline multiplier to detect "moderate"
AUTO_FLOOR_MOD = 0.06                # minimum moderate threshold

FIXED_MOD_THRESHOLD = 0.12           # used if USE_AUTO_THRESHOLD = False
NOISY_MULTIPLIER = 1.8               # noisy_threshold = mod_threshold * NOISY_MULTIPLIER

# Stability / anti-flicker
HOLD_MS = 160
HOLD_S = HOLD_MS / 1000.0

_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

# Learn background noise from quiet-ish frames
noise_peaks = []
NOISE_WINDOW = 160

def get_mod_threshold():
    if not USE_AUTO_THRESHOLD:
        return FIXED_MOD_THRESHOLD
    if len(noise_peaks) < 12:
        return max(FIXED_MOD_THRESHOLD, AUTO_FLOOR_MOD)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR_MOD, base * AUTO_MULTIPLIER_QUIET_TO_MOD)
    return max(thr, FIXED_MOD_THRESHOLD)

def safe_exit(code=0):
    try:
        green.value = False
        orange.value = False
        red.value = False
        green.deinit()
        orange.deinit()
        red.deinit()
    except Exception:
        pass
    print("Exercise 8 exited cleanly.")
    sys.exit(code)

print("Exercise 8: Noise Level Classifier running (INMP441 / VoiceHAT)")
print("GREEN=quiet (D6) | ORANGE=moderate (D13) | RED=too noisy (D5)")
print("Using INPUT_DEVICE=1, SAMPLE_RATE=48000")
print("Stop: Stop button or Ctrl+C")

current_level = "quiet"
last_switch_t = 0.0

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=BLOCK_SIZE,
        device=INPUT_DEVICE,
        dtype="float32",
        callback=audio_callback,
    ):
        last_print = 0.0

        while not _should_exit:
            now_t = time.time()

            # Update background noise model using quiet-ish frames
            if _latest_peak < 0.20:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            mod_thr = get_mod_threshold()
            noisy_thr = mod_thr * NOISY_MULTIPLIER

            # Classify
            if _latest_peak >= noisy_thr:
                target = "noisy"
            elif _latest_peak >= mod_thr:
                target = "moderate"
            else:
                target = "quiet"

            # Anti-flicker hold
            if target != current_level and (now_t - last_switch_t) >= HOLD_S:
                current_level = target
                set_level(current_level)
                last_switch_t = now_t

            if now_t - last_print > 1.0:
                print(
                    f"peak={_latest_peak:.3f} mod_thr={mod_thr:.3f} noisy_thr={noisy_thr:.3f} "
                    f"LEVEL={current_level.upper()}"
                )
                last_print = now_t

            time.sleep(0.01)

    safe_exit(0)

except Exception as e:
    print("\n❌ Audio stream failed to start:")
    print("   ", repr(e))
    print("\nAvailable devices:")
    try:
        print(sd.query_devices())
    except Exception as e2:
        print("   Could not query devices:", repr(e2))
    safe_exit(1)