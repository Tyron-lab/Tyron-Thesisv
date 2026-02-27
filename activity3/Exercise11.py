# Activity 3 - Exercise 11: I²C Sensor Reading (BMP280 -> LCD)
# Now with SIGTERM + SIGINT handling for clean Stop button / Ctrl+C exit

import time
import signal
import sys

# ---- I2C mux (TCA9548A) ----
from smbus2 import SMBus

# ---- LCD ----
from RPLCD.i2c import CharLCD

# ---- BMP280 ----
import board
import busio
import adafruit_bmp280

# =========================
# SETTINGS (EDIT THESE)
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

BMP_CH   = 2
BMP_ADDR = None  # None -> auto try 0x76 then 0x77

# =========================

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
    time.sleep(0.02)  # small settle time

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
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1.ljust(LCD_COLS)[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string(line2.ljust(LCD_COLS)[:LCD_COLS])

try:
    lcd = lcd_init()

    # BMP280 init
    mux_select(BMP_CH)
    i2c = busio.I2C(board.SCL, board.SDA)
    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76 if BMP_ADDR is None else BMP_ADDR)

    last_display = None

    while not _should_exit:
        try:
            mux_select(BMP_CH)
            temp_c = float(bmp.temperature)
            pressure_hpa = float(bmp.pressure)

            line1 = f"T: {temp_c:>5.1f} C"
            line2 = f"P: {pressure_hpa:>5.1f} hPa"

            print(f"Temp={temp_c:.1f}C  Pressure={pressure_hpa:.1f}hPa")

        except Exception as e:
            print(f"[BMP280] read error: {e}")
            line1 = "READ ERROR"
            line2 = "Check wiring"

        if lcd:
            display = (line1, line2)
            if display != last_display:
                lcd_write(lcd, line1, line2)
                last_display = display

        time.sleep(2)

except Exception as e:
    print(f"\n❌ Fatal error: {e}")
    if 'lcd' in locals():
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except:
            pass

finally:
    if 'lcd' in locals() and lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.6)
            mux_select(LCD_CH)
            lcd.clear()
        except:
            pass

    print("Exercise 11 exited cleanly.")
    sys.exit(0) 