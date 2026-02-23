# Activity 3 - Exercise 13: Display Output
# Input: Sensor values (DHT11, BMP280, MQ Gas DO)
# What happens: Data formatted for readability
# Output: LCD displays readable text (cycles screens)

import time
import importlib
from typing import TYPE_CHECKING

# ---- I2C mux (TCA9548A) ----
from smbus2 import SMBus

# ---- LCD ----
from RPLCD.i2c import CharLCD

# ---- GPIO / Board ----
import board
import digitalio

# ---- BMP280 ----
import busio
import adafruit_bmp280

# (For type-checkers only; avoids Pylance "missing import" noise on Windows)
if TYPE_CHECKING:
    import Adafruit_DHT  # noqa: F401


# =========================
# SETTINGS (EDIT THESE)
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

# LCD (mux channel + address)
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# BMP280 (mux channel)
BMP_CH   = 2
BMP_ADDR = None      # None -> auto try 0x76 then 0x77

# DHT11 pin (NOT I2C)
DHT_PIN = board.D4   # change if needed

# Gas DO pin (digital input)
GAS_PIN = board.D23
INVERT_GAS_DO = True

# screen timing (seconds per screen)
SCREEN_S = 3.0

# Gas "alert" threshold (0-100% from sampling)
GAS_ALERT_LEVEL = 30
# =========================


# =========================
# TCA9548A MUX HELPERS
# =========================
def mux_select(channel: int):
    if not (0 <= channel <= 7):
        raise ValueError("TCA9548A channel must be 0..7")
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)


# =========================
# LCD HELPERS
# =========================
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


def lcd_write(lcd: CharLCD, line1: str, line2: str = ""):
    mux_select(LCD_CH)
    lcd.clear()
    lcd.write_string((line1 or "")[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string((line2 or "")[:LCD_COLS])


# =========================
# DHT11 SETUP (preferred: adafruit_dht)
# fallback: Adafruit_DHT (BCM pin)
# =========================
dht = None
dht_mode = None

try:
    import adafruit_dht
    dht = adafruit_dht.DHT11(DHT_PIN)
    dht_mode = "adafruit_dht"
except Exception:
    try:
        Adafruit_DHT = importlib.import_module("Adafruit_DHT")
        # Adafruit_DHT uses BCM pin numbers; board.D4 corresponds to BCM 4
        dht = (Adafruit_DHT, Adafruit_DHT.DHT11, 4)
        dht_mode = "Adafruit_DHT"
    except Exception:
        dht = None
        dht_mode = None


def read_dht():
    """Returns (temp_c, humidity) or (None, None) if failed."""
    if dht_mode == "adafruit_dht":
        try:
            return float(dht.temperature), float(dht.humidity)
        except Exception:
            return None, None

    if dht_mode == "Adafruit_DHT":
        Adafruit_DHT, DHTTYPE, BCM = dht
        hum, temp = Adafruit_DHT.read_retry(DHTTYPE, BCM)
        if temp is None or hum is None:
            return None, None
        return float(temp), float(hum)

    return None, None


# =========================
# GAS DO SETUP
# =========================
gas = digitalio.DigitalInOut(GAS_PIN)
gas.direction = digitalio.Direction.INPUT


def gas_level_percent(samples: int = 20, delay: float = 0.02) -> int:
    """
    Digital 'level' estimate (0-100%) by sampling the DO pin.
    If inverted: True means "gas detected".
    """
    hits = 0
    for _ in range(samples):
        v = gas.value
        if INVERT_GAS_DO:
            v = not v
        if v:
            hits += 1
        time.sleep(delay)
    return int(round(100 * hits / samples))


# =========================
# BMP280 SETUP (via mux)
# =========================
i2c = busio.I2C(board.SCL, board.SDA)


def bmp_init():
    mux_select(BMP_CH)
    addrs = [BMP_ADDR] if BMP_ADDR is not None else [0x76, 0x77]
    last_err = None
    for addr in addrs:
        try:
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
            bmp.sea_level_pressure = 1013.25
            return bmp, addr
        except Exception as e:
            last_err = e
    return None, last_err


bmp, bmp_addr_or_err = bmp_init()


def read_bmp():
    """Returns (temp_c, pressure_hpa) or (None, None) if failed."""
    global bmp
    if bmp is None:
        return None, None
    try:
        mux_select(BMP_CH)
        return float(bmp.temperature), float(bmp.pressure)  # °C, hPa
    except Exception:
        return None, None


# =========================
# FORMATTING HELPERS
# =========================
def fmt_temp_c(t):
    return "--.-" if t is None else f"{t:0.1f}"

def fmt_hum(h):
    return "--" if h is None else f"{h:0.0f}"

def fmt_press_kpa(p_hpa):
    if p_hpa is None:
        return "---.-"
    return f"{(p_hpa / 10.0):0.1f}"  # hPa -> kPa

def ok_or_fail(v1, v2):
    return (v1 is not None) and (v2 is not None)


# =========================
# MAIN LOOP
# =========================
print("Exercise 13 running (Formatted Display -> LCD)... Ctrl+C to stop.")
lcd = lcd_init()

# Startup screen
lcd_write(lcd, "Exercise 13", "Display Output")
time.sleep(1.2)

# BMP quick status
if bmp is None:
    lcd_write(lcd, "BMP280: ERROR", "Check I2C/CH")
    time.sleep(1.2)

try:
    screens = ["DHT", "BMP", "GAS"]
    idx = 0

    while True:
        screen = screens[idx % len(screens)]
        idx += 1

        if screen == "DHT":
            t, h = read_dht()
            if ok_or_fail(t, h):
                line1 = f"DHT T:{fmt_temp_c(t)}C"
                line2 = f"Hum :{fmt_hum(h)}%"
            else:
                line1 = "DHT: NO DATA"
                line2 = "Check wiring"
            lcd_write(lcd, line1, line2)

        elif screen == "BMP":
            t, p = read_bmp()
            if ok_or_fail(t, p):
                line1 = f"BMP T:{fmt_temp_c(t)}C"
                line2 = f"P   :{fmt_press_kpa(p)}kPa"
            else:
                line1 = "BMP: NO DATA"
                line2 = "Check I2C/CH"
            lcd_write(lcd, line1, line2)

        elif screen == "GAS":
            level = gas_level_percent()
            status = "ALERT" if level >= GAS_ALERT_LEVEL else "OK"
            line1 = f"GAS: {status:<5}"
            line2 = f"Lvl: {level:>3d}%"
            lcd_write(lcd, line1, line2)

        time.sleep(SCREEN_S)

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    # cleanup
    try:
        lcd_write(lcd, "Stopped", "")
        time.sleep(0.8)
        mux_select(LCD_CH)
        lcd.clear()
    except Exception:
        pass

    try:
        gas.deinit()
    except Exception:
        pass

    if dht_mode == "adafruit_dht" and dht:
        try:
            dht.exit()
        except Exception:
            pass
