import time
import sys
import signal

import board
import digitalio

BUZZER_PIN = board.D16

# ✅ KEEP THIS TRUE FIRST (so it will NEVER beep)
MUTE = True

# ✅ ACTIVE BUZZER modules are VERY OFTEN active-low:
#    beep when input LOW, silent when input HIGH
ACTIVE_LOW = True

_should_exit = False
def _term(sig, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _term)
signal.signal(signal.SIGINT, _term)

buzzer = digitalio.DigitalInOut(BUZZER_PIN)
buzzer.direction = digitalio.Direction.OUTPUT

def buzzer_write(on: bool):
    # active-low: ON=LOW, OFF=HIGH
    if ACTIVE_LOW:
        buzzer.value = (not on)
    else:
        buzzer.value = bool(on)

def buzzer_off_hard():
    # Force OFF level strongly
    buzzer_write(False)
    time.sleep(0.05)
    buzzer_write(False)

# ✅ force silent immediately
buzzer_off_hard()

print("BUZZER: forced silent.")
print("If it's still beeping now, the module is wired to 5V/GND wrong or not controlled by this pin.")
print("Running... (Ctrl+C to exit)")

try:
    while not _should_exit:
        # stay silent
        buzzer_off_hard()

        # if you later set MUTE=False, it will beep once per second
        if not MUTE:
            buzzer_write(True)
            time.sleep(0.15)
            buzzer_write(False)
            time.sleep(0.85)
        else:
            time.sleep(0.3)

finally:
    # ensure silent
    try:
        buzzer_off_hard()
        buzzer.deinit()
    except Exception:
        pass
    sys.exit(0)