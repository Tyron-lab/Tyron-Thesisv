# Exercise 1: Motion Detection (PIR -> Status LEDs) + LCD messages via TCA9548A
# RED = error (D17)
# ORANGE = warning/motion (D22)
# GREEN = success/ok (D27)

import time
import board
import digitalio

# ---- LCD via TCA9548A ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# CHANGE THESE IF NEEDED:
I2C_BUS  = 1
MUX_ADDR = 0x70      # TCA9548A default
LCD_CH   = 0         # channel where LCD is plugged (SC0/SD0=0, SC1/SD1=1, ...)
LCD_ADDR = 0x27      # LCD backpack address (often 0x27 or 0x3F)

LCD_COLS = 16
LCD_ROWS = 2

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
    io.value = initial
    return io

def make_in(pin):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    return io

# Status LEDs
R = make_out(board.D17, False)   # RED
G = make_out(board.D27, False)   # GREEN
O = make_out(board.D22, False)   # ORANGE

# PIR input
pir = make_in(board.D18)

def all_off():
    R.value = False
    G.value = False
    O.value = False

print("PIR Motion Detection: warming up PIR (30s)...")
all_off()

# Init LCD (if it fails, we keep running without LCD)
lcd = None
try:
    lcd = lcd_init()
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

# Warm-up: blink ORANGE + show calibrating on LCD
warmup_seconds = 30

if lcd:
    lcd_write(lcd, "Calibrating...", f"Wait {warmup_seconds}s")

for sec_left in range(warmup_seconds, 0, -1):
    # blink every 0.5s twice per second
    O.value = True
    time.sleep(0.5)
    O.value = False
    time.sleep(0.5)

    if lcd and sec_left % 1 == 0:
        lcd_write(lcd, "Calibrating...", f"Wait {sec_left-1}s")

O.value = False

print("Monitoring motion... Ctrl+C to stop.")

# Default state: OK
last_motion = None
try:
    G.value = True
    O.value = False
    R.value = False

    if lcd:
        lcd_write(lcd, "Ready", "No motion")

    while True:
        motion = pir.value  # True = motion detected

        # Only update when state changes (prevents LCD flicker)
        if motion != last_motion:
            if motion:
                print("🚨 MOTION DETECTED")
                # LEDs
                G.value = False
                O.value = True
                # LCD
                if lcd:
                    lcd_write(lcd, "Detected!", "Motion found")
            else:
                print("✅ NO MOTION")
                # LEDs
                O.value = False
                G.value = True
                # LCD
                if lcd:
                    lcd_write(lcd, "Ready", "No motion")

            last_motion = motion

        time.sleep(0.05)

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
    all_off()
    R.value = True
    if lcd:
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except Exception:
            pass
    time.sleep(5)

finally:
    all_off()
    pir.deinit()
    R.deinit()
    G.deinit()
    O.deinit()
    if lcd:
        try:
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
