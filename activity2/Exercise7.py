# Exercise 7 (Activity 1): Sound Detection Indicator using INMP441 I2S (Google VoiceHAT SoundCard)
# Measures sound level and shows 3 levels using LEDs:
#   RED    (board.D5)  = LOUD (high noise)
#   ORANGE (board.D13) = MID  (medium noise)
#   GREEN  (board.D6)  = QUIET (low/no noise)
#
# Uses supported sample rate (48k) + explicit INPUT_DEVICE like Exercise 6.

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# ---------------- LED PINS ----------------
LED_RED_PIN    = board.D5     # RED  = HIGH noise
LED_GREEN_PIN  = board.D6     # GREEN= NO noise / quiet
LED_ORANGE_PIN = board.D13    # ORANGE = MID noise

red = digitalio.DigitalInOut(LED_RED_PIN)
green = digitalio.DigitalInOut(LED_GREEN_PIN)
orange = digitalio.DigitalInOut(LED_ORANGE_PIN)

red.direction = digitalio.Direction.OUTPUT
green.direction = digitalio.Direction.OUTPUT
orange.direction = digitalio.Direction.OUTPUT

red.value = False
green.value = True   # start as quiet
orange.value = False

def set_level(level: str):
    """
    level: 'quiet' | 'mid' | 'loud'
    """
    if level == "quiet":
        red.value = False
        orange.value = False
        green.value = True
    elif level == "mid":
        red.value = False
        orange.value = True
        green.value = False
    else:  # loud
        red.value = True
        orange.value = False
        green.value = False

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

# ✅ same as Exercise 6
INPUT_DEVICE = 1

# ---------------- Detection tuning ----------------
# We use PEAK amplitude as sound level indicator.

USE_AUTO_THRESHOLD = True

# Auto threshold for "MID". LOUD will be a multiplier above MID.
AUTO_MULTIPLIER = 4.5      # sensitivity baseline (mid threshold)
AUTO_FLOOR = 0.06          # minimum threshold

FIXED_MID_THRESHOLD = 0.12 # used if USE_AUTO_THRESHOLD = False
LOUD_MULTIPLIER = 1.8      # loud_threshold = mid_threshold * LOUD_MULTIPLIER

# Keep indicator stable (avoid flicker)
HOLD_MS = 140
HOLD_S = HOLD_MS / 1000.0

_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

noise_peaks = []
NOISE_WINDOW = 140

def get_mid_threshold():
    if not USE_AUTO_THRESHOLD:
        return FIXED_MID_THRESHOLD
    if len(noise_peaks) < 12:
        return max(FIXED_MID_THRESHOLD, AUTO_FLOOR)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, FIXED_MID_THRESHOLD)

def safe_exit(code=0):
    try:
        # turn all off on exit
        red.value = False
        orange.value = False
        green.value = False
        red.deinit()
        orange.deinit()
        green.deinit()
    except Exception:
        pass
    print("Exercise 7 exited cleanly.")
    sys.exit(code)

print("Exercise 7: INMP441 Sound Detection Indicator (3 levels) running")
print("RED=board.D5 (LOUD), ORANGE=board.D13 (MID), GREEN=board.D6 (QUIET)")
print("Using INPUT_DEVICE=1, SAMPLE_RATE=48000")
print("Stop: Stop button or Ctrl+C")
print("Tuning tips:")
print(" - Too sensitive? raise AUTO_MULTIPLIER or FIXED_MID_THRESHOLD")
print(" - Not detecting? lower AUTO_MULTIPLIER or FIXED_MID_THRESHOLD")
print(" - LOUD too easy/hard? adjust LOUD_MULTIPLIER")

last_state_change_t = 0.0
current_level = "quiet"
set_level(current_level)

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

            # Build noise model using quieter blocks
            if _latest_peak < 0.20:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            mid_thr = get_mid_threshold()
            loud_thr = mid_thr * LOUD_MULTIPLIER

            # Decide target level
            if _latest_peak >= loud_thr:
                target = "loud"
            elif _latest_peak >= mid_thr:
                target = "mid"
            else:
                target = "quiet"

            # Hold to prevent flicker: only switch if enough time passed
            if target != current_level:
                if (now_t - last_state_change_t) >= HOLD_S:
                    current_level = target
                    set_level(current_level)
                    last_state_change_t = now_t

            if now_t - last_print > 1.0:
                print(
                    f"peak={_latest_peak:.3f} mid_thr={mid_thr:.3f} loud_thr={loud_thr:.3f} "
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