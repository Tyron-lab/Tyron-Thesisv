# Exercise 2: Gas Detection (Gas sensor -> Status) + LCD via TCA9548A
# GREEN = SAFE / CLEAR
# RED   = DETECTED / ALERT
# (ORANGE NOT USED)

import time
import signal
import sys

import board
import digitalio

# ---- LCD via TCA9548A ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# CHANGE THESE IF NEEDED:
I2C_BUS  = 1
MUX_ADDR = 0x70      # TCA9548A default
LCD_CH   = 0         # channel where LCD is plugged (0..7)
LCD_ADDR = 0x27      # LCD backpack address (often 0x27 or 0x3F)

LCD_COLS = 16
LCD_ROWS = 2

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button sends SIGTERM
signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)  # Ctrl+C too

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

def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = bool(initial)
    return io

def make_in(pin, pull_up=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    if pull_up:
        try:
            io.pull = digitalio.Pull.UP
        except Exception:
            pass
    return io

# Status LEDs (match your Tools pins)
R = make_out(board.D5, False)    # RED = DETECT
G = make_out(board.D6, False)    # GREEN = SAFE

# --- Gas sensor input pin ---
GAS_PIN = board.D17
gas = make_in(GAS_PIN, pull_up=False)

def all_off():
    R.value = False
    G.value = False

def show_safe():
    # GREEN ON only
    R.value = False
    G.value = True

def show_alert():
    # RED ON only
    G.value = False
    R.value = True

# --- Detection tuning ---
SAMPLES = 20
SAMPLE_DELAY = 0.02
ALERT_PERCENT = 30

# If your module outputs inverted logic, set this True/False
INVERT_DO = True

def read_level_percent():
    hits = 0
    for _ in range(SAMPLES):
        if _should_exit:
            break
        v = gas.value
        if INVERT_DO:
            v = not v
        if v:
            hits += 1
        time.sleep(SAMPLE_DELAY)
    if SAMPLES <= 0:
        return 0
    return int(round(100 * hits / SAMPLES))

print("Gas Detection running... (Stop button / Ctrl+C to stop)")
all_off()

# Init LCD (if it fails, keep running without LCD)
lcd = None
try:
    lcd = lcd_init()
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

last_state = None  # "SAFE" or "ALERT"

try:
    # default SAFE
    show_safe()
    if lcd:
        lcd_write(lcd, "Ready", "Checking gas")

    while not _should_exit:
        level = read_level_percent()
        alert = (level >= ALERT_PERCENT)

        if alert:
            state = "ALERT"
            if state != last_state:
                print(f"🚨 SMOKE/GAS DETECTED (level {level}%)")

            show_alert()

            if lcd:
                lcd_write(lcd, "SMOKE DETECT!", f"Level: {level}%")

            # small delay but responsive
            time.sleep(0.12)

        else:
            state = "SAFE"
            if state != last_state:
                print(f"✅ CLEAR (level {level}%)")

            show_safe()

            if lcd:
                lcd_write(lcd, "CLEAR / SAFE", f"Level: {level}%")

            time.sleep(0.2)

        last_state = state

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    all_off()
    R.value = True
    if lcd:
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except Exception:
            pass
    time.sleep(2)

finally:
    # ✅ Clean stop
    all_off()

    try:
        gas.deinit()
    except Exception:
        pass

    try:
        R.deinit()
        G.deinit()
    except Exception:
        pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.6)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 2 exited cleanly.")
    sys.exit(0)