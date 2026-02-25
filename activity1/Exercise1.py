# Exercise 1: Motion Detection (PIR -> Status LEDs) + LCD messages via TCA9548A
# Uses GPIO pins:
#   LED RED    = D5
#   LED GREEN  = D6
#   LED ORANGE = D13
#   PIR INPUT  = D18

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

_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button (server terminate) sends SIGTERM -> exit gracefully
signal.signal(signal.SIGTERM, _handle_term)

def mux_select(channel: int):
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)

def lcd_init():
    mux_select(LCD_CH)
    lcd = CharLCD('PCF8574', address=LCD_ADDR, port=I2C_BUS, cols=LCD_COLS, rows=LCD_ROWS, charmap='A00')
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

def make_in(pin):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    return io

# Status LEDs (match Tools pins)
R = make_out(board.D5, False)    # RED
G = make_out(board.D6, False)    # GREEN
O = make_out(board.D13, False)   # ORANGE

# PIR input
pir = make_in(board.D18)

def all_off():
    R.value = False
    G.value = False
    O.value = False

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
    G.value = True
    O.value = False
    R.value = False

    if lcd:
        lcd_write(lcd, "Ready", "No motion")

    while not _should_exit:
        motion = bool(pir.value)

        if motion != last_motion:
            if motion:
                print("🚨 MOTION DETECTED")
                G.value = False
                O.value = True
                if lcd:
                    lcd_write(lcd, "Detected!", "Motion found")
            else:
                print("✅ NO MOTION")
                O.value = False
                G.value = True
                if lcd:
                    lcd_write(lcd, "Ready", "No motion")
            last_motion = motion

        time.sleep(0.05)

except KeyboardInterrupt:
    print("Stopped by user (KeyboardInterrupt).")

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
    # Clean shutdown
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