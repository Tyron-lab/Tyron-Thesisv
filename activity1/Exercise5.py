# Exercise 5: DHT11 Temperature & Humidity Alert System
# - Reads temperature and humidity from DHT11 (D4)
# - Displays on LCD via TCA9548A mux
# - If temperature goes HIGH:
#     -> LCD shows "TEMP ALERT!"
#     -> Buzzer beeps (D21, active-low)
#     -> All Relays ON (D27, D10, D26, D25, active-low)
# - When temperature returns to normal:
#     -> LCD shows normal reading
#     -> Buzzer OFF
#     -> All Relays OFF
#
# Pins:
#   DHT11   = D4
#   Buzzer  = D21 (active-low)
#   Relay   = D27, D10, D26, D25 (active-low)
#   LCD     = I2C via TCA9548A mux CH0, addr 0x27

import time
import signal
import sys

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

import board
import digitalio
import adafruit_dht

# ────────────────────────────────────────────────
# SETTINGS
# ────────────────────────────────────────────────
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

TEMP_ALERT_C  = 29.0   # Change this threshold (degrees C)
BEEP_INTERVAL = 2.0    # Beep every N seconds during alert

# ────────────────────────────────────────────────
# DHT11 (D4)
# ────────────────────────────────────────────────
dht = adafruit_dht.DHT11(board.D4)

# ────────────────────────────────────────────────
# BUZZER (active-low: False=ON, True=OFF)
# ────────────────────────────────────────────────
BUZZER_ACTIVE_LOW = True
buzzer = digitalio.DigitalInOut(board.D21)
buzzer.direction = digitalio.Direction.OUTPUT
buzzer.value = True  # OFF on start

def buzzer_set(on: bool):
    buzzer.value = (not on) if BUZZER_ACTIVE_LOW else bool(on)

def buzzer_off():
    buzzer.value = True if BUZZER_ACTIVE_LOW else False

def beep(count=2, on_ms=150, off_ms=100):
    for _ in range(count):
        buzzer_set(True)
        time.sleep(on_ms / 1000.0)
        buzzer_set(False)
        time.sleep(off_ms / 1000.0)

# ────────────────────────────────────────────────
# RELAY (active-low: True=OFF, False=ON)
# ────────────────────────────────────────────────
RELAY_ACTIVE_LOW = True
RELAY_PIN_LIST   = [board.D27, board.D10, board.D26, board.D25]

relay_ios = []
for _pin in RELAY_PIN_LIST:
    _io = digitalio.DigitalInOut(_pin)
    _io.direction = digitalio.Direction.OUTPUT
    _io.value = True  # OFF on start
    relay_ios.append(_io)

def all_relays_on():
    for io in relay_ios:
        io.value = False if RELAY_ACTIVE_LOW else True

def all_relays_off():
    for io in relay_ios:
        io.value = True if RELAY_ACTIVE_LOW else False

# ────────────────────────────────────────────────
# LCD via TCA9548A
# ────────────────────────────────────────────────
def mux_select(channel: int):
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDR, 1 << channel)
    time.sleep(0.03)

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
    l1 = (line1 or "").ljust(LCD_COLS)[:LCD_COLS]
    l2 = (line2 or "").ljust(LCD_COLS)[:LCD_COLS]
    lcd.cursor_pos = (0, 0)
    lcd.write_string(l1)
    lcd.cursor_pos = (1, 0)
    lcd.write_string(l2)

# ────────────────────────────────────────────────
# STOP HANDLING
# ────────────────────────────────────────────────
_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT,  _handle_term)

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
print("Exercise 5: DHT11 Temperature Alert System")
print(f"  Alert threshold : {TEMP_ALERT_C}C")
print(f"  DHT11 pin       : D4")
print(f"  Buzzer pin      : D21 (active-low)")
print(f"  Relay pins      : D27, D10, D26, D25 (active-low)")
print("Stop: Stop button or Ctrl+C")

# Init LCD
lcd = None
try:
    lcd = lcd_init()
    lcd_write(lcd, "DHT11 Ready", "Initializing...")
    print("[LCD] OK")
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}")
    lcd = None

alert_active = False
beep_timer   = 0.0
last_display = ("", "")

try:
    while not _should_exit:
        temp     = None
        humidity = None

        # DHT11 read
        try:
            temp     = dht.temperature
            humidity = dht.humidity
        except Exception as e:
            print(f"[DHT11] read error: {e}")
            time.sleep(1.0)
            continue

        if temp is None or humidity is None:
            time.sleep(1.0)
            continue

        now     = time.time()
        is_high = temp >= TEMP_ALERT_C

        if is_high:
            # ALERT STATE
            if not alert_active:
                alert_active = True
                all_relays_on()
                print(f"[ALERT] Temp HIGH: {temp}C >= {TEMP_ALERT_C}C -> Relays ON")

            line1 = "!! TEMP ALERT !!"
            line2 = f"T:{temp:.1f}C H:{humidity:.0f}%"

            # Beep every BEEP_INTERVAL seconds
            if now - beep_timer >= BEEP_INTERVAL:
                beep(count=2, on_ms=150, off_ms=100)
                beep_timer = now

        else:
            # NORMAL STATE
            if alert_active:
                alert_active = False
                all_relays_off()
                buzzer_off()
                print(f"[NORMAL] Temp OK: {temp}C < {TEMP_ALERT_C}C -> Relays OFF")

            line1 = f"Temp: {temp:.1f} C"
            line2 = f"Humi: {humidity:.0f} %"

        print(f"T={temp:.1f}C  H={humidity:.0f}%  {'ALERT' if is_high else 'OK'}")

        # Update LCD only if changed (reduce flicker)
        if lcd and (line1, line2) != last_display:
            try:
                lcd_write(lcd, line1, line2)
                last_display = (line1, line2)
            except Exception as e:
                print(f"[LCD] write error: {e}")

        time.sleep(1.0)

finally:
    try:
        buzzer_off()
        buzzer.deinit()
    except Exception:
        pass
    try:
        all_relays_off()
        for io in relay_ios:
            io.deinit()
    except Exception:
        pass
    try:
        dht.exit()
    except Exception:
        pass
    if lcd:
        try:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.4)
            mux_select(LCD_CH)
            lcd.clear()
        except Exception:
            pass
    print("Exercise 5 exited cleanly.")
    sys.exit(0)