# Exercise 4: Distance Measurement (HC-SR04) using digitalio timing + Passive Buzzer + LCD via TCA9548A
# TRIG = board.D5, ECHO = board.D6
# Output: LCD shows distance; buzzer beeps when object is near

import time
import board
import digitalio

# ---- LCD via TCA9548A (same style as Exercise 2) ----
from smbus2 import SMBus
from RPLCD.i2c import CharLCD

# --- I2C / MUX / LCD settings (match your setup) ---
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

def mux_select(channel: int):
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)

def lcd_init():
    mux_select(LCD_CH)
    lcd = CharLCD(
        'PCF8574',
        address=LCD_ADDR,
        port=I2C_BUS,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        charmap='A00'
    )
    lcd.clear()
    return lcd

def lcd_write(lcd, line1: str, line2: str = ""):
    mux_select(LCD_CH)
    lcd.clear()
    lcd.write_string((line1 or "")[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string((line2 or "")[:LCD_COLS])

# ---- Ultrasonic pins (your working ones) ----
TRIG = digitalio.DigitalInOut(board.D5)
ECHO = digitalio.DigitalInOut(board.D6)
TRIG.direction = digitalio.Direction.OUTPUT
ECHO.direction = digitalio.Direction.INPUT
TRIG.value = False

# ---- Passive buzzer pin (pick a free one) ----
# D12 = GPIO12 (change to D13/D19/D26 if needed)
BUZZER_PIN = board.D16
buzzer = digitalio.DigitalInOut(BUZZER_PIN)
buzzer.direction = digitalio.Direction.OUTPUT

# If your buzzer module is active-low (beeps when pin is LOW), set this True.
# If it beeps when pin is HIGH, set this False.
BUZZER_ACTIVE_LOW = False

def buzzer_on():
    buzzer.value = (not BUZZER_ACTIVE_LOW)

def buzzer_off():
    buzzer.value = BUZZER_ACTIVE_LOW

buzzer_off()  # start silent

# ---- Behavior tuning ----
NEAR_CM = 20.0
VERY_NEAR_CM = 8.0

def measure_distance():
    # Trigger pulse (10µs)
    TRIG.value = True
    time.sleep(0.00001)
    TRIG.value = False

    # Wait for echo high
    pulse_start = time.time()
    timeout = pulse_start + 0.1  # 100ms timeout

    while (not ECHO.value) and time.time() < timeout:
        pulse_start = time.time()

    # Wait for echo low
    pulse_end = time.time()
    while ECHO.value and time.time() < timeout:
        pulse_end = time.time()

    # Timeout/no object
    if pulse_end - pulse_start > 0.1:
        return None

    duration = pulse_end - pulse_start
    distance_cm = duration * 17150  # cm/s / 2
    return round(distance_cm, 1)

def beep_once(on_s: float, off_s: float):
    buzzer_on()
    time.sleep(on_s)
    buzzer_off()
    time.sleep(off_s)

def beep_pattern(distance_cm: float):
    # Passive buzzer: simple ON/OFF beeps (works even without PWM)
    if distance_cm <= VERY_NEAR_CM:
        beep_once(0.06, 0.06)
    elif distance_cm <= NEAR_CM:
        beep_once(0.10, 0.18)
    else:
        buzzer_off()
        time.sleep(0.12)

print("Exercise 4 running (digitalio ultrasonic)... Ctrl+C to stop.")

# Init LCD
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "Ultrasonic", "Measuring...")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

last_display = None

try:
    while True:
        dist = measure_distance()

        if dist is None or not (2 <= dist <= 400):
            line1 = "Dist: ---"
            line2 = "Out of range"
            buzzer_off()
            time.sleep(0.2)
        else:
            line1 = f"Dist: {dist:>6.1f}cm"
            line2 = "NEAR! BEEP!" if dist <= NEAR_CM else "OK"
            beep_pattern(dist)

        # LCD update (reduce flicker)
        if lcd:
            display = (line1, line2)
            if display != last_display:
                lcd_write(lcd, line1, line2)
                last_display = display

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    # cleanup
    try:
        buzzer_off()
        buzzer.deinit()
    except Exception:
        pass

    try:
        TRIG.deinit()
        ECHO.deinit()
    except Exception:
        pass

    if lcd:
        try:
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
