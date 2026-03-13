# activity5/Exercise24.py
# Exercise 24: Terminal / Actuator Event Logger
#
# Pins:
#   Buzzer  : board.D21  (active-low)
#   LEDs    : R=board.D5, O=board.D13, G=board.D6
#   Relays  : board.D27, board.D10, board.D26, board.D25  (active-low)
#   Servo   : board.D12  (PWM, standard servo)
#
# Commands received via ex24_cmd.json (written by Flask /api/a5/command):
#   { action:"buzzer",  state:"on"|"off" }
#   { action:"led",     color:"red"|"orange"|"green"|"off" }
#   { action:"servo",   angle:0..180 }
#   { action:"servo",   state:"stop" }       ← NEW: stop / release servo
#   { action:"relay",   ch:1..4|"all", state:"on"|"off" }   ← ALL fixed
#   { action:"stop" }                        ← all off

import os
import sys
import time
import json
import signal
import threading
from datetime import datetime

import board
import digitalio
import pwmio

# ─────────────────────────────
# PINS
# ─────────────────────────────
BUZZER_PIN  = board.D21
LED_R_PIN   = board.D5
LED_O_PIN   = board.D13
LED_G_PIN   = board.D6
SERVO_PIN   = board.D12
RELAY_PINS  = [board.D27, board.D10, board.D26, board.D25]

# ─────────────────────────────
# ACTIVE LEVELS
# ─────────────────────────────
BUZZER_ACTIVE_LOW = True
LED_ACTIVE_HIGH   = True
RELAY_ACTIVE_LOW  = True   # set False if your relay board is active-high

# ─────────────────────────────
# SERVO CONFIG (standard 50Hz servo)
# ─────────────────────────────
SERVO_FREQ   = 50       # Hz
SERVO_MIN_US = 500      # µs pulse = 0°
SERVO_MAX_US = 2500     # µs pulse = 180°

def angle_to_duty(angle_deg):
    angle_deg  = max(0.0, min(180.0, float(angle_deg)))
    period_us  = 1_000_000 / SERVO_FREQ
    pulse_us   = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * (angle_deg / 180.0)
    return int((pulse_us / period_us) * 65535)

# ─────────────────────────────
# LOG FILES
# ─────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR  = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_TXT   = os.path.join(LOG_DIR, "ex24_terminal.log")
LOG_JSONL = os.path.join(LOG_DIR, "ex24_events.jsonl")

running = True
_lock   = threading.Lock()

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def log_event(level, message, **extra):
    rec  = {"ts": now_iso(), "level": level, "message": message, **(extra or {})}
    line = f'[{rec["ts"]}] {level}: {message}'
    try:
        with open(LOG_TXT,   "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass
    try:
        with open(LOG_JSONL, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
    except Exception: pass
    print(line, flush=True)

def make_output(pin):
    d = digitalio.DigitalInOut(pin)
    d.direction = digitalio.Direction.OUTPUT
    return d

def set_output(dev, on, active_high=True):
    dev.value = bool(on) if active_high else not bool(on)

def buzzer_on(buz):
    buz.value = (not BUZZER_ACTIVE_LOW)

def buzzer_off(buz):
    buz.value = BUZZER_ACTIVE_LOW

def beep(buz, duration=0.12):
    buzzer_on(buz); time.sleep(duration); buzzer_off(buz)

def relay_active_high():
    return not RELAY_ACTIVE_LOW

def safe_off_all(led_r, led_o, led_g, buz, relays, servo_pwm):
    set_output(led_r, False, LED_ACTIVE_HIGH)
    set_output(led_o, False, LED_ACTIVE_HIGH)
    set_output(led_g, False, LED_ACTIVE_HIGH)
    buzzer_off(buz)
    for r in relays:
        set_output(r, False, relay_active_high())
    if servo_pwm:
        try: servo_pwm.duty_cycle = 0
        except Exception: pass

# ─────────────────────────────
# RELAY HELPER  (handles ch int OR "all")
# ─────────────────────────────
def relay_set(relays, ch, on):
    ah = relay_active_high()
    ch_norm = str(ch).strip().lower()
    if ch_norm == "all":
        for r in relays:
            set_output(r, on, ah)
        log_event("EVENT", f"Relay ALL {'ON' if on else 'OFF'}")
    else:
        try:
            idx = int(ch_norm) - 1   # 1-based → 0-based
            if 0 <= idx < len(relays):
                set_output(relays[idx], on, ah)
                log_event("EVENT", f"Relay CH{idx+1} {'ON' if on else 'OFF'}")
            else:
                log_event("WARN", f"Relay channel {ch} out of range (1-{len(relays)})")
        except (ValueError, TypeError):
            log_event("WARN", f"Relay bad channel value: {ch!r}")

# ─────────────────────────────
# COMMAND DISPATCH
# ─────────────────────────────
def dispatch(cmd, led_r, led_o, led_g, buz, relays, servo_pwm):
    action = str(cmd.get("action", "")).lower()

    # BUZZER
    if action == "buzzer":
        state = str(cmd.get("state", "off")).lower()
        if state == "on":
            buzzer_on(buz);  log_event("EVENT", "Buzzer ON");  return True, "Buzzer ON"
        else:
            buzzer_off(buz); log_event("EVENT", "Buzzer OFF"); return True, "Buzzer OFF"

    # LED
    elif action == "led":
        color = str(cmd.get("color", "off")).lower()
        set_output(led_r, False, LED_ACTIVE_HIGH)
        set_output(led_o, False, LED_ACTIVE_HIGH)
        set_output(led_g, False, LED_ACTIVE_HIGH)
        if   color == "red":    set_output(led_r, True, LED_ACTIVE_HIGH)
        elif color == "orange": set_output(led_o, True, LED_ACTIVE_HIGH)
        elif color == "green":  set_output(led_g, True, LED_ACTIVE_HIGH)
        log_event("EVENT", f"LED {color.upper()}")
        return True, f"LED {color}"

    # SERVO
    elif action == "servo":
        if not servo_pwm:
            return False, "Servo PWM unavailable"
        state = str(cmd.get("state", "")).lower()
        if state == "stop":
            servo_pwm.duty_cycle = 0           # no pulse → motor released
            log_event("EVENT", "Servo STOP (pulse off)")
            return True, "Servo STOP"
        try:
            angle = float(cmd.get("angle", 0))
        except (TypeError, ValueError):
            return False, "Invalid servo angle"
        servo_pwm.duty_cycle = angle_to_duty(angle)
        log_event("EVENT", f"Servo {angle:.0f}°")
        return True, f"Servo {angle:.0f}°"

    # RELAY
    elif action == "relay":
        ch    = cmd.get("ch", 1)
        state = str(cmd.get("state", "off")).lower()
        relay_set(relays, ch, state == "on")
        return True, f"Relay {ch} {'ON' if state=='on' else 'OFF'}"

    # STOP ALL
    elif action == "stop":
        safe_off_all(led_r, led_o, led_g, buz, relays, servo_pwm)
        log_event("EVENT", "STOP ALL")
        return True, "All off"

    else:
        log_event("WARN", f"Unknown action: {action!r}")
        return False, f"Unknown action: {action}"

# ─────────────────────────────
# COMMAND FILE WATCHER (polls ex24_cmd.json)
# ─────────────────────────────
CMD_FILE = os.path.join(BASE_DIR, "ex24_cmd.json")

def watch_commands(led_r, led_o, led_g, buz, relays, servo_pwm):
    last_mtime = 0
    while running:
        try:
            if os.path.exists(CMD_FILE):
                mtime = os.path.getmtime(CMD_FILE)
                if mtime != last_mtime:
                    last_mtime = mtime
                    with open(CMD_FILE, "r", encoding="utf-8") as f:
                        cmd = json.load(f)
                    with _lock:
                        ok, msg = dispatch(cmd, led_r, led_o, led_g, buz, relays, servo_pwm)
                    if not ok:
                        log_event("ERROR", f"Command failed: {msg}", cmd=cmd)
        except Exception as exc:
            log_event("ERROR", f"watch_commands: {exc}")
        time.sleep(0.08)

# ─────────────────────────────
# SHUTDOWN
# ─────────────────────────────
def shutdown(sig=None, frame=None):
    global running
    running = False

# ─────────────────────────────
# MAIN
# ─────────────────────────────
def main():
    global running
    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    led_r  = make_output(LED_R_PIN)
    led_o  = make_output(LED_O_PIN)
    led_g  = make_output(LED_G_PIN)
    buz    = make_output(BUZZER_PIN)
    relays = [make_output(p) for p in RELAY_PINS]

    servo_pwm = None
    try:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, frequency=SERVO_FREQ, variable_frequency=False)
        servo_pwm.duty_cycle = 0
        log_event("INFO", "Servo PWM ready on D12")
    except Exception as exc:
        log_event("WARN", f"Servo PWM init failed (servo disabled): {exc}")

    safe_off_all(led_r, led_o, led_g, buz, relays, servo_pwm)

    log_event("INFO", "Exercise 24 started", pins={
        "buzzer": "D21", "led_r": "D5", "led_o": "D13", "led_g": "D6",
        "servo":  "D12 (PWM)", "relays": ["D27","D10","D26","D25"]
    })

    beep(buz, 0.08)

    t = threading.Thread(
        target=watch_commands,
        args=(led_r, led_o, led_g, buz, relays, servo_pwm),
        daemon=True
    )
    t.start()

    step = 0
    try:
        while running:
            step += 1
            if step % 30 == 0:
                log_event("INFO", f"Heartbeat step={step}")
            time.sleep(1.0)
    finally:
        log_event("INFO", "Exercise 24 stopping — cleanup")
        safe_off_all(led_r, led_o, led_g, buz, relays, servo_pwm)
        for dev in [led_r, led_o, led_g, buz, *relays]:
            try: dev.deinit()
            except Exception: pass
        if servo_pwm:
            try: servo_pwm.deinit()
            except Exception: pass
        log_event("INFO", "Exercise 24 stopped")

if __name__ == "__main__":
    main()