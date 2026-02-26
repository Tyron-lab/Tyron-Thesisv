# activity5/Exercise22.py
# Exercise 22: Receive Command (MQTT Subscribe -> Control outputs)
#
# Subscribes to: trainerkit/a5/command
#
# Supported payload examples:
#   {"device":"relay","ch":1,"state":"on"}
#   {"device":"relay","ch":2,"state":"off"}
#   {"device":"relay_seq","mode":"chase","repeat":2,"delay_ms":250}
#
#   {"device":"led","color":"red","state":"on"}
#   {"device":"led_seq","mode":"traffic","repeat":2,"delay_ms":220}
#
#   {"device":"servo","action":"open"}                 # uses SERVO_MODE
#   {"device":"servo","action":"close"}                # uses SERVO_MODE
#   {"device":"servo","action":"stop"}                 # continuous stop
#   {"device":"servo","angle":90}                      # positional only
#
#   {"device":"beep","count":2}
#   {"device":"all_off"}
#
# Stop: Ctrl+C or your dashboard Stop button (terminates process)

import json
import time
import signal
import sys
import threading

import paho.mqtt.client as mqtt

# --- Conditional GPIO imports (so it doesn't crash on non-Pi machines)
SENSORS_AVAILABLE = {"board": False, "digitalio": False, "pwmio": False}
try:
    import board
    import digitalio
    SENSORS_AVAILABLE["board"] = True
    SENSORS_AVAILABLE["digitalio"] = True
except Exception:
    pass

try:
    import pwmio
    SENSORS_AVAILABLE["pwmio"] = True
except Exception:
    pass


# ==========================
# MQTT SETTINGS (match server.py)
# ==========================
MQTT_HOST = "192.168.4.1"
MQTT_PORT = 1883
TOPIC_CMD = "trainerkit/a5/command"
CLIENT_ID = "trainerkit_pi_ex22"


# ==========================
# OUTPUT PINS (edit if needed)
# ==========================
# Relay channels (active-low like your server.py init_relay)
# Add more channels if you really have them wired, like 5: board.Dxx, etc.
RELAY_PINS = {
    1: getattr(board, "D27", None),
    2: getattr(board, "D10", None),
    3: getattr(board, "D26", None),
    4: getattr(board, "D25", None),
}

# LED pins
LED_PINS = {
    "red":    getattr(board, "D5", None),
    "orange": getattr(board, "D6", None),
    "green":  getattr(board, "D13", None),
}

# Servo pin
SERVO_PIN = getattr(board, "D12", None)
SERVO_FREQ = 50

# IMPORTANT: choose servo type
# - "positional" = normal 0..180 servo (angle control)
# - "continuous" = 360/continuous rotation servo (speed + stop control)
SERVO_MODE = "continuous"  # <-- change to "positional" if you have normal servo

# PWM pulse calibration (these matter a LOT for continuous servos)
# Positional typical: 500..2500us
# Continuous typical: stop ~1500us, forward <1500, reverse >1500 (or vice versa)
MIN_PULSE_US = 500
MAX_PULSE_US = 2500

# Continuous servo tuning:
SERVO_STOP_US = 1500     # neutral/stop pulse
SERVO_OPEN_US = 1300     # one direction (tune!)
SERVO_CLOSE_US = 1700    # opposite direction (tune!)
SERVO_RUN_SECONDS = 1.2  # how long to rotate for open/close before stopping

# Optional buzzer
BUZZER_PIN = getattr(board, "D16", None)
BUZZER_ACTIVE_LOW = False  # set True if your buzzer is active-low


# ==========================
# GLOBAL STATE
# ==========================
running = True

relay_ios = {}
led_ios = {}
servo_pwm = None
buzzer_io = None

# lock so sequences don't overlap and fight outputs
seq_lock = threading.Lock()


def log(*args):
    print("[EX22]", *args, flush=True)


def safe_deinit(io):
    try:
        if io is not None:
            io.deinit()
    except Exception:
        pass


def gpio_ready():
    return SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("digitalio")


def init_relays():
    if not gpio_ready():
        return False
    for ch, pin in RELAY_PINS.items():
        if pin is None:
            continue
        if ch not in relay_ios:
            io = digitalio.DigitalInOut(pin)
            io.direction = digitalio.Direction.OUTPUT
            io.value = True  # active-low OFF
            relay_ios[ch] = io
    return True


def set_relay(ch: int, on: bool):
    if not init_relays():
        log("GPIO not available -> relay ignored")
        return False
    io = relay_ios.get(int(ch))
    if io is None:
        log(f"Relay CH{ch} pin not configured")
        return False
    # active-low: ON = False, OFF = True
    io.value = (not bool(on))
    log(f"Relay CH{ch} -> {'ON' if on else 'OFF'}")
    return True


def all_relays_off():
    if not init_relays():
        return
    for ch in sorted(relay_ios.keys()):
        try:
            relay_ios[ch].value = True
        except Exception:
            pass


def init_leds():
    if not gpio_ready():
        return False
    for color, pin in LED_PINS.items():
        if pin is None:
            continue
        if color not in led_ios:
            io = digitalio.DigitalInOut(pin)
            io.direction = digitalio.Direction.OUTPUT
            io.value = False
            led_ios[color] = io
    return True


def set_led(color: str, on: bool):
    color = (color or "").lower()
    if not init_leds():
        log("GPIO not available -> led ignored")
        return False
    io = led_ios.get(color)
    if io is None:
        log(f"LED color '{color}' not configured")
        return False
    io.value = bool(on)
    log(f"LED {color} -> {'ON' if on else 'OFF'}")
    return True


def all_leds_off():
    if not init_leds():
        return
    for c in led_ios:
        try:
            led_ios[c].value = False
        except Exception:
            pass


def init_servo():
    global servo_pwm
    if not (SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("pwmio")):
        return False
    if SERVO_PIN is None:
        return False
    if servo_pwm is None:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=SERVO_FREQ)
    return True


def _pulse_to_duty(pulse_us: int) -> int:
    # 20ms period at 50Hz -> 20000us
    return int((pulse_us / 20000.0) * 65535.0)


def servo_write_us(pulse_us: int):
    if not init_servo():
        log("PWM/servo not available -> servo ignored")
        return False
    pulse_us = int(max(400, min(2600, pulse_us)))
    servo_pwm.duty_cycle = _pulse_to_duty(pulse_us)
    return True


def servo_stop():
    if SERVO_MODE != "continuous":
        # for positional, neutral can just be 0 duty or keep last angle
        # we'll set duty 0 to relax
        if init_servo():
            servo_pwm.duty_cycle = 0
        log("Servo stop (positional relax)")
        return True

    ok = servo_write_us(SERVO_STOP_US)
    log("Servo STOP (continuous)")
    return ok


def servo_open():
    if SERVO_MODE == "positional":
        # Example: open at 90 degrees (edit if you want)
        return set_servo_angle(90)

    # continuous rotation: run a bit then stop
    log(f"Servo OPEN (continuous) run {SERVO_RUN_SECONDS}s")
    servo_write_us(SERVO_OPEN_US)
    time.sleep(max(0.1, float(SERVO_RUN_SECONDS)))
    return servo_stop()


def servo_close():
    if SERVO_MODE == "positional":
        return set_servo_angle(0)

    log(f"Servo CLOSE (continuous) run {SERVO_RUN_SECONDS}s")
    servo_write_us(SERVO_CLOSE_US)
    time.sleep(max(0.1, float(SERVO_RUN_SECONDS)))
    return servo_stop()


def set_servo_angle(angle: int):
    # positional servo 0..180
    if SERVO_MODE != "positional":
        log("Servo angle ignored (SERVO_MODE is continuous)")
        return False

    if not init_servo():
        log("PWM/servo not available -> servo ignored")
        return False
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    servo_pwm.duty_cycle = _pulse_to_duty(int(pulse_us))
    log(f"Servo angle -> {angle}°")
    return True


def init_buzzer():
    global buzzer_io
    if not gpio_ready():
        return False
    if BUZZER_PIN is None:
        return False
    if buzzer_io is None:
        buzzer_io = digitalio.DigitalInOut(BUZZER_PIN)
        buzzer_io.direction = digitalio.Direction.OUTPUT
        buzzer_io.value = True if BUZZER_ACTIVE_LOW else False
    return True


def set_buzzer(on: bool):
    if not init_buzzer():
        log("GPIO/buzzer not available -> buzzer ignored")
        return False
    buzzer_io.value = (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)
    log(f"Buzzer -> {'ON' if on else 'OFF'}")
    return True


def beep(count=2, on_ms=120, off_ms=120):
    try:
        count = int(count)
        on_ms = int(on_ms)
        off_ms = int(off_ms)
    except Exception:
        count, on_ms, off_ms = 2, 120, 120

    for _ in range(max(1, count)):
        set_buzzer(True)
        time.sleep(max(0.01, on_ms / 1000.0))
        set_buzzer(False)
        time.sleep(max(0.01, off_ms / 1000.0))


# ==========================
# SEQUENCES
# ==========================
def led_sequence(mode="traffic", repeat=2, delay_ms=220):
    """
    traffic: red -> orange -> green (blink)
    chase:   red->orange->green then off
    """
    if not init_leds():
        log("LED seq ignored (no GPIO)")
        return

    repeat = int(max(1, repeat))
    delay = max(0.03, int(delay_ms) / 1000.0)
    mode = (mode or "traffic").lower()

    with seq_lock:
        all_leds_off()
        for _ in range(repeat):
            if mode == "traffic":
                for c in ("red", "orange", "green"):
                    all_leds_off()
                    set_led(c, True)
                    time.sleep(delay)
                    set_led(c, False)
                    time.sleep(delay * 0.6)
            else:  # chase
                for c in ("red", "orange", "green"):
                    set_led(c, True)
                    time.sleep(delay)
                all_leds_off()
                time.sleep(delay)

        all_leds_off()
    log(f"LED sequence done: {mode} x{repeat}")


def relay_sequence(mode="chase", repeat=2, delay_ms=250):
    """
    chase: relays 1..N ON one-by-one then OFF
    all_on_off: all ON then all OFF
    """
    if not init_relays():
        log("Relay seq ignored (no GPIO)")
        return

    repeat = int(max(1, repeat))
    delay = max(0.03, int(delay_ms) / 1000.0)
    mode = (mode or "chase").lower()

    chs = [ch for ch in sorted(RELAY_PINS.keys()) if RELAY_PINS[ch] is not None]
    if not chs:
        log("Relay seq: no channels configured")
        return

    with seq_lock:
        all_relays_off()
        for _ in range(repeat):
            if mode == "all_on_off":
                for ch in chs:
                    set_relay(ch, True)
                time.sleep(delay)
                for ch in chs:
                    set_relay(ch, False)
                time.sleep(delay)
            else:  # chase
                for ch in chs:
                    all_relays_off()
                    set_relay(ch, True)
                    time.sleep(delay)
                all_relays_off()
                time.sleep(delay * 0.7)

        all_relays_off()
    log(f"Relay sequence done: {mode} x{repeat}")


def all_off():
    with seq_lock:
        all_relays_off()
        all_leds_off()
        set_buzzer(False)
        servo_stop()
    log("ALL OFF executed")


# ==========================
# CLEANUP
# ==========================
def cleanup():
    global servo_pwm
    try:
        all_off()
        try:
            if servo_pwm is not None:
                servo_pwm.duty_cycle = 0
        except Exception:
            pass
    finally:
        for io in relay_ios.values():
            safe_deinit(io)
        relay_ios.clear()

        for io in led_ios.values():
            safe_deinit(io)
        led_ios.clear()

        safe_deinit(buzzer_io)

        try:
            if servo_pwm is not None:
                servo_pwm.deinit()
        except Exception:
            pass
        servo_pwm = None


def handle_exit(*_):
    global running
    running = False


def parse_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "on", "yes")


# ==========================
# MQTT callbacks
# ==========================
def on_connect(client, userdata, flags, rc):
    log("MQTT connected rc=", rc)
    if rc == 0:
        client.subscribe(TOPIC_CMD)
        log("Subscribed:", TOPIC_CMD)
    else:
        log("Connect failed (rc != 0)")


def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8", errors="replace")
    log("RX", msg.topic, "->", raw)

    try:
        data = json.loads(raw)
    except Exception:
        log("Invalid JSON payload; ignored")
        return

    device = (data.get("device") or "").lower()

    # ---------- relay ----------
    if device == "relay":
        ch = int(data.get("ch", 1))
        state = parse_bool(data.get("state", "off"))
        set_relay(ch, state)

    elif device == "relay_seq":
        mode = data.get("mode", "chase")
        repeat = data.get("repeat", 2)
        delay_ms = data.get("delay_ms", 250)
        relay_sequence(mode=mode, repeat=repeat, delay_ms=delay_ms)

    # ---------- led ----------
    elif device == "led":
        color = (data.get("color") or "red").lower()
        state = parse_bool(data.get("state", "off"))
        set_led(color, state)

    elif device == "led_seq":
        mode = data.get("mode", "traffic")
        repeat = data.get("repeat", 2)
        delay_ms = data.get("delay_ms", 220)
        led_sequence(mode=mode, repeat=repeat, delay_ms=delay_ms)

    # ---------- servo ----------
    elif device == "servo":
        # prefer action for continuous
        action = (data.get("action") or "").lower().strip()

        if action == "open":
            servo_open()
        elif action == "close":
            servo_close()
        elif action == "stop":
            servo_stop()
        elif "angle" in data:
            set_servo_angle(int(data.get("angle", 90)))
        else:
            log("Servo: missing action/angle")

    # ---------- buzzer ----------
    elif device == "beep":
        beep(
            count=data.get("count", 2),
            on_ms=data.get("on_ms", 120),
            off_ms=data.get("off_ms", 120),
        )

    elif device == "all_off":
        all_off()

    else:
        log("Unknown device/command; ignored")


def main():
    global running

    log("Exercise 22: Receive Command (MQTT)")
    log(f"Broker: {MQTT_HOST}:{MQTT_PORT}")
    log(f"Topic : {TOPIC_CMD}")
    log(f"Servo : mode={SERVO_MODE}")
    log("Stop  : Ctrl+C or dashboard Stop")

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as e:
        log("MQTT connect failed:", e)
        cleanup()
        sys.exit(1)

    client.loop_start()

    try:
        while running:
            time.sleep(0.1)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        cleanup()
        log("Stopped cleanly.")


if __name__ == "__main__":
    main()