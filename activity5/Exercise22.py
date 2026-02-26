# activity5/Exercise22.py
# Exercise 22: Receive Command (MQTT Subscribe -> Control outputs)
#
# Subscribes to: trainerkit/a5/command
# Expected JSON payload examples:
#   {"device":"relay","ch":1,"state":"on"}
#   {"device":"relay","ch":2,"state":"off"}
#   {"device":"servo","angle":90}
#   {"device":"led","color":"red","state":"on"}
#   {"device":"beep","count":2}
#
# Stop: Ctrl+C or your dashboard Stop button (terminates process)

import json
import time
import signal
import sys

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
RELAY_PINS = {
    1: getattr(board, "D27", None),
    2: getattr(board, "D10", None),
    3: getattr(board, "D26", None),
    4: getattr(board, "D25", None),
}

# LED pins (same style as your server.py)
LED_PINS = {
    "red":    getattr(board, "D5", None),
    "orange": getattr(board, "D6", None),
    "green":  getattr(board, "D13", None),
}

# Servo pin (same as your server.py)
SERVO_PIN = getattr(board, "D12", None)
SERVO_FREQ = 50
MIN_PULSE_US = 500
MAX_PULSE_US = 2500

# Optional buzzer (same as your server.py)
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


def init_servo():
    global servo_pwm
    if not (SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("pwmio")):
        return False
    if SERVO_PIN is None:
        return False
    if servo_pwm is None:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=SERVO_FREQ)
    return True


def set_servo_angle(angle: int):
    if not init_servo():
        log("PWM/servo not available -> servo ignored")
        return False
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    duty = int((pulse_us / 20000.0) * 65535.0)  # 20ms period at 50Hz
    servo_pwm.duty_cycle = duty
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
        # set OFF initially
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


def cleanup():
    global servo_pwm
    try:
        # turn things off safely
        for ch in list(relay_ios.keys()):
            try:
                relay_ios[ch].value = True  # OFF (active-low)
            except Exception:
                pass
        for c in list(led_ios.keys()):
            try:
                led_ios[c].value = False
            except Exception:
                pass
        try:
            if buzzer_io is not None:
                buzzer_io.value = True if BUZZER_ACTIVE_LOW else False
        except Exception:
            pass
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

    # --- Device routing ---
    device = (data.get("device") or "").lower()

    if device == "relay":
        ch = int(data.get("ch", 1))
        state = parse_bool(data.get("state", "off"))
        set_relay(ch, state)

    elif device == "servo":
        angle = int(data.get("angle", 90))
        set_servo_angle(angle)

    elif device == "led":
        color = (data.get("color") or "red").lower()
        state = parse_bool(data.get("state", "off"))
        set_led(color, state)

    elif device == "beep":
        beep(
            count=data.get("count", 2),
            on_ms=data.get("on_ms", 120),
            off_ms=data.get("off_ms", 120),
        )

    else:
        # allow shorthand commands too
        # e.g. {"relay1":"on"} or {"light":"on"}
        if "relay1" in data:
            set_relay(1, parse_bool(data["relay1"]))
        elif "relay2" in data:
            set_relay(2, parse_bool(data["relay2"]))
        elif "gate" in data:
            # gate=open/close -> servo angles
            v = str(data["gate"]).lower()
            if v in ("open", "on", "1", "true"):
                set_servo_angle(90)
            else:
                set_servo_angle(0)
        else:
            log("Unknown device/command; ignored")


def main():
    global running

    log("Exercise 22: Receive Command (MQTT)")
    log(f"Broker: {MQTT_HOST}:{MQTT_PORT}")
    log(f"Topic : {TOPIC_CMD}")
    log("Stop  : Ctrl+C or dashboard Stop")

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message

    # connect + loop in background
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