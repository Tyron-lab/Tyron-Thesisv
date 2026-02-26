# Exercise 6 (Activity 2): Clap Switch using INMP441 I2S (Google VoiceHAT SoundCard)
# 1 clap  -> GREEN LED ON
# 2 claps -> GREEN LED OFF

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# ---------------- LED ----------------
LED_GREEN_PIN = board.D6
green = digitalio.DigitalInOut(LED_GREEN_PIN)
green.direction = digitalio.Direction.OUTPUT
green.value = False

def set_green(on: bool):
    green.value = bool(on)

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
INPUT_DEVICE = 1

# ---------------- Clap detection tuning (MORE SENSITIVE) ----------------
CLAP_PEAK_THRESHOLD = 0.12   # was 0.25

MIN_CLAP_GAP = 0.12          # slightly smaller so fast claps still register
DOUBLE_CLAP_WINDOW = 0.80    # allow more time for 2nd clap

USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 3.5        # was 6.0
AUTO_FLOOR = 0.06            # was 0.12

_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

# ---------------- Clap logic ----------------
led_on = False
last_clap_t = 0.0
pending_single = False
pending_start_t = 0.0

noise_peaks = []
NOISE_WINDOW = 150           # was 80

def get_threshold():
    if not USE_AUTO_THRESHOLD:
        return CLAP_PEAK_THRESHOLD
    if len(noise_peaks) < 12:
        return max(CLAP_PEAK_THRESHOLD, AUTO_FLOOR)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, CLAP_PEAK_THRESHOLD)

def register_clap(now_t: float):
    global pending_single, pending_start_t, led_on
    if pending_single and (now_t - pending_start_t) <= DOUBLE_CLAP_WINDOW:
        led_on = False
        set_green(False)
        pending_single = False
        print("👏👏 Double clap -> OFF")
        return
    pending_single = True
    pending_start_t = now_t
    print("👏 Clap detected (waiting...)")

def finalize_single_if_due(now_t: float):
    global pending_single, led_on
    if pending_single and (now_t - pending_start_t) > DOUBLE_CLAP_WINDOW:
        led_on = True
        set_green(True)
        pending_single = False
        print("✅ Single clap -> ON")

def safe_exit(code=0):
    try:
        set_green(False)
        green.deinit()
    except Exception:
        pass
    print("Exercise 6 exited cleanly.")
    sys.exit(code)

print("Exercise 6: INMP441 Clap Switch running (Google VoiceHAT card)")
print("Using INPUT_DEVICE=1, SAMPLE_RATE=48000")
print("Stop: Stop button or Ctrl+C")
print("Tip: If it triggers too easily, raise AUTO_MULTIPLIER back up slowly (4.0, 4.5, 5.0).")

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

            # build noise model from "not too loud" blocks
            if _latest_peak < 0.35:   # was 0.20
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            thr = get_threshold()

            if now_t - last_print > 1.0:
                print(f"peak={_latest_peak:.3f} thr={thr:.3f} LED={'ON' if led_on else 'OFF'}")
                last_print = now_t

            if _latest_peak >= thr:
                if (now_t - last_clap_t) >= MIN_CLAP_GAP:
                    last_clap_t = now_t
                    register_clap(now_t)
                _latest_peak = 0.0

            finalize_single_if_due(now_t)
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