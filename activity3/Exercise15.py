# Activity 3 - Exercise 15: Communication Error (STRICT + LCD)
# GREEN = all required I2C devices are present
# RED   = ANY required device is missing
# LCD   = shows which sensor is missing

import time
from smbus2 import SMBus
import board
import digitalio
from RPLCD.i2c import CharLCD

# =========================
# SETTINGS (EDIT THESE)
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

# Your mux channels (SDx/SCx -> x)
LCD_CH = 0
BMP_CH = 2
MPU_CH = 1

# Expected I2C addresses per device
LCD_ADDRS = [0x27, 0x3F]
BMP_ADDRS = [0x76, 0x77]
MPU_ADDRS = [0x68, 0x69]

# LCD backpack address (must match the real LCD address on LCD_CH)
LCD_ADDR = 0x27      # change to 0x3F if yours is 0x3F
LCD_COLS = 16
LCD_ROWS = 2

RED_PIN   = board.D6
GREEN_PIN = board.D7

CHECK_EVERY_S = 1.0
# =========================


def mux_select(channel: int):
    if not (0 <= channel <= 7):
        raise ValueError("TCA9548A channel must be 0..7")
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)


def make_led(pin):
    led = digitalio.DigitalInOut(pin)
    led.direction = digitalio.Direction.OUTPUT
    led.value = False
    return led


def ack(addr: int) -> bool:
    """Return True if device ACKs (ping)."""
    try:
        with SMBus(I2C_BUS) as bus:
            bus.write_quick(addr)
        return True
    except Exception:
        return False


def any_addr_present(ch: int, addr_list):
    """Returns found address in list, else None."""
    mux_select(ch)
    for a in addr_list:
        if ack(a):
            return a
    return None


def show_ok(red, green):
    red.value = False
    green.value = True


def show_error(red, green):
    green.value = False
    red.value = True


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


def missing_to_lines(missing):
    """
    Fit missing sensor names into 16x2 lines.
    Examples:
      ["BMP280"] -> "MISSING:" / "BMP280"
      ["BMP280","MPU6050"] -> "MISS:BMP MPU" / " "
    """
    if not missing:
        return "I2C OK", "ALL PRESENT"

    # compact names
    short = []
    for m in missing:
        if m == "MPU6050":
            short.append("MPU")
        elif m == "BMP280":
            short.append("BMP")
        elif m == "LCD":
            short.append("LCD")
        else:
            short.append(m[:3].upper())

    # try to fit all on line2
    joined = " ".join(short)
    if len(joined) <= 16:
        return "I2C ERROR", f"MISS: {joined}"[:16]

    # otherwise split
    half = max(1, len(short)//2)
    l2 = " ".join(short[:half])
    l3 = " ".join(short[half:])

    return "I2C ERROR", (f"{l2}|{l3}")[:16]


print("Exercise 15 STRICT+LCD running... Ctrl+C to stop.")
print("Rule: GREEN only if ALL devices present. Remove ONE -> RED")

red = make_led(RED_PIN)
green = make_led(GREEN_PIN)

# Init LCD (continue even if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Exercise 15", "Starting...")
    time.sleep(0.8)
except Exception as e:
    print(f"[LCD] init failed (continuing without LCD): {e}")
    lcd = None

last_lcd = None

try:
    while True:
        # Check each required device on its channel
        lcd_found = any_addr_present(LCD_CH, LCD_ADDRS)
        bmp_found = any_addr_present(BMP_CH, BMP_ADDRS)
        mpu_found = any_addr_present(MPU_CH, MPU_ADDRS)

        missing = []
        if lcd_found is None:
            missing.append("LCD")
        if bmp_found is None:
            missing.append("BMP280")
        if mpu_found is None:
            missing.append("MPU6050")

        if not missing:
            show_ok(red, green)
            print(
                f"[OK] LCD=0x{lcd_found:02X} (CH{LCD_CH}), "
                f"BMP=0x{bmp_found:02X} (CH{BMP_CH}), "
                f"MPU=0x{mpu_found:02X} (CH{MPU_CH})"
            )
        else:
            show_error(red, green)
            print("[ERROR] Missing:", ", ".join(missing))

        # LCD update
        if lcd:
            l1, l2 = missing_to_lines(missing)
            if (l1, l2) != last_lcd:
                lcd_write(lcd, l1, l2)
                last_lcd = (l1, l2)

        time.sleep(CHECK_EVERY_S)

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    red.value = False
    green.value = False
    try: red.deinit()
    except Exception: pass
    try: green.deinit()
    except Exception: pass

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.7)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
