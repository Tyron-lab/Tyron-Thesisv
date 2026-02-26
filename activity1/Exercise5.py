# Exercise 5: Air Pressure Reading (BMP280) + LCD via TCA9548A
# Fix: mux settle delays + no lcd.clear() flicker + stable I2C init

import time
import signal
import sys

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

import board
import busio
import adafruit_bmp280

# ---------- SETTINGS ----------
I2C_BUS  = 1
MUX_ADDR = 0x70

LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

BMP_CH   = 2
BMP_ADDRS = [0x76, 0x77]

SEA_LEVEL_HPA = 1013.25
# ----------------------------

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

def mux_select(channel: int):
    if not (0 <= channel <= 7):
        raise ValueError("TCA9548A channel must be 0..7")
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)
    # ✅ important: give mux a moment
    time.sleep(0.03)

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
    """Write without clear (prevents flicker + faster)."""
    mux_select(LCD_CH)
    l1 = (line1 or "").ljust(LCD_COLS)[:LCD_COLS]
    l2 = (line2 or "").ljust(LCD_COLS)[:LCD_COLS]
    lcd.cursor_pos = (0, 0)
    lcd.write_string(l1)
    lcd.cursor_pos = (1, 0)
    lcd.write_string(l2)

def bmp_init(i2c):
    mux_select(BMP_CH)
    last_err = None
    for addr in BMP_ADDRS:
        try:
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
            bmp.sea_level_pressure = SEA_LEVEL_HPA
            return bmp, addr
        except Exception as e:
            last_err = e
    raise RuntimeError(f"BMP280 not found at {BMP_ADDRS}: {last_err}")

print("Exercise 5 running (BMP280 + LCD)... (Stop button / Ctrl+C to stop)")

# Init LCD
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "BMP280 Ready", "Reading...")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

# Create ONE I2C object for whole program (stable)
i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

# Init BMP280
bmp = None
bmp_addr = None
try:
    bmp, bmp_addr = bmp_init(i2c)
    print(f"[BMP280] OK addr=0x{bmp_addr:02X} mux_ch={BMP_CH}")
except Exception as e:
    print(f"[BMP280] init failed: {e}")
    if lcd:
        try:
            lcd_write(lcd, "BMP280 ERROR", str(e)[:16])
        except Exception:
            pass
    while not _should_exit:
        time.sleep(0.3)

last_print = 0.0

try:
    while not _should_exit and bmp is not None:
        try:
            mux_select(BMP_CH)

            temp_c = float(bmp.temperature)      # °C
            pressure_hpa = float(bmp.pressure)   # hPa
            pressure_kpa = pressure_hpa / 10.0   # kPa

            line1 = f"T:{temp_c:5.1f}C"
            line2 = f"P:{pressure_kpa:5.1f}kPa"

            # ✅ also print every 1s so you can confirm values are updating
            now = time.time()
            if now - last_print > 1.0:
                print(f"T={temp_c:.2f}C  P={pressure_hpa:.2f}hPa ({pressure_kpa:.2f}kPa)")
                last_print = now

        except Exception as e:
            print(f"[BMP280] read error: {e}")
            line1 = "Read error"
            line2 = "Check BMP280"

        if lcd:
            lcd_write(lcd, line1, line2)

        time.sleep(0.5)

finally:
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.4)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
    print("Exercise 5 exited cleanly.")
    sys.exit(0)