# Exercise 7 (Activity 1): Sound Detection Indicator using INMP441 I2S (Google VoiceHAT SoundCard)
# Measures sound level and shows 3 levels using LEDs:
#   RED    (board.D5)  = LOUD (high noise)  -> solid RED
#   ORANGE (board.D13) = MID  (medium noise)-> running lights (traffic light cycle)
#   GREEN  (board.D6)  = QUIET (low/no noise)-> solid GREEN
#
# MID mode running pattern: GREEN -> ORANGE -> RED -> ORANGE -> repeat

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# ---------------- LED PINS ----------------
LED_RED_PIN    = board.D5     # RED  = HIGH noise
LED_GREEN_PIN  = board.D6     # GREEN= QUIET
LED_ORANGE_PIN = board.D13    # ORANGE = MID

red = digitalio.DigitalInOut(LED_RED_PIN)
green = digitalio.DigitalInOut(LED_GREEN_PIN)
orange = digitalio.DigitalInOut(LED_ORANGE_PIN)

red.direction = digitalio.Direction.OUTPUT
green.direction = digitalio.Direction.OUTPUT
orange.direction = digitalio.Direction.OUTPUT

def all_off():
    red.value = False
    orange.value = False
    green.value = False

def set_solid(level: str):
    """
    level: 'quiet' | 'loud'
    """
    if level == "quiet":
        red.value = False
        orange.value = False
        green.value = True
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
INPUT_DEVICE = 1  # same as Exercise 6

# ---------------- Detection tuning ----------------
USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 4.5
AUTO_FLOOR = 0.06

FIXED_MID_THRESHOLD = 0.12
LOUD_MULTIPLIER = 1.8

# Prevent level bouncing too fast
HOLD_MS = 200
HOLD_S = HOLD_MS / 1000.0

# Running lights speed (MID mode)
RUN_STEP_MS = 180
RUN_STEP_S = RUN_STEP_MS / 1000.0

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
        all_off()
        red.deinit()
        orange.deinit()
        green.deinit()
    except Exception:
        pass
    print("Exercise 7 exited cleanly.")
    sys.exit(code)

print("Exercise 7: Sound Detection Indicator (3 levels + MID running lights)")
print("RED=board.D5 (LOUD solid), ORANGE=board.D13 (MID running), GREEN=board.D6 (QUIET solid)")
print("Using INPUT_DEVICE=1, SAMPLE_RATE=48000")
print("Stop: Stop button or Ctrl+C")

# Start state
current_level = "quiet"
set_solid("quiet")
last_level_change_t = 0.0

# MID running pattern: G -> O -> R -> O -> repeat
run_pattern = ["G", "O", "R", "O"]
run_idx = 0
next_run_step_t = 0.0

def show_run_step(step: str):
    if step == "G":
        red.value = False
        orange.value = False
        green.value = True
    elif step == "O":
        red.value = False
        orange.value = True
        green.value = False
    else:  # "R"
        red.value = True
        orange.value = False
        green.value = False

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

            # Decide target level based on current peak
            if _latest_peak >= loud_thr:
                target = "loud"
            elif _latest_peak >= mid_thr:
                target = "mid"
            else:
                target = "quiet"

            # Switch levels with HOLD to avoid rapid bouncing
            if target != current_level and (now_t - last_level_change_t) >= HOLD_S:
                current_level = target
                last_level_change_t = now_t

                if current_level == "quiet":
                    set_solid("quiet")
                elif current_level == "loud":
                    set_solid("loud")
                else:
                    # entering MID: reset running pattern timer
                    run_idx = 0
                    next_run_step_t = 0.0

            # MID running lights loop
            if current_level == "mid":
                if now_t >= next_run_step_t:
                    show_run_step(run_pattern[run_idx])
                    run_idx = (run_idx + 1) % len(run_pattern)
                    next_run_step_t = now_t + RUN_STEP_S

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