# Exercise 2: Gas Detection (Gas sensor -> Warning blink) + LCD messages via TCA9548A
# Reuses the same LCD/TCA9548A approach as Exercise 1.
# RED = error (D17)
# ORANGE = warning blink (D22)
# GREEN = ok (D27)

import time
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

def make_in(pin, pull_up=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    if pull_up:
        io.pull = digitalio.Pull.UP
    return io

# Status LEDs
R = make_out(board.D17, False)   # RED
G = make_out(board.D27, False)   # GREEN
O = make_out(board.D22, False)   # ORANGE

# --- Gas sensor input pin ---
# Connect GAS SENSOR "DO" to this GPIO (and VCC/GND accordingly).
# Change this if you used a different GPIO.
GAS_PIN = board.D23
gas = make_in(GAS_PIN, pull_up=False)

def all_off():
    R.value = False
    G.value = False
    O.value = False

def blink(pin_io, times=3, on_s=0.15, off_s=0.15):
    for _ in range(times):
        pin_io.value = True
        time.sleep(on_s)
        pin_io.value = False
        time.sleep(off_s)

# --- Detection tuning ---
# We "check gas level" by sampling DO many times and computing % triggered.
SAMPLES = 20
SAMPLE_DELAY = 0.02  # seconds between samples
ALERT_PERCENT = 30   # trigger alert if DO is active in >=30% of samples

# If your module outputs inverted logic, set this True.
# Typical MQ modules: DO often goes HIGH when gas/smoke exceeds threshold,
# but some boards are opposite.
INVERT_DO = True

def read_level_percent():
    hits = 0
    for _ in range(SAMPLES):
        v = gas.value
        if INVERT_DO:
            v = not v
        if v:
            hits += 1
        time.sleep(SAMPLE_DELAY)
    return int(round(100 * hits / SAMPLES))

print("Gas Detection running... Ctrl+C to stop.")
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
    G.value = True
    if lcd:
        lcd_write(lcd, "Ready", "Checking gas")

    while True:
        level = read_level_percent()
        alert = (level >= ALERT_PERCENT)

        if alert:
            state = "ALERT"
            if state != last_state:
                print(f"🚨 GAS/SMOKE DETECTED (level {level}%)")
                G.value = False

            # Blink warning LED continuously while alert
            blink(O, times=2, on_s=0.12, off_s=0.12)

            if lcd:
                lcd_write(lcd, "GAS ALERT!", f"Level: {level}%")
        else:
            state = "SAFE"
            if state != last_state:
                print(f"✅ Gas OK (level {level}%)")
                O.value = False
                G.value = True

            if lcd:
                lcd_write(lcd, "Gas OK", f"Level: {level}%")
            time.sleep(0.2)

        last_state = state

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
    gas.deinit()
    R.deinit()
    G.deinit()
    O.deinit()
    if lcd:
        try:
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
