# Exercise 1: Motion Detection (PIR -> Status LEDs) + LCD messages via TCA9548A
# LED RED    = D5   (MOTION DETECTED)
# LED GREEN  = D6   (NO MOTION)
# LED ORANGE = D13  (WARMUP / CALIBRATING)
# PIR INPUT  = D18

import time
import signal
import sys

import board
import digitalio

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# CHANGE THESE IF NEEDED:
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27

LCD_COLS = 16
LCD_ROWS = 2

# ✅ If your PIR logic is reversed, set this True
INVERT_PIR = True

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button sends SIGTERM, Ctrl+C sends SIGINT
signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

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

def make_in_pir(pin):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    # ✅ stabilize idle state
    try:
        io.pull = digitalio.Pull.DOWN
    except Exception:
        pass
    return io

# Status LEDs
R = make_out(board.D5, False)    # RED
G = make_out(board.D6, False)    # GREEN
       # ORANGE

# PIR input
pir = make_in_pir(board.D22)

def all_off():
    R.value = False
    G.value = False
    O.value = False

def show_detected():
    # ✅ RED = motion
    R.value = True
    G.value = False
    O.value = False

def show_no_motion():
    # ✅ GREEN = no motion
    R.value = False
    G.value = True
    O.value = False

def read_motion() -> bool:
    v = bool(pir.value)
    return (not v) if INVERT_PIR else v

print("PIR Motion Detection: warming up PIR (30s)...")
all_off()

# Init LCD (if it fails, keep running without LCD)
lcd = None
try:
    lcd = lcd_init()
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

warmup_seconds = 30

if lcd:
    lcd_write(lcd, "Calibrating...", f"Wait {warmup_seconds}s")

# Warmup blink ORANGE
for sec_left in range(warmup_seconds, 0, -1):
    if _should_exit:
        break
    O.value = True
    time.sleep(0.5)
    O.value = False
    time.sleep(0.5)
    if lcd:
        lcd_write(lcd, "Calibrating...", f"Wait {sec_left-1}s")

O.value = False

if _should_exit:
    print("Stopped (SIGTERM) during warmup.")
else:
    print("Monitoring motion... (Stop button to end)")

last_motion = None

try:
    # Start safe
    show_no_motion()
    if lcd:
        lcd_write(lcd, "Ready", "No motion")

    while not _should_exit:
        motion = read_motion()

        # ✅ enforce LED state every cycle (prevents weird stuck states)
        if motion:
            show_detected()
        else:
            show_no_motion()

        if motion != last_motion:
            if motion:
                print("🚨 MOTION DETECTED")
                if lcd:
                    lcd_write(lcd, "Detected!", "Motion found")
            else:
                print("✅ NO MOTION")
                if lcd:
                    lcd_write(lcd, "Ready", "No motion")
            last_motion = motion

        time.sleep(0.05)

except Exception as e:
    print(f"❌ ERROR: {e}")
    all_off()
    R.value = True
    if lcd:
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except Exception:
            pass
    time.sleep(1)

finally:
    try:
        if lcd:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.4)
            mux_select(LCD_CH)
            lcd.clear()
    except Exception:
        pass

    all_off()
    try: pir.deinit()
    except Exception: pass
    try: R.deinit()
    except Exception: pass
    try: G.deinit()
    except Exception: pass
    try: O.deinit()
    except Exception: pass

    print("Exercise 1 exited cleanly.")
    sys.exit(0)