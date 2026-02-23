# Activity 3 - Exercise 12: Motion Sensor Data (MPU6050 -> Motion Status)
# Input: MPU6050 movement data via I2C (through TCA9548A mux)
# What happens: reads accel/gyro and decides STILL vs MOVING
# Output: Motion status shown on LCD

import time
import math

# ---- I2C mux (TCA9548A) ----
from smbus2 import SMBus

# ---- LCD ----
from RPLCD.i2c import CharLCD

# ---- MPU6050 (Adafruit) ----
import board
import busio

try:
    import adafruit_mpu6050 # python3 -m pip install adafruit-circuitpython-mpu6050
    
    HAS_ADAFRUIT_MPU = True
except Exception:
    HAS_ADAFRUIT_MPU = False


# =========================
# SETTINGS (EDIT THESE)
# =========================
I2C_BUS  = 1
MUX_ADDR = 0x70

# LCD mux channel + address
LCD_CH   = 0
LCD_ADDR = 0x27     # common: 0x27 or 0x3F
LCD_COLS = 16
LCD_ROWS = 2

# MPU6050 mux channel
MPU_CH   = 1        # <-- CHANGE: SDx/SCx -> x (where MPU6050 is plugged)

# MPU6050 I2C address (common: 0x68; if AD0 pulled HIGH then 0x69)
# If not sure, leave None and it will auto-try 0x68 then 0x69
MPU_ADDR = None

# Motion thresholds (tune to your liking)
ACCEL_MOVING_MS2 = 1.2     # moving if | |a|-g | > this (m/s^2)
GYRO_MOVING_DPS  = 25.0    # moving if gyro magnitude > this (deg/s)

# Display refresh
REFRESH_S = 0.25
# =========================


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


def mpu_init(i2c):
    if not HAS_ADAFRUIT_MPU:
        raise RuntimeError("Missing library: adafruit_mpu6050. Install it: pip install adafruit-circuitpython-mpu6050")

    mux_select(MPU_CH)
    addrs = [MPU_ADDR] if MPU_ADDR is not None else [0x68, 0x69]
    last_err = None

    for addr in addrs:
        try:
            mpu = adafruit_mpu6050.MPU6050(i2c, address=addr)
            # Optional: you can change ranges, but defaults are fine
            # mpu.accelerometer_range = adafruit_mpu6050.Range.RANGE_8_G
            # mpu.gyro_range = adafruit_mpu6050.GyroRange.RANGE_500_DPS
            return mpu, addr
        except Exception as e:
            last_err = e

    raise RuntimeError(f"MPU6050 not found at {addrs}. Last error: {last_err}")


def accel_mag(ax, ay, az):
    return math.sqrt(ax*ax + ay*ay + az*az)


def gyro_mag(gx, gy, gz):
    return math.sqrt(gx*gx + gy*gy + gz*gz)


print("Exercise 12 running (MPU6050 -> Motion Status)... Ctrl+C to stop.")

# Init LCD (continue even if LCD fails)
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ex12 MPU6050", "Starting...")
except Exception as e:
    print(f"[LCD] init failed (continuing without LCD): {e}")
    lcd = None

# Create I2C object once
i2c = busio.I2C(board.SCL, board.SDA)

# Init MPU6050
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
    while True:
        time.sleep(2)

# Main loop
last_display = None
moving_count = 0

try:
    while True:
        try:
            # Always select the MPU channel before reading
            mux_select(MPU_CH)

            # adafruit_mpu6050 returns:
            # acceleration in m/s^2, gyro in rad/s (depending on version) OR deg/s in some libs.
            # For adafruit_mpu6050: gyro is in rad/s. We'll convert to deg/s.
            ax, ay, az = mpu.acceleration  # m/s^2
            gx, gy, gz = mpu.gyro          # rad/s

            # Convert gyro rad/s -> deg/s
            gx_dps = gx * 57.2958
            gy_dps = gy * 57.2958
            gz_dps = gz * 57.2958

            a_mag = accel_mag(ax, ay, az)
            g = 9.81
            a_delta = abs(a_mag - g)              # how far from 1g
            g_mag = gyro_mag(gx_dps, gy_dps, gz_dps)

            moving = (a_delta > ACCEL_MOVING_MS2) or (g_mag > GYRO_MOVING_DPS)
            status = "MOVING" if moving else "STILL"

            if moving:
                moving_count += 1

            line1 = f"Motion: {status}"
            # show a quick hint value so you can tune thresholds
            # keep within 16 chars
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
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.8)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
