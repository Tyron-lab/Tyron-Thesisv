# Activity2/Exercise6.py
# Exercise 6: Normal vs Abnormal Data
# Input: Sensor readings
# What happens: System checks if values are normal
# Output: GREEN stays ON (normal) or ORANGE blinks (abnormal), RED on error
#
# Uses LCD via TCA9548A (I2C extender) like your Exercise1.py

import time
import random
import board
import digitalio

# ---- LCD via TCA9548A ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# ========== EDIT THESE IF NEEDED ==========
I2C_BUS  = 1
MUX_ADDR = 0x70      # TCA9548A default
LCD_CH   = 0         # channel where LCD is plugged
LCD_ADDR = 0x27      # LCD backpack addr (0x27 or 0x3F)

LCD_COLS = 16
LCD_ROWS = 2

# Sensor "normal range" (demo values)
NORMAL_MIN = 10
NORMAL_MAX = 90

# Blink behavior when abnormal
BLINK_ON  = 0.25
BLINK_OFF = 0.25
# =========================================

def mux_select(channel: int):
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)

def lcd_init():
    mux_select(LCD_CH)
    lcd = CharLCD('PCF8574', address=LCD_ADDR, port=I2C_BUS,
                  cols=LCD_COLS, rows=LCD_ROWS, charmap='A00')
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
    io.value = initial
    return io

def all_off(R, G, O):
    R.value = False
    G.value = False
    O.value = False

# Status LEDs (same as your Exercise1)
R = make_out(board.D17, False)   # RED = error
G = make_out(board.D27, False)   # GREEN = normal/ok
O = make_out(board.D22, False)   # ORANGE = abnormal/blink

# ---- Replace this with your real sensor read later ----
def read_sensor_value():
    # Demo: random 0..100
    return random.randint(0, 100)

print("Exercise 6: Normal vs Abnormal Data")
all_off(R, G, O)

# Init LCD (if it fails, continue without LCD)
lcd = None
try:
    lcd = lcd_init()
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

# Show startup on LCD
if lcd:
    lcd_write(lcd, "Exercise 6", "Checking...")

last_state = None  # "NORMAL" or "ABNORMAL"

try:
    while True:
        value = read_sensor_value()
        normal = (NORMAL_MIN <= value <= NORMAL_MAX)
        state = "NORMAL" if normal else "ABNORMAL"

        # Only update outputs when state changes (prevents LCD flicker)
        if state != last_state:
            if normal:
                # Normal: GREEN ON solid
                R.value = False
                O.value = False
                G.value = True
                print(f"✅ NORMAL ({value}) -> GREEN ON")

                if lcd:
                    lcd_write(lcd, "NORMAL", f"Val: {value}")

            else:
                # Abnormal: GREEN OFF, ORANGE BLINK
                R.value = False
                G.value = False
                print(f"⚠️ ABNORMAL ({value}) -> ORANGE BLINK")

                if lcd:
                    lcd_write(lcd, "ABNORMAL!", f"Val: {value}")

            last_state = state

        # Maintain behavior
        if not normal:
            # Blink ORANGE while abnormal
            O.value = True
            time.sleep(BLINK_ON)
            O.value = False
            time.sleep(BLINK_OFF)
        else:
            # Normal steady (just poll)
            time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped by user.")
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    all_off(R, G, O)
    R.value = True
    if lcd:
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except Exception:
            pass
    time.sleep(5)

finally:
    all_off(R, G, O)
    R.deinit()
    G.deinit()
    O.deinit()
    if lcd:
        try:
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass