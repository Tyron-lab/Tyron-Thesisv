# Exercise 6 (Activity 2): Clap Switch using INMP441 I2S MEMS Microphone
# Wiring (Raspberry Pi I2S fixed pins):
#   INMP441 SCK/BCLK -> GPIO18 (Pin 12)
#   INMP441 WS/LRCLK -> GPIO19 (Pin 35)
#   INMP441 SD/DOUT  -> GPIO20 (Pin 38)
#   INMP441 VDD      -> 3.3V  (Pin 1 or 17)
#   INMP441 GND      -> GND   (Pin 6/9/14/20/25/30/34/39)
#   INMP441 L/R      -> GND (Left) or 3.3V (Right)
#
# Output:
#   1 clap  -> GREEN LED ON
#   2 claps -> GREEN LED OFF
#
# Stop-safe: supports SIGTERM (Stop button) + Ctrl+C

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

# =========================
# LED PIN (TrainerKit)
# =========================
LED_GREEN_PIN = board.D6

# =========================
# AUDIO SETTINGS
# =========================
SAMPLE_RATE = 16000        # Hz
BLOCK_MS = 30              # block duration
CHANNELS = 1               # read mono
BLOCK_SIZE = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))

# If the mic isn't the default input device, set INPUT_DEVICE:
# - None = default
# - int (device index) or str (name substring)
INPUT_DEVICE = None  # e.g. 2 or "I2S"

# =========================
# CLAP DETECTION TUNING
# =========================
CLAP_PEAK_THRESHOLD = 0.35    # raise if too sensitive, lower if not detecting
MIN_CLAP_GAP = 0.15           # seconds: debounce
DOUBLE_CLAP_WINDOW = 0.70     # seconds: second clap within this -> OFF

# Optional: adaptive threshold (starts learning background noise)
USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 6.0         # higher = less sensitive
AUTO_FLOOR = 0.20             # minimum threshold

# =========================
# STOP HANDLING
# =========================
_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# =========================
# GPIO LED SETUP
# =========================
green = digitalio.DigitalInOut(LED_GREEN_PIN)
green.direction = digitalio.Direction.OUTPUT
green.value = False

def set_green(on: bool):
    green.value = bool(on)

# =========================
# AUDIO FEATURE (peak)
# =========================
_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    # indata shape: (frames, channels)
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

# =========================
# CLAP STATE MACHINE
# =========================
led_on = False
last_clap_t = 0.0
pending_single = False
pending_start_t = 0.0

# For auto threshold
noise_peaks = []
NOISE_WINDOW = 60  # keep last N peaks

def get_threshold():
    if not USE_AUTO_THRESHOLD:
        return CLAP_PEAK_THRESHOLD
    if len(noise_peaks) < 10:
        return max(CLAP_PEAK_THRESHOLD, AUTO_FLOOR)

    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, CLAP_PEAK_THRESHOLD)

def register_clap(now_t: float):
    global pending_single, pending_start_t, led_on

    # Double clap detected -> OFF
    if pending_single and (now_t - pending_start_t) <= DOUBLE_CLAP_WINDOW:
        led_on = False
        set_green(False)
        pending_single = False
        print("👏👏 Double clap -> OFF")
        return

    # Start waiting for a possible double clap
    pending_single = True
    pending_start_t = now_t
    print("👏 Clap detected (waiting for 2nd clap...)")

def finalize_single_if_due(now_t: float):
    global pending_single, led_on
    if pending_single and (now_t - pending_start_t) > DOUBLE_CLAP_WINDOW:
        led_on = True
        set_green(True)
        pending_single = False
        print("✅ Single clap -> ON")

def safe_exit():
    try:
        set_green(False)
        green.deinit()
    except Exception:
        pass
    print("Exercise 6 exited cleanly.")
    sys.exit(0)

print("Exercise 6: INMP441 Clap Switch running...")
print("Wiring: BCLK=GPIO18(pin12), LRCLK=GPIO19(pin35), DATA=GPIO20(pin38)")
print("Stop: click Stop button or Ctrl+C")
print("Tip: If it triggers too easily, increase CLAP_PEAK_THRESHOLD or AUTO_MULTIPLIER.")

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

            # Maintain noise profile for auto threshold
            # Only add when not peaking hard (avoid learning claps)
            if _latest_peak < 0.25:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            thr = get_threshold()

            # Debug once per second
            if now_t - last_print > 1.0:
                print(f"peak={_latest_peak:.3f}  thr={thr:.3f}  LED={'ON' if led_on else 'OFF'}")
                last_print = now_t

            # Clap detection (peak spike)
            if _latest_peak >= thr:
                if (now_t - last_clap_t) >= MIN_CLAP_GAP:
                    last_clap_t = now_t
                    register_clap(now_t)

                # reset to avoid multiple counts for one clap burst
                _latest_peak = 0.0

            finalize_single_if_due(now_t)
            time.sleep(0.01)

finally:
    safe_exit()