# Activity 3 - Exercise 14: Multiple I²C Devices
# Input: Data from different I²C sensors (BMP280 + MPU6050)
# What happens: Devices share the same I²C lines (via TCA9548A mux channels)
# Output: Correct data displayed on LCD (cycles screens)

import time
import math

# ---- I2C mux (TCA9548A) ----
from smbus2 import SMBus

# ---- LCD ----
from RPLCD.i2c import CharLCD

# ---- I2C devices ----
import board
import busio
import adafruit_bmp280
import adafruit_mpu6050


# =========================
# SETTINGS (EDIT THESE)
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

# LCD
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

# BMP280 (mux channel + addr)
BMP_CH   = 2
BMP_ADDR = None      # None -> try 0x76 then 0x77

# MPU6050 (mux channel + addr)
MPU_CH   = 1
MPU_ADDR = None      # None -> try 0x68 then 0x69

# screen timing
SCREEN_S = 2.5
# =========================


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


def init_bmp(i2c):
    mux_select(BMP_CH)
    addrs = [BMP_ADDR] if BMP_ADDR is not None else [0x76, 0x77]
    last = None
    for a in addrs:
        try:
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=a)
            bmp.sea_level_pressure = 1013.25
            return bmp, a
        except Exception as e:
            last = e
    raise RuntimeError(f"BMP280 not found at {addrs}. Last error: {last}")


def init_mpu(i2c):
    mux_select(MPU_CH)
    addrs = [MPU_ADDR] if MPU_ADDR is not None else [0x68, 0x69]
    last = None
    for a in addrs:
        try:
            mpu = adafruit_mpu6050.MPU6050(i2c, address=a)
            return mpu, a
        except Exception as e:
            last = e
    raise RuntimeError(f"MPU6050 not found at {addrs}. Last error: {last}")


def fmt_temp_c(t):
    return "--.-" if t is None else f"{t:0.1f}"

def fmt_kpa(p_hpa):
    return "---.-" if p_hpa is None else f"{(p_hpa/10.0):0.1f}"


def mag3(x, y, z):
    return math.sqrt(x*x + y*y + z*z)


print("Exercise 14 running (Multiple I2C Devices)... Ctrl+C to stop.")

# LCD
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ex14 I2C Multi", "Starting...")
except Exception as e:
    print(f"[LCD] init failed: {e}")
    lcd = None

# One I2C object shared (same SDA/SCL), mux selects downstream
i2c = busio.I2C(board.SCL, board.SDA)

# Init both sensors
try:
    bmp, bmp_addr = init_bmp(i2c)
    print(f"[BMP280] OK addr 0x{bmp_addr:02X} CH{BMP_CH}")
except Exception as e:
    bmp = None
    print(f"[BMP280] ERROR: {e}")

try:
    mpu, mpu_addr = init_mpu(i2c)
    print(f"[MPU6050] OK addr 0x{mpu_addr:02X} CH{MPU_CH}")
except Exception as e:
    mpu = None
    print(f"[MPU6050] ERROR: {e}")

if lcd:
    l1 = "BMP OK" if bmp else "BMP ERR"
    l2 = "MPU OK" if mpu else "MPU ERR"
    lcd_write(lcd, l1, l2)
    time.sleep(1.2)

try:
    while True:
        # ---- Screen 1: BMP280 ----
        if bmp:
            try:
                mux_select(BMP_CH)
                t_b = float(bmp.temperature)
                p_b = float(bmp.pressure)
                line1 = f"BMP T:{fmt_temp_c(t_b)}C"
                line2 = f"P  :{fmt_kpa(p_b)}kPa"
            except Exception as e:
                print(f"[BMP280] read error: {e}")
                line1, line2 = "BMP READ ERR", "Check wiring"
        else:
            line1, line2 = "BMP280 missing", "Check I2C"

        if lcd:
            lcd_write(lcd, line1, line2)
        time.sleep(SCREEN_S)

        # ---- Screen 2: MPU6050 ----
        if mpu:
            try:
                mux_select(MPU_CH)
                ax, ay, az = mpu.acceleration  # m/s^2
                gx, gy, gz = mpu.gyro          # rad/s -> convert
                gx *= 57.2958
                gy *= 57.2958
                gz *= 57.2958

                a_mag = mag3(ax, ay, az)
                g_mag = mag3(gx, gy, gz)

                # simple motion status (tune thresholds if needed)
                moving = (abs(a_mag - 9.81) > 1.2) or (g_mag > 25.0)
                status = "MOVING" if moving else "STILL"

                line1 = f"MPU: {status:<6}"
                line2 = f"A:{a_mag:>4.1f} G:{g_mag:>3.0f}"
            except Exception as e:
                print(f"[MPU6050] read error: {e}")
                line1, line2 = "MPU READ ERR", "Check wiring"
        else:
            line1, line2 = "MPU6050 missing", "Check I2C"

        if lcd:
            lcd_write(lcd, line1, line2)
        time.sleep(SCREEN_S)

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
