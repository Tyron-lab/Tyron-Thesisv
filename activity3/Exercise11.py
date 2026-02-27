# Activity 3 - Exercise 11: I²C Sensor Reading (BMP280 -> LCD)
# Input: BMP280 sensor data via I2C (through TCA9548A mux)
# Output: LCD shows temperature + pressure

import time
import signal
import sys               # ← added for sys.exit()

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

# MUX channel where LCD is connected (SDx/SCx -> x)
LCD_CH   = 0
LCD_ADDR = 0x27     # common: 0x27 or 0x3F

# MUX channel where BMP280 is connected (SDx/SCx -> x)
BMP_CH   = 2

# BMP280 I2C address (common: 0x76 or 0x77)
# If you're not sure, leave BMP_ADDR=None and it will auto-try 0x76 then 0x77
BMP_ADDR = None

LCD_COLS = 16
LCD_ROWS = 2
# =========================


# ────────────────────────────────────────────────
# Added: SIGTERM + SIGINT handling (Stop button / Ctrl+C)
# ────────────────────────────────────────────────
_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)
# ────────────────────────────────────────────────


def mux_select(channel: int):
    """Select TCA9548A channel (0..7)."""
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
        charmap="A00",
    )
    lcd.clear()
    return lcd


def lcd_write(lcd, line1: str, line2: str = ""):
    mux_select(LCD_CH)
    lcd.clear()
    lcd.write_string((line1 or "")[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string((line2 or "")[:LCD_COLS])


def bmp_init(i2c):
    """Init BMP280 on its mux channel. Tries address 0x76 then 0x77 if BMP_ADDR is None."""
    mux_select(BMP_CH)

    addrs = [BMP_ADDR] if BMP_ADDR is not None else [0x76, 0x77]
    last_err = None

    for addr in addrs:
        try:
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
            # Sea level pressure only affects altitude calc; safe to keep default.
            bmp.sea_level_pressure = 1013.25
            return bmp, addr
        except Exception as e:
            last_err = e

    raise RuntimeError(f"BMP280 not found at {addrs}. Last error: {last_err}")


def format_lines(temp_c: float, pressure_hpa: float):
    # LCD is 16x2, so keep it short and readable
    # Pressure in kPa looks nice: 1013 hPa = 101.3 kPa
    pressure_kpa = pressure_hpa / 10.0
    line1 = f"T:{temp_c:>5.1f}C"
    line2 = f"P:{pressure_kpa:>5.1f}kPa"
    return line1, line2


print("Exercise 11 running (BMP280 -> LCD)... Ctrl+C to stop.")

# Init LCD (continue even if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ex11 BMP280", "Starting...")
except Exception as e:
    print(f"[LCD] init failed (continuing without LCD): {e}")
    lcd = None

# Create I2C object once
i2c = busio.I2C(board.SCL, board.SDA)

# Init BMP280
try:
    bmp, used_addr = bmp_init(i2c)
    print(f"[BMP280] OK at address 0x{used_addr:02X} on mux channel {BMP_CH}")
    if lcd:
        lcd_write(lcd, "BMP280 OK", f"Addr 0x{used_addr:02X} CH{BMP_CH}")
        time.sleep(1.2)
except Exception as e:
    print(f"[BMP280] init failed: {e}")
    if lcd:
        lcd_write(lcd, "BMP280 ERROR", str(e)[:16])
    # Stop here (keeps LCD showing error)
    while True:
        time.sleep(2)

last_display = None

try:
    while True:
        if _should_exit:
            break

        try:
            mux_select(BMP_CH)
            temp_c = float(bmp.temperature)
            pressure_hpa = float(bmp.pressure)

            line1, line2 = format_lines(temp_c, pressure_hpa)
            print(f"Temp={temp_c:.1f}C  Pressure={pressure_hpa:.1f}hPa")

        except Exception as e:
            print(f"[BMP280] read error: {e}")
            line1, line2 = "READ ERROR", "Check wiring"

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

# ────────────────────────────────────────────────
# Added: final cleanup on SIGTERM / SIGINT exit
# ────────────────────────────────────────────────
finally:
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 11 exited cleanly.")
    sys.exit(0)