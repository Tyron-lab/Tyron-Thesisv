# activity5/Exercise24.py
# Exercise 24: Terminal / Actuator Event Logger (digitalio ONLY)
#
# Uses ONLY:
#   import board
#   import digitalio
#
# Pins:
#   Buzzer  : board.D21  (active-low default below)
#   LEDs    : R=board.D5, O=board.D13, G=board.D6
#   Relays  : board.D27, board.D10, board.D26, board.D25
#
# NOTE: Servo is NOT supported with digitalio-only.
#       If you want servo on D12, you must use pwmio + adafruit_motor.servo or pigpio.

import os
import time
import json
import signal
from datetime import datetime

import board
import digitalio

# ─────────────────────────────
# PINS
# ─────────────────────────────
BUZZER_PIN = board.D21

LED_R_PIN = board.D5
LED_O_PIN = board.D13
LED_G_PIN = board.D6

RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]

# ─────────────────────────────
# ACTIVE LEVELS (adjust if needed)
# ─────────────────────────────
BUZZER_ACTIVE_LOW = True      # common buzzer modules are active-low
LED_ACTIVE_HIGH   = True
RELAY_ACTIVE_HIGH = True      # set False if your relay board is active-low

STEP_SEC = 1.0

# ─────────────────────────────
# LOG FILES
# ─────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_TXT   = os.path.join(LOG_DIR, "ex24_terminal.log")
LOG_JSONL = os.path.join(LOG_DIR, "ex24_events.jsonl")

running = True

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def log_event(level: str, message: str, **extra):
    rec = {"ts": now_iso(), "level": level, "message": message, **(extra or {})}
    line = f'[{rec["ts"]}] {level}: {message}'

    try:
        with open(LOG_TXT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

    try:
        with open(LOG_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

    print(line, flush=True)

def make_output(pin):
    d = digitalio.DigitalInOut(pin)
    d.direction = digitalio.Direction.OUTPUT
    return d

def set_output(dev, on: bool, active_high: bool = True):
    if active_high:
        dev.value = bool(on)
    else:
        dev.value = not bool(on)

def buzzer_on(buzzer):
    buzzer.value = False if BUZZER_ACTIVE_LOW else True

def buzzer_off(buzzer):
    buzzer.value = True if BUZZER_ACTIVE_LOW else False

def beep(buzzer, duration=0.12):
    buzzer_on(buzzer)
    time.sleep(duration)
    buzzer_off(buzzer)

def safe_off_all(led_r, led_o, led_g, buzzer, relays):
    set_output(led_r, False, LED_ACTIVE_HIGH)
    set_output(led_o, False, LED_ACTIVE_HIGH)
    set_output(led_g, False, LED_ACTIVE_HIGH)
    buzzer_off(buzzer)
    for r in relays:
        set_output(r, False, RELAY_ACTIVE_HIGH)

def shutdown(sig=None, frame=None):
    global running
    running = False

def main():
    global running
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    led_r = make_output(LED_R_PIN)
    led_o = make_output(LED_O_PIN)
    led_g = make_output(LED_G_PIN)
    buzzer = make_output(BUZZER_PIN)
    relays = [make_output(p) for p in RELAY_PINS]

    safe_off_all(led_r, led_o, led_g, buzzer, relays)

    log_event("INFO", "Exercise 24 started (digitalio only)", pins={
        "buzzer": "D21",
        "led_r": "D5",
        "led_o": "D13",
        "led_g": "D6",
        "relays": ["D27", "D10", "D26", "D25"],
        "servo": "NOT SUPPORTED (needs PWM)"
    })

    beep(buzzer, 0.08)

    step = 0
    relay_idx = 0

    try:
        while running:
            step += 1

            # LEDs: R -> O -> G cycle
            r_on = (step % 3 == 1)
            o_on = (step % 3 == 2)
            g_on = (step % 3 == 0)

            set_output(led_r, r_on, LED_ACTIVE_HIGH)
            set_output(led_o, o_on, LED_ACTIVE_HIGH)
            set_output(led_g, g_on, LED_ACTIVE_HIGH)

            log_event("EVENT", "LED cycle", r=r_on, o=o_on, g=g_on)

            # Relays: one at a time
            for i, rr in enumerate(relays):
                set_output(rr, i == relay_idx, RELAY_ACTIVE_HIGH)

            log_event("EVENT", "Relay toggle", active_index=relay_idx)
            relay_idx = (relay_idx + 1) % len(relays)

            # Beep each cycle
            beep(buzzer, 0.06)
            log_event("EVENT", "Buzzer beep")

            time.sleep(STEP_SEC)

    finally:
        log_event("INFO", "Stopping Exercise 24 (cleanup)")
        safe_off_all(led_r, led_o, led_g, buzzer, relays)

        for dev in [led_r, led_o, led_g, buzzer, *relays]:
            try:
                dev.deinit()
            except Exception:
                pass

        log_event("INFO", "Exercise 24 stopped")

if __name__ == "__main__":
    main()