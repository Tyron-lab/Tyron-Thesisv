# Activity 3 - Exercise 12: Motion Sensor Data (MPU6050 -> Motion Status)
# Input: MPU6050 movement data via I2C (through TCA9548A mux)
# What happens: reads accel/gyro and decides STILL vs MOVING
# Output: Motion status shown on LCD

import time
import math
import signal
import sys

# ---- I2C mux (TCA9548A) ----
from smbus2 import SMBus

# ---- LCD ----
from RPLCD.i2c import CharLCD

# ---- MPU6050 (Adafruit) ----
import board
import busio

try:
    import adafruit_mpu6050
    HAS_ADAFRUIT_MPU = True
except Exception:
    HAS_ADAFRUIT_MPU = False


# =========================
# SETTINGS
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

MPU_CH   = 1
MPU_ADDR = None

ACCEL_MOVING_MS2 = 1.2
GYRO_MOVING_DPS  = 25.0

REFRESH_S = 0.25
# =========================


# ─────────────────────────
# STOP SIGNAL HANDLING
# ─────────────────────────
_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)


# ─────────────────────────
# I2C BUS (OPEN ONCE)
# ─────────────────────────
bus = SMBus(I2C_BUS)

def mux_select(channel: int):
    if not (0 <= channel <= 7):
        raise ValueError("TCA9548A channel must be 0..7")
    bus.write_byte(MUX_ADDR, 1 << channel)


# ─────────────────────────
# LCD FUNCTIONS
# ─────────────────────────
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
    lcd.cursor_pos = (0,0)
    lcd.write_string(line1.ljust(LCD_COLS)[:LCD_COLS])
    lcd.cursor_pos = (1,0)
    lcd.write_string(line2.ljust(LCD_COLS)[:LCD_COLS])


# ─────────────────────────
# MPU INITIALIZATION
# ─────────────────────────
def mpu_init(i2c):

    if not HAS_ADAFRUIT_MPU:
        raise RuntimeError(
            "Missing library: adafruit_mpu6050\n"
            "Install with:\n"
            "pip install adafruit-circuitpython-mpu6050"
        )

    mux_select(MPU_CH)

    addrs = [MPU_ADDR] if MPU_ADDR is not None else [0x68, 0x69]
    last_err = None

    for addr in addrs:
        try:
            mpu = adafruit_mpu6050.MPU6050(i2c, address=addr)
            return mpu, addr
        except Exception as e:
            last_err = e

    raise RuntimeError(f"MPU6050 not found at {addrs}. Last error: {last_err}")


# ─────────────────────────
# MATH HELPERS
# ─────────────────────────
def accel_mag(ax, ay, az):
    return math.sqrt(ax*ax + ay*ay + az*az)


def gyro_mag(gx, gy, gz):
    return math.sqrt(gx*gx + gy*gy + gz*gz)


print("Exercise 12 running (MPU6050 -> Motion Status)... Ctrl+C to stop.")


# ─────────────────────────
# LCD INIT
# ─────────────────────────
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ex12 MPU6050", "Starting...")
except Exception as e:
    print(f"[LCD] init failed (continuing without LCD): {e}")
    lcd = None


# ─────────────────────────
# I2C OBJECT
# ─────────────────────────
i2c = busio.I2C(board.SCL, board.SDA)


# ─────────────────────────
# MPU INIT
# ─────────────────────────
try:

    mpu, used_addr = mpu_init(i2c)

    print(f"[MPU6050] OK at address 0x{used_addr:02X} on mux channel {MPU_CH}")

    if lcd:
        lcd_write(lcd, "MPU6050 OK", f"Addr 0x{used_addr:02X} CH{MPU_CH}")
        time.sleep(1.2)

except Exception as e:

    print(f"[MPU6050] init failed: {e}")

    if lcd:
        lcd_write(lcd, "MPU6050 ERROR", str(e)[:16])

    while not _should_exit:
        time.sleep(2)


# ─────────────────────────
# MAIN LOOP
# ─────────────────────────
last_display = None
moving_count = 0

try:

    while not _should_exit:

        try:

            mux_select(MPU_CH)

            ax, ay, az = mpu.acceleration
            gx, gy, gz = mpu.gyro

            gx_dps = gx * 57.2958
            gy_dps = gy * 57.2958
            gz_dps = gz * 57.2958

            a_mag = accel_mag(ax, ay, az)

            g = 9.81
            a_delta = abs(a_mag - g)

            g_mag = gyro_mag(gx_dps, gy_dps, gz_dps)

            moving = (a_delta > ACCEL_MOVING_MS2) or (g_mag > GYRO_MOVING_DPS)

            status = "MOVING" if moving else "STILL"

            if moving:
                moving_count += 1

            line1 = f"Motion: {status}"
            line2 = f"dA:{a_delta:>4.1f} g:{g_mag:>4.0f}"

            print(f"{status} | aΔ={a_delta:.2f} m/s2 | gyro={g_mag:.1f} dps | count={moving_count}")

        except Exception as e:

            line1 = "READ ERROR"
            line2 = "Check wiring"
            print(f"[MPU6050] read error: {e}")


        if lcd:
            display = (line1, line2)

            if display != last_display:
                lcd_write(lcd, line1, line2)
                last_display = display


        time.sleep(REFRESH_S)


except KeyboardInterrupt:
    print("\nStopped.")


# ─────────────────────────
# CLEANUP
# ─────────────────────────
finally:

    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass

    try:
        bus.close()
    except Exception:
        pass

    print("Exercise 12 exited cleanly.")

    sys.exit(0)