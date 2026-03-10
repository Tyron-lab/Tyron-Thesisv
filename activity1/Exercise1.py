import time
import signal
import sys
import os

import board
import digitalio

from smbus2 import SMBus
from RPLCD.i2c import CharLCD

print("╔════════════════════════════════════════════╗", file=sys.stderr)
print("║ Exercise 1 STARTED — PID: %-18s ║" % os.getpid(), file=sys.stderr)
print("╚════════════════════════════════════════════╝", file=sys.stderr)
sys.stderr.flush()

# CHANGE THESE IF NEEDED:
I2C_BUS  = 1
MUX_ADDR = 0x70
LCD_CH   = 0
LCD_ADDR = 0x27

LCD_COLS = 16
LCD_ROWS = 2

INVERT_PIR = True

_should_exit = False
def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True
    print("Received shutdown signal (SIGTERM/SIGINT)", file=sys.stderr)

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

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
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = bool(initial)
    print(f"  → {pin} OK", file=sys.stderr)
    return io

def make_in_pir(pin):
    print(f"Claiming input pin {pin} (PIR)...", file=sys.stderr)
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    try:
        io.pull = digitalio.Pull.DOWN
    except Exception:
        pass
    print(f"  → {pin} OK", file=sys.stderr)
    return io

# ─── PROTECTED GPIO INIT ────────────────────────────────────────
try:
    print("Initializing LEDs...", file=sys.stderr)
    R = make_out(board.D5, False)    # RED
    G = make_out(board.D6, False)    # GREEN
    O = make_out(board.D13, False)   # ORANGE

    print("Initializing PIR...", file=sys.stderr)
    pir = make_in_pir(board.D22)

except Exception as e:
    print("!!! CRITICAL ERROR: GPIO initialization failed !!!", file=sys.stderr)
    print(str(e), file=sys.stderr)
    print("Exercise 1 will exit now.", file=sys.stderr)
    sys.exit(1)

sys.stderr.flush()
# ──────────────────────────────────────────────────────────────────

print("PIR Motion Detection: warming up PIR (30s)...", file=sys.stderr)
all_off()
sys.stderr.flush()

# Rest of your code (LCD init, warmup loop, etc.) remains the same...