# Exercise 4: Distance Measurement (HC-SR04) using digitalio timing + Passive Buzzer + LCD via TCA9548A
# TRIG = board.D23, ECHO = board.D24
# Output: LCD shows distance; buzzer beeps when object is near
# NOTE: Buzzer is forced OFF on start + clean exit (SIGTERM safe)

import time
import signal
import sys

import board
import digitalio

# ---- LCD via TCA9548A ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# --- I2C / MUX / LCD settings ---
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ---- Ultrasonic pins ----
TRIG_PIN = board.D23
ECHO_PIN = board.D24

# ---- Buzzer pin ----
BUZZER_PIN = board.D16  # <-- your current buzzer pin

# ✅ If you want COMPLETELY SILENT even when near, set this True.
MUTE = False

# If your buzzer is wired as active-low (beeps when pin is LOW), set True.
# If it beeps when pin is HIGH, set False.
BUZZER_ACTIVE_LOW = True

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button sends SIGTERM, Ctrl+C sends SIGINT
signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# ---------------- LCD helpers ----------------
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

# ---------------- GPIO setup ----------------
TRIG = digitalio.DigitalInOut(TRIG_PIN)
ECHO = digitalio.DigitalInOut(ECHO_PIN)
TRIG.direction = digitalio.Direction.OUTPUT
ECHO.direction = digitalio.Direction.INPUT
TRIG.value = False

# ---------------- Buzzer setup (SAFE) ----------------
buzzer = None
BUZZER_OK = False

def buzzer_set(on: bool):
    """Hard ON/OFF with correct polarity. Always use this (never buzzer.value directly)."""
    global buzzer, BUZZER_OK
    if (not BUZZER_OK) or (buzzer is None) or MUTE:
        return

    if BUZZER_ACTIVE_LOW:
        # ON = LOW(False), OFF = HIGH(True)
        buzzer.value = (not on)
    else:
        # ON = HIGH(True), OFF = LOW(False)
        buzzer.value = bool(on)

def buzzer_off_hard():
    """Force OFF no matter what."""
    global buzzer, BUZZER_OK
    if (not BUZZER_OK) or (buzzer is None):
        return
    # OFF state: active-low -> HIGH(True), active-high -> LOW(False)
    buzzer.value = True if BUZZER_ACTIVE_LOW else False
    time.sleep(0.02)

def init_buzzer():
    """Try to claim buzzer pin. If GPIO busy, continue without buzzer."""
    global buzzer, BUZZER_OK
    try:
        buzzer = digitalio.DigitalInOut(BUZZER_PIN)
        buzzer.direction = digitalio.Direction.OUTPUT
        BUZZER_OK = True

        # ✅ First thing: silence buzzer immediately
        buzzer_off_hard()
        buzzer_set(False)
        return True
    except Exception as e:
        BUZZER_OK = False
        buzzer = None
        print(f"[BUZZER] init failed (GPIO busy or pin conflict): {repr(e)}")
        print("[BUZZER] Continuing WITHOUT buzzer. (Ultrasonic + LCD will still work)")
        print("[BUZZER] Fix options:")
        print("  1) Stop other exercises still running (they may hold GPIO)")
        print("  2) Change BUZZER_PIN to another free pin (e.g. board.D17 / board.D22 / board.D25)")
        return False

# Attempt buzzer init once
init_buzzer()

# ---------------- Behavior tuning ----------------
NEAR_CM = 20.0
VERY_NEAR_CM = 8.0

def measure_distance():
    # Trigger pulse (10µs)
    TRIG.value = True
    time.sleep(0.00001)
    TRIG.value = False

    pulse_start = time.time()
    timeout = pulse_start + 0.1  # 100ms timeout

    # Wait for echo high
    while (not ECHO.value) and time.time() < timeout:
        pulse_start = time.time()

    # Wait for echo low
    pulse_end = time.time()
    while ECHO.value and time.time() < timeout:
        pulse_end = time.time()

    # Timeout/no object
    if pulse_end - pulse_start > 0.1:
        return None

    duration = pulse_end - pulse_start
    distance_cm = duration * 17150  # cm/s / 2
    return round(distance_cm, 1)

def beep_once(on_s: float, off_s: float):
    if MUTE or not BUZZER_OK:
        time.sleep(on_s + off_s)
        return
    buzzer_set(True)
    time.sleep(on_s)
    buzzer_set(False)
    time.sleep(off_s)

def beep_pattern(distance_cm: float):
    # Simple ON/OFF beeps (works without PWM)
    if MUTE or not BUZZER_OK:
        return

    if distance_cm <= VERY_NEAR_CM:
        beep_once(0.06, 0.06)
    elif distance_cm <= NEAR_CM:
        beep_once(0.10, 0.18)
    else:
        buzzer_set(False)
        time.sleep(0.12)

print("Exercise 4 running (ultrasonic)... Stop button / Ctrl+C to stop.")
print("Buzzer muted?" , MUTE)
print("BUZZER_ACTIVE_LOW =", BUZZER_ACTIVE_LOW)
print("BUZZER_OK =", BUZZER_OK)

# Init LCD
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ultrasonic", "Measuring...")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

last_display = None

try:
    while not _should_exit:
        dist = measure_distance()

        if dist is None or not (2 <= dist <= 400):
            line1 = "Dist: ---"
            line2 = "Out of range"
            buzzer_set(False)
            time.sleep(0.2)
        else:
            line1 = f"Dist: {dist:>6.1f}cm"
            if MUTE:
                line2 = "MUTED"
            else:
                line2 = "NEAR! BEEP!" if (BUZZER_OK and dist <= NEAR_CM) else "OK"
            beep_pattern(dist)

        # LCD update (reduce flicker)
        if lcd:
            display = (line1, line2)
            if display != last_display:
                lcd_write(lcd, line1, line2)
                last_display = display

except KeyboardInterrupt:
    print("\nStopped (KeyboardInterrupt).")

finally:
    # ✅ cleanup: FORCE SILENT
    try:
        MUTE = True
        buzzer_set(False)
        buzzer_off_hard()
    except Exception:
        pass

    try:
        if buzzer is not None:
            buzzer.deinit()
    except Exception:
        pass

    try:
        TRIG.value = False
        TRIG.deinit()
        ECHO.deinit()
    except Exception:
        pass

    if lcd:
        try:
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 4 exited cleanly.")
    sys.exit(0)