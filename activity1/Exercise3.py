# Exercise 3: Temperature & Humidity (DHT11) + LCD via TCA9548A
# Output: LCD shows temperature and humidity (no LEDs)
# FIX: Handles SIGTERM + always releases DHT so you can run again without "already running"

import time
import signal
import sys

# ---- LCD via TCA9548A (same style as Exercise 1) ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# CHANGE THESE IF NEEDED (same defaults as Exercise 1)
I2C_BUS  = 1
MUX_ADDR = 0x70      # TCA9548A default
LCD_CH   = 0         # channel where LCD is plugged
LCD_ADDR = 0x27      # LCD backpack address (often 0x27 or 0x3F)

LCD_COLS = 16
LCD_ROWS = 2

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

# Stop button usually sends SIGTERM
signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)  # Ctrl+C

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

# ---- DHT11 ----
# Preferred: adafruit-circuitpython-dht
# Fallback: Adafruit_DHT (older)
dht = None
sensor = None

# Pick your DHT data pin here (change if your wiring is different)
DHT_PIN = None

try:
    import board
    import adafruit_dht

    DHT_PIN = board.D4  # <-- CHANGE THIS PIN if needed
    dht = adafruit_dht.DHT11(DHT_PIN)
    sensor = "adafruit_dht"

except Exception as e1:
    try:
        import Adafruit_DHT
        DHT_BCM = 4  # <-- CHANGE THIS GPIO if needed (BCM numbering)
        dht = (Adafruit_DHT, Adafruit_DHT.DHT11, DHT_BCM)
        sensor = "Adafruit_DHT"
    except Exception as e2:
        sensor = None
        dht = None

print("DHT11 Temperature & Humidity running... (Stop button / Ctrl+C to stop)")

# Init LCD (if it fails, keep running without LCD)
lcd = None
try:
    lcd = lcd_init()
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

def show_error(msg: str):
    print("ERROR:", msg)
    if lcd:
        lcd_write(lcd, "DHT11 ERROR", (msg or "")[:16])

if dht is None or sensor is None:
    show_error("No DHT lib")
    while not _should_exit:
        time.sleep(0.5)
    # exit cleanly
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.6)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
    sys.exit(0)

last_display = None

try:
    if lcd:
        lcd_write(lcd, "DHT11 Ready", "Reading...")

    while not _should_exit:
        temp_c = None
        hum = None

        try:
            if sensor == "adafruit_dht":
                # adafruit_dht sometimes throws RuntimeError; just retry
                temp_c = dht.temperature
                hum = dht.humidity

            elif sensor == "Adafruit_DHT":
                Adafruit_DHT, DHTTYPE, BCM = dht
                hum, temp_c = Adafruit_DHT.read_retry(DHTTYPE, BCM)

        except RuntimeError:
            # common with adafruit_dht
            temp_c = None
            hum = None

        except Exception as e:
            # If you see "DHT11 is running" here, it means previous instance wasn't released
            show_error(str(e))
            time.sleep(1.0)
            continue

        # Format lines for LCD
        if temp_c is None or hum is None:
            line1 = "Temp: --.- C"
            line2 = "Hum : -- %"
        else:
            line1 = f"Temp: {temp_c:>4.1f} C"
            line2 = f"Hum : {hum:>4.0f} %"

        display = (line1, line2)
        if lcd and display != last_display:
            lcd_write(lcd, line1, line2)
            last_display = display

        # small sleep, but still responsive to stop
        for _ in range(20):
            if _should_exit:
                break
            time.sleep(0.1)

finally:
    # ✅ CRITICAL: release DHT so next run works
    if sensor == "adafruit_dht" and dht:
        try:
            if lcd:
                lcd_write(lcd, "Stopping...", "Releasing DHT")
            dht.exit()
        except Exception:
            pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.6)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 3 exited cleanly.")
    sys.exit(0)