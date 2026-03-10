# Exercise 1: Motion Detection (PIR → Status LEDs) + LCD messages via TCA9548A
# LED RED    = D5   (MOTION DETECTED)
# LED GREEN  = D6   (NO MOTION)
# LED ORANGE = D13  (WARMUP / CALIBRATING)
# PIR INPUT  = D22

import time
import signal
import sys
import os
import traceback

import board
import digitalio

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

print("╔════════════════════════════════════════════╗", file=sys.stderr)
print(f"║ Exercise 1 STARTED — PID: {os.getpid():<18} ║", file=sys.stderr)
print("╚════════════════════════════════════════════╝", file=sys.stderr)
sys.stderr.flush()

# ─── CONFIG ────────────────────────────────────────────────
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2

INVERT_PIR = True

# ─── SIGNAL HANDLING ───────────────────────────────────────
_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True
    print("Received shutdown signal (SIGTERM/SIGINT)", file=sys.stderr)

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

# ─── HELPER FUNCTIONS ──────────────────────────────────────
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

def make_out(pin, initial=False):
    print(f"Claiming output pin {pin}...", file=sys.stderr)
    try:
        io = digitalio.DigitalInOut(pin)
        io.direction = digitalio.Direction.OUTPUT
        io.value = bool(initial)
        print(f"  → {pin} OK", file=sys.stderr)
        return io
    except Exception as e:
        print(f"  → Failed to claim {pin}: {e}", file=sys.stderr)
        raise

def make_in_pir(pin):
    print(f"Claiming input pin {pin} (PIR)...", file=sys.stderr)
    try:
        io = digitalio.DigitalInOut(pin)
        io.direction = digitalio.Direction.INPUT
        try:
            io.pull = digitalio.Pull.DOWN
        except Exception:
            pass
        print(f"  → {pin} OK", file=sys.stderr)
        return io
    except Exception as e:
        print(f"  → Failed to claim {pin}: {e}", file=sys.stderr)
        raise

def all_off():
    if 'R' in locals() and R: R.value = False
    if 'G' in locals() and G: G.value = False
    if 'O' in locals() and O: O.value = False

def show_detected():
    if 'R' in locals() and R: R.value = True
    if 'G' in locals() and G: G.value = False
    if 'O' in locals() and O: O.value = False

def show_no_motion():
    if 'R' in locals() and R: R.value = False
    if 'G' in locals() and G: G.value = True
    if 'O' in locals() and O: O.value = False

def read_motion() -> bool:
    if 'pir' not in locals() or pir is None:
        return False
    v = bool(pir.value)
    return (not v) if INVERT_PIR else v

# ─── MAIN GPIO INITIALIZATION (protected) ──────────────────
try:
    print("Initializing LEDs...", file=sys.stderr)
    R = make_out(board.D5, False)     # RED
    G = make_out(board.D6, False)     # GREEN
    O = make_out(board.D13, False)    # ORANGE

    print("Initializing PIR...", file=sys.stderr)
    pir = make_in_pir(board.D22)

except Exception as e:
    print("!!! CRITICAL ERROR: GPIO initialization failed !!!", file=sys.stderr)
    print(str(e), file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()
    sys.exit(1)

sys.stderr.flush()

# ─── PROGRAM START ─────────────────────────────────────────
print("PIR Motion Detection: warming up PIR (30s)...")
all_off()

# Init LCD (if it fails, keep running without LCD)
lcd = None
try:
    lcd = lcd_init()
    print("LCD initialized successfully", file=sys.stderr)
except Exception as e:
    print(f"[LCD] init failed, continuing without LCD: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    lcd = None

warmup_seconds = 30

if lcd:
    lcd_write(lcd, "Calibrating...", f"Wait {warmup_seconds}s")

# Warmup blink ORANGE
for sec_left in range(warmup_seconds, 0, -1):
    if _should_exit:
        print("Stopped (SIGTERM) during warmup.")
        break
    O.value = True
    time.sleep(0.5)
    O.value = False
    time.sleep(0.5)
    if lcd:
        lcd_write(lcd, "Calibrating...", f"Wait {sec_left-1}s")
    print(f"Warmup: {sec_left} seconds left", file=sys.stderr)   # ← debug
    sys.stderr.flush()

O.value = False

if _should_exit:
    print("Stopped during warmup.")
else:
    print("Monitoring motion... (Stop button to end)")

# ─── MAIN LOOP ─────────────────────────────────────────────
last_motion = None

try:
    show_no_motion()
    if lcd:
        lcd_write(lcd, "Ready", "No motion")

    while not _should_exit:
        motion = read_motion()

        if motion:
            show_detected()
        else:
            show_no_motion()

        if motion != last_motion:
            if motion:
                print("🚨 MOTION DETECTED")
                if lcd:
                    lcd_write(lcd, "Detected!", "Motion found")
            else:
                print("✅ NO MOTION")
                if lcd:
                    lcd_write(lcd, "Ready", "No motion")
            last_motion = motion

        time.sleep(0.05)

except Exception as e:
    print(f"❌ ERROR: {e}")
    traceback.print_exc(file=sys.stderr)
    all_off()
    if 'R' in locals() and R: R.value = True
    if lcd:
        try:
            lcd_write(lcd, "ERROR", str(e)[:16])
        except:
            pass
    time.sleep(1)

finally:
    try:
        if lcd:
            lcd_write(lcd, "Stopped", "")
            time.sleep(0.4)
            mux_select(LCD_CH)
            lcd.clear()
    except:
        pass

    all_off()
    try: 
        if 'pir' in locals() and pir: pir.deinit()
    except: pass
    try: 
        if 'R' in locals() and R: R.deinit()
    except: pass
    try: 
        if 'G' in locals() and G: G.deinit()
    except: pass
    try: 
        if 'O' in locals() and O: O.deinit()
    except: pass

    print("Exercise 1 exited cleanly.")
    sys.exit(0)