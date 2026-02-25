# Exercise 9: Sound Alert System (INMP441) + Buzzer + RED/ORANGE LEDs (+ optional LCD)
# Input: Loud sound detected (e.g., shout or alarm)
# Output: Buzzer alarm + blink RED (D5) + ORANGE (D13)

import time
import signal
import sys

import board
import digitalio
import numpy as np
import sounddevice as sd

# ---- Optional LCD via TCA9548A (safe if missing) ----
USE_LCD = True
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
except Exception:
    USE_LCD = False

# ---------------- Stop handling ----------------
_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# ==========================
# Helper: make output pin (your style)
# ==========================
def make_out(pin, initial=False):
    d = digitalio.DigitalInOut(pin)
    d.direction = digitalio.Direction.OUTPUT
    d.value = bool(initial)
    return d

# ==========================
# LCD via TCA9548A (optional)
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
# Buzzer (Exercise 4 hardened logic)
# ==========================
BUZZER_PIN = board.D21     # change if your buzzer is on another pin
MUTE = False
BUZZER_ACTIVE_LOW = True   # True if buzzer ON when GPIO LOW

buzzer = make_out(BUZZER_PIN, False)

def buzzer_set(on: bool):
    global MUTE
    if MUTE:
        # force silence
        buzzer.value = BUZZER_ACTIVE_LOW
        return
    if BUZZER_ACTIVE_LOW:
        buzzer.value = (not on)   # ON=LOW, OFF=HIGH
    else:
        buzzer.value = bool(on)   # ON=HIGH, OFF=LOW

def buzzer_off_hard():
    buzzer.value = BUZZER_ACTIVE_LOW
    time.sleep(0.02)

# ✅ silence at start
buzzer_off_hard()
buzzer_set(False)

# ==========================
# LEDs (your pins)
# ==========================
# Red + Orange LEDs as you requested:
R = make_out(board.D5, False)     # Red
O = make_out(board.D13, False)    # Orange

def leds_off():
    R.value = False
    O.value = False

def leds_blink_step(state: bool):
    """One blink step: state True=ON, False=OFF."""
    R.value = state
    O.value = state

# ==========================
# Alarm pattern (buzzer + blink LEDs)
# ==========================
def alarm_pattern(duration_s: float = 2.0, on_s: float = 0.12, off_s: float = 0.12):
    end_t = time.time() + duration_s
    blink_state = False
    while time.time() < end_t and (not _should_exit):
        blink_state = not blink_state
        leds_blink_step(blink_state)

        buzzer_set(True)
        time.sleep(on_s)
        buzzer_set(False)
        time.sleep(off_s)

    # return to OFF after alarm
    leds_off()
    buzzer_set(False)

def safe_exit(lcd=None, code=0):
    global MUTE
    try:
        MUTE = True
        buzzer_set(False)
        buzzer_off_hard()
    except Exception:
        pass

    try:
        leds_off()
    except Exception:
        pass

    # deinit pins
    for obj in (buzzer, R, O):
        try:
            obj.deinit()
        except Exception:
            pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.3)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 9 exited cleanly.")
    sys.exit(code)

# ==========================
# Audio settings
# ==========================
SAMPLE_RATE = 48000
BLOCK_MS = 20
CHANNELS = 1
BLOCK_SIZE = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))
INPUT_DEVICE = 1  # set to your working device index

_latest_peak = 0.0
def audio_callback(indata, frames, time_info, status):
    global _latest_peak
    x = indata[:, 0].astype(np.float32)
    _latest_peak = float(np.max(np.abs(x)))

# ==========================
# Loud detection tuning
# ==========================
USE_AUTO_THRESHOLD = True
AUTO_MULTIPLIER = 7.0
AUTO_FLOOR = 0.12
FIXED_THRESHOLD = 0.20

HOLD_MS = 120
HOLD_S = HOLD_MS / 1000.0

COOLDOWN_MS = 1500
COOLDOWN_S = COOLDOWN_MS / 1000.0

noise_peaks = []
NOISE_WINDOW = 200

def get_threshold():
    if not USE_AUTO_THRESHOLD:
        return FIXED_THRESHOLD
    if len(noise_peaks) < 15:
        return max(FIXED_THRESHOLD, AUTO_FLOOR)
    base = float(np.median(noise_peaks))
    thr = max(AUTO_FLOOR, base * AUTO_MULTIPLIER)
    return max(thr, FIXED_THRESHOLD)

# ==========================
# Main
# ==========================
print("Exercise 9: Sound Alert System running...")
print(f"Mic device={INPUT_DEVICE} SR={SAMPLE_RATE} block={BLOCK_MS}ms")
print("Stop: Stop button or Ctrl+C")
print("Red LED: D5 | Orange LED: D13 | Buzzer pin:", BUZZER_PIN)

lcd = None
if USE_LCD:
    try:
        lcd = lcd_init()
        lcd_write(lcd, "Sound Alert", "Listening...")
    except Exception as e:
        print(f"[LCD] init failed, continuing without LCD: {e}")
        lcd = None

loud_started = None
last_alert_t = 0.0
last_print = 0.0
state = "IDLE"

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
            now = time.time()

            # learn ambient when not crazy loud
            if _latest_peak < 0.35:
                noise_peaks.append(_latest_peak)
                if len(noise_peaks) > NOISE_WINDOW:
                    noise_peaks.pop(0)

            thr = get_threshold()
            is_loud = (_latest_peak >= thr)

            # loud hold logic
            if is_loud:
                if loud_started is None:
                    loud_started = now
            else:
                loud_started = None

            loud_confirmed = (loud_started is not None) and ((now - loud_started) >= HOLD_S)
            cooldown_ok = (now - last_alert_t) >= COOLDOWN_S

            if loud_confirmed and state != "ALERT":
                state = "ALERT"
                if lcd:
                    lcd_write(lcd, "LOUD SOUND!", "ALERT!")
                print("🚨 LOUD SOUND DETECTED")

            if (not loud_confirmed) and state != "IDLE":
                state = "IDLE"
                leds_off()
                buzzer_set(False)
                if lcd:
                    lcd_write(lcd, "Listening...", f"thr {thr:.2f}")

            # Trigger alarm (buzzer + blink LEDs)
            if loud_confirmed and cooldown_ok:
                last_alert_t = now
                alarm_pattern(duration_s=2.0)

            # debug print 1/sec
            if now - last_print > 1.0:
                print(f"peak={_latest_peak:.3f} thr={thr:.3f} loud={'YES' if loud_confirmed else 'no'}")
                last_print = now

            time.sleep(0.01)

    safe_exit(lcd, 0)

except KeyboardInterrupt:
    safe_exit(lcd, 0)

except Exception as e:
    print("\n❌ Audio stream failed:")
    print("   ", repr(e))
    try:
        print("\nAvailable devices:\n", sd.query_devices())
    except Exception:
        pass
    if lcd:
        try:
            lcd_write(lcd, "AUDIO ERROR", str(e)[:16])
        except Exception:
            pass
    safe_exit(lcd, 1)