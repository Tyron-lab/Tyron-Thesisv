# Activity 3 - Exercise 15: Communication Error (STRICT + LCD)
# GREEN = all required I2C devices are present
# RED   = ANY required device is missing
# ORANGE = optional "checking" blink
# LCD   = shows which sensor is missing

import time
import signal
import sys
from smbus2 import SMBus
import board
import digitalio
from RPLCD.i2c import CharLCD

# =========================
# SETTINGS
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

LCD_CH = 0
BMP_CH = 2
MPU_CH = 1

LCD_ADDRS = [0x27, 0x3F]
BMP_ADDRS = [0x76, 0x77]
MPU_ADDRS = [0x68, 0x69]

LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# ✅ LEDs you demanded:
RED_PIN    = board.D5
GREEN_PIN  = board.D6
ORANGE_PIN = board.D13

CHECK_EVERY_S = 1.0
# =========================

# -------- stop handling --------
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
    time.sleep(0.02)

def make_led(pin, initial=False, name="LED"):
    try:
        led = digitalio.DigitalInOut(pin)
        led.direction = digitalio.Direction.OUTPUT
        led.value = bool(initial)
        return led
    except Exception as e:
        print(f"[GPIO] {name} on {pin} failed: {e}")
        print("➡️ This pin is BUSY. Close the other exercise/server using it, or reboot.")
        raise

def ack(addr: int) -> bool:
    try:
        with SMBus(I2C_BUS) as bus:
            bus.write_quick(addr)
        return True
    except Exception:
        return False

def any_addr_present(ch: int, addr_list):
    mux_select(ch)
    for a in addr_list:
        if ack(a):
            return a
    return None

def show_ok(red, green, orange):
    red.value = False
    orange.value = False
    green.value = True

def show_error(red, green, orange):
    green.value = False
    orange.value = False
    red.value = True

def show_checking(red, green, orange, blink_on: bool):
    # optional blink while checking
    green.value = False
    red.value = False
    orange.value = blink_on

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
    # faster/no flicker write
    l1 = (line1 or "").ljust(LCD_COLS)[:LCD_COLS]
    l2 = (line2 or "").ljust(LCD_COLS)[:LCD_COLS]
    lcd.cursor_pos = (0, 0)
    lcd.write_string(l1)
    lcd.cursor_pos = (1, 0)
    lcd.write_string(l2)

def missing_to_lines(missing):
    if not missing:
        return "I2C OK", "ALL PRESENT"

    short = []
    for m in missing:
        if m == "MPU6050": short.append("MPU")
        elif m == "BMP280": short.append("BMP")
        elif m == "LCD": short.append("LCD")
        else: short.append(m[:3].upper())

    joined = " ".join(short)
    if len(joined) <= 16:
        return "I2C ERROR", f"MISS: {joined}"[:16]

    half = max(1, len(short)//2)
    l2 = " ".join(short[:half])
    l3 = " ".join(short[half:])
    return "I2C ERROR", (f"{l2}|{l3}")[:16]

print("Exercise 15 STRICT+LCD running... Stop button / Ctrl+C to stop.")
print("Rule: GREEN only if ALL devices present. Remove ONE -> RED")

# ✅ LED init (can throw GPIO busy)
red = make_led(RED_PIN, False, "RED")
green = make_led(GREEN_PIN, False, "GREEN")
orange = make_led(ORANGE_PIN, False, "ORANGE")

# Init LCD (continue even if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Exercise 15", "Starting...")
    time.sleep(0.6)
except Exception as e:
    print(f"[LCD] init failed (continuing without LCD): {e}")
    lcd = None

last_lcd = None
blink = False

try:
    while not _should_exit:
        blink = not blink
        show_checking(red, green, orange, blink)

        lcd_found = any_addr_present(LCD_CH, LCD_ADDRS)
        bmp_found = any_addr_present(BMP_CH, BMP_ADDRS)
        mpu_found = any_addr_present(MPU_CH, MPU_ADDRS)

        missing = []
        if lcd_found is None: missing.append("LCD")
        if bmp_found is None: missing.append("BMP280")
        if mpu_found is None: missing.append("MPU6050")

        if not missing:
            show_ok(red, green, orange)
            print(
                f"[OK] LCD=0x{lcd_found:02X} (CH{LCD_CH}), "
                f"BMP=0x{bmp_found:02X} (CH{BMP_CH}), "
                f"MPU=0x{mpu_found:02X} (CH{MPU_CH})"
            )
        else:
            show_error(red, green, orange)
            print("[ERROR] Missing:", ", ".join(missing))

        if lcd:
            l1, l2 = missing_to_lines(missing)
            if (l1, l2) != last_lcd:
                lcd_write(lcd, l1, l2)
                last_lcd = (l1, l2)

        time.sleep(CHECK_EVERY_S)

except KeyboardInterrupt:
    pass

finally:
    for led in (red, green, orange):
        try:
            led.value = False
        except Exception:
            pass
        try:
            led.deinit()
        except Exception:
            pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.5)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    print("Exercise 15 exited cleanly.")
    sys.exit(0)