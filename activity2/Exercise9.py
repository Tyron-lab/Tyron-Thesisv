# Exercise 9: Voice Activated System (INMP441 I2S / VoiceHAT) + LCD (RPLCD via TCA9548A) + Buzzer
#
# Input: Voice detected (speaking)
# What happens: System detects speaking from mic intensity (sustained)
# Output:
#   LCD shows "VOICE DETECTED"
#   Buzzer beeps

import time
import signal
import sys

import board
import digitalio

import numpy as np
import sounddevice as sd

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# ==========================
# LCD via TCA9548A (same as Exercise 1)
# ==========================
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27

LCD_COLS = 16
LCD_ROWS = 2

def mux_select(channel: int):
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)

def lcd_init():
    mux_select(LCD_CH)
    lcd = CharLCD(
        "PCF8574",
        address=LCD_ADDR,
        port=I2C_BUS,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        charmap="A00"
    )
    lcd.clear()
    return lcd

def lcd_write(lcd, line1: str, line2: str = ""):
    mux_select(LCD_CH)
    lcd.clear()
    lcd.write_string((line1 or "")[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string((line2 or "")[:LCD_COLS])

# ==========================
# Stop handling (same pattern)
# ==========================
_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# ==========================
# Buzzer (active buzzer recommended)
# ==========================
BUZZER_PIN = board.D21  # CHANGE if your buzzer is on a different pin
buzzer = digitalio.DigitalInOut(BUZZER_PIN)
buzzer.direction = digitalio.Direction.OUTPUT
buzzer.value = False

def beep(times=2, on_s=0.10, off_s=0.10):
    for _ in range(times):
        buzzer.value = True
        time.sleep(on_s)
        buzzer.value = False
        time.sleep(off_s)

# ==========================
# Audio settings (like Exercise 6)
# ==========================
SAMPLE_RATE = 48000
BLOCK_MS = 20
CHANNELS = 1
BLOCK_SIZE = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))

INPUT_DEVICE = 1  # same device index you used successfully

_latest_peak = 0.0

def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

# ==========================
# Voice detection tuning
# ==========================
# We'll treat "voice" as intensity sustained above threshold for VOICE_MIN_MS.
# Auto threshold adapts to room noise.

USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 5.0
AUTO_FLOOR = 0.08

FIXED_THRESHOLD = 0.14   # used if USE_AUTO_THRESHOLD=False

VOICE_MIN_MS = 200       # must be speaking for at least 200ms
VOICE_MIN_S = VOICE_MIN_MS / 1000.0

TRIGGER_COOLDOWN_MS = 1200
TRIGGER_COOLDOWN_S = TRIGGER_COOLDOWN_MS / 1000.0

noise_peaks = []
NOISE_WINDOW = 180

def get_threshold():
    if not USE_AUTO_THRESHOLD:
        return FIXED_THRESHOLD
    if len(noise_peaks) < 12:
        return max(FIXED_THRESHOLD, AUTO_FLOOR)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, FIXED_THRESHOLD)

def safe_exit(lcd=None, code=0):
    try:
        buzzer.value = False
        buzzer.deinit()
    except Exception:
        pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.4)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 9 exited cleanly.")
    sys.exit(code)

# ==========================
# Main
# ==========================
print("Exercise 9: Voice Activated System running (INMP441 / VoiceHAT)")
print(f"Using INPUT_DEVICE={INPUT_DEVICE}, SAMPLE_RATE={SAMPLE_RATE}")
print("LCD: RPLCD via TCA9548A | Output: LCD 'VOICE DETECTED' + buzzer beeps")
print("Stop: Stop button or Ctrl+C")

# Init LCD (keep running if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Voice System", "Listening...")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

voice_started_t = None
last_trigger_t = 0.0
last_print = 0.0
last_state = None  # None/'idle'/'voice'

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=BLOCK_SIZE,
        device=INPUT_DEVICE,
        dtype="float32",
        callback=audio_callback,
    ):
        while not _should_exit:
            now_t = time.time()

            # learn background noise (quiet-ish frames)
            if _latest_peak < 0.20:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            thr = get_threshold()
            above = (_latest_peak >= thr)

            # voice timing gate
            if above:
                if voice_started_t is None:
                    voice_started_t = now_t
            else:
                voice_started_t = None

            voice_detected = False
            if voice_started_t is not None and (now_t - voice_started_t) >= VOICE_MIN_S:
                voice_detected = True

            # update LCD state (avoid writing every loop)
            if voice_detected and last_state != "voice":
                last_state = "voice"
                if lcd:
                    lcd_write(lcd, "VOICE DETECTED", "Speaking...")
                else:
                    print("VOICE DETECTED")

            if (not voice_detected) and last_state != "idle":
                last_state = "idle"
                if lcd:
                    lcd_write(lcd, "Listening...", "Say something")
                else:
                    pass

            # trigger buzzer on voice detect with cooldown
            cooldown_ok = (now_t - last_trigger_t) >= TRIGGER_COOLDOWN_S
            if voice_detected and cooldown_ok:
                last_trigger_t = now_t
                beep(times=2, on_s=0.10, off_s=0.10)

            # debug print once/sec
            if now_t - last_print > 1.0:
                print(f"peak={_latest_peak:.3f} thr={thr:.3f} voice={'YES' if voice_detected else 'no'}")
                last_print = now_t

            time.sleep(0.01)

    safe_exit(lcd, 0)

except Exception as e:
    print("\n❌ Audio stream failed to start:")
    print("   ", repr(e))
    print("\nAvailable devices:")
    try:
        print(sd.query_devices())
    except Exception as e2:
        print("   Could not query devices:", repr(e2))

    if lcd:
        try:
            lcd_write(lcd, "AUDIO ERROR", str(e)[:16])
        except Exception:
            pass

    safe_exit(lcd, 1)