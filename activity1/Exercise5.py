# Exercise 5: Air Pressure Reading (BMP280) + LCD via TCA9548A
# Input: BMP280 via I2C
# Output: LCD displays pressure + temperature
# FIX: SIGTERM support + clean shutdown so you can run again

import time
import signal
import sys

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
BMP_CH   = 2

# BMP280 I2C address preference (we will auto-try both)
BMP_ADDRS = [0x76, 0x77]

# Optional altitude calc base pressure (hPa)
SEA_LEVEL_HPA = 1013.25
# ----------------------------

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button sends SIGTERM
signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)  # Ctrl+C

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

    # Create I2C bus (CircuitPython style)
    i2c = busio.I2C(board.SCL, board.SDA)

    # Wait a bit for I2C lock (important when starting/stopping)
    t0 = time.time()
    while not i2c.try_lock():
        if time.time() - t0 > 2.0:
            raise RuntimeError("I2C lock timeout")
        time.sleep(0.05)

    try:
        # Try both addresses (0x76 then 0x77)
        last_err = None
        for addr in BMP_ADDRS:
            try:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                bmp.sea_level_pressure = SEA_LEVEL_HPA
                return bmp, i2c, addr
            except Exception as e:
                last_err = e
        raise RuntimeError(f"BMP280 not found at {BMP_ADDRS}: {last_err}")
    finally:
        try:
            i2c.unlock()
        except Exception:
            pass

print("Exercise 5 running (BMP280 + LCD)... (Stop button / Ctrl+C to stop)")

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
i2c_bus = None
bmp_addr = None

try:
    bmp, i2c_bus, bmp_addr = bmp_init()
    print(f"[BMP280] OK addr=0x{bmp_addr:02X} mux_ch={BMP_CH}")
except Exception as e:
    print(f"[BMP280] init failed: {e}")
    if lcd:
        try:
            lcd_write(lcd, "BMP280 ERROR", str(e)[:16])
        except Exception:
            pass
    # Stay alive until stopped, but don't crash/restart loop
    while not _should_exit:
        time.sleep(0.3)

last_display = None

try:
    while not _should_exit and bmp is not None:
        try:
            # Select BMP channel before reading
            mux_select(BMP_CH)

            temp_c = bmp.temperature            # °C
            pressure_hpa = bmp.pressure         # hPa
            pressure_kpa = pressure_hpa / 10.0  # kPa

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

        # Responsive sleep
        for _ in range(20):
            if _should_exit:
                break
            time.sleep(0.1)

finally:
    # ✅ Clean shutdown (same style as Exercise 3)
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.6)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    # busio.I2C has no deinit in this style; just let it go.
    # But we make sure no buzzy loops keep running.
    print("Exercise 5 exited cleanly.")
    sys.exit(0)