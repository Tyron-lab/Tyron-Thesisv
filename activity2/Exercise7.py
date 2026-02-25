# Exercise 7 (Activity 1): Sound Detection Indicator using INMP441 I2S (Google VoiceHAT SoundCard)
# Measures sound level and turns LED ON when loud, OFF when quiet.
#
# Uses supported sample rate (48k) + explicit INPUT_DEVICE like Exercise 6.

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# ---------------- LED ----------------
LED_PIN = board.D13
led = digitalio.DigitalInOut(LED_PIN)
led.direction = digitalio.Direction.OUTPUT
led.value = False

def set_led(on: bool):
    led.value = bool(on)

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

# ✅ Use the same input device index that works in Exercise 6
INPUT_DEVICE = 1

# ---------------- Loud/quiet detection tuning ----------------
# We'll use PEAK amplitude as a simple "sound level" signal (works well for indicators).
# You can switch to RMS later if you want, but peak is responsive and simple.

USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 4.5     # raise if too sensitive, lower if not detecting
AUTO_FLOOR = 0.06         # minimum threshold so it doesn't turn ON in silence

FIXED_THRESHOLD = 0.12    # used if USE_AUTO_THRESHOLD = False

HOLD_ON_MS = 120          # keep LED ON briefly after loud sound
HOLD_ON_S = HOLD_ON_MS / 1000.0

_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

noise_peaks = []
NOISE_WINDOW = 120

def get_threshold():
    if not USE_AUTO_THRESHOLD:
        return FIXED_THRESHOLD
    if len(noise_peaks) < 12:
        return max(FIXED_THRESHOLD, AUTO_FLOOR)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, FIXED_THRESHOLD)

def safe_exit(code=0):
    try:
        set_led(False)
        led.deinit()
    except Exception:
        pass
    print("Exercise 7 exited cleanly.")
    sys.exit(code)

print("Exercise 7: INMP441 Sound Detection Indicator running (Google VoiceHAT card)")
print("LED: board.D13 | Using INPUT_DEVICE=1, SAMPLE_RATE=48000")
print("Stop: Stop button or Ctrl+C")
print("Tip: If always ON, raise AUTO_MULTIPLIER / FIXED_THRESHOLD. If never ON, lower them.")

last_loud_t = 0.0

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
        led_on = False

        while not _should_exit:
            now_t = time.time()

            # Build noise model using quieter blocks
            if _latest_peak < 0.20:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            thr = get_threshold()

            loud = (_latest_peak >= thr)

            if loud:
                last_loud_t = now_t

            # Hold behavior so LED doesn't flicker too fast
            should_on = (now_t - last_loud_t) <= HOLD_ON_S

            if should_on != led_on:
                led_on = should_on
                set_led(led_on)

            if now_t - last_print > 1.0:
                print(f"peak={_latest_peak:.3f} thr={thr:.3f} LED={'ON' if led_on else 'OFF'}")
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