# Exercise 5: Air Pressure Reading (BMP280) + LCD via TCA9548A
# Input: BMP280 via I2C
# Output: LCD displays pressure + temperature

import time

# ---- LCD via TCA9548A ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# ---- BMP280 ----
import board
import busio
import adafruit_bmp280

# ---------- SETTINGS ----------
I2C_BUS  = 1
MUX_ADDR = 0x70

# LCD on mux channel:
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# BMP280 mux channel:
# If your BMP280 is on the SAME mux channel as the LCD, set this equal to LCD_CH.
BMP_CH   = 2

# BMP280 I2C address: usually 0x76 or 0x77
BMP_ADDR = 0x76
# ----------------------------

def mux_select(channel: int):
    if not (0 <= channel <= 7):
        raise ValueError("TCA9548A channel must be 0..7")
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

def bmp_init():
    # Select BMP channel BEFORE creating/using I2C
    mux_select(BMP_CH)
    i2c = busio.I2C(board.SCL, board.SDA)
    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=BMP_ADDR)

    # Optional: tuning (safe defaults)
    bmp.sea_level_pressure = 1013.25  # hPa (used for altitude calc only)

    return bmp

print("Exercise 5 running (BMP280 + LCD)... Ctrl+C to stop.")

# Init LCD (continue even if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "BMP280 Ready", "Reading...")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

# Init BMP280
bmp = None
try:
    bmp = bmp_init()
except Exception as e:
    print(f"[BMP280] init failed: {e}")
    if lcd:
        lcd_write(lcd, "BMP280 ERROR", str(e)[:16])
    # keep showing error
    while True:
        time.sleep(2)

last_display = None

try:
    while True:
        try:
            # Select BMP channel before reading
            mux_select(BMP_CH)

            temp_c = bmp.temperature                  # °C
            pressure_hpa = bmp.pressure               # hPa
            pressure_kpa = pressure_hpa / 10.0        # kPa

            line1 = f"T:{temp_c:>5.1f}C"
            line2 = f"P:{pressure_kpa:>5.1f}kPa"

        except Exception as e:
            print(f"[BMP280] read error: {e}")
            line1 = "Read error"
            line2 = "Check BMP280"

        if lcd:
            display = (line1, line2)
            if display != last_display:
                lcd_write(lcd, line1, line2)
                last_display = display

        time.sleep(2)

except KeyboardInterrupt:
    print("\nStopped.")
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
