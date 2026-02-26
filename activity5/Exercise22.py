# activity5/Exercise22.py
# FIXED: Use a command queue + worker thread so sequences don't block MQTT thread.

import json
import time
import signal
import sys
import threading
import queue

import paho.mqtt.client as mqtt

# --- Conditional GPIO imports
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
# OUTPUT PINS
# ==========================
# Active-low relays (ON=False, OFF=True)
RELAY_PINS = {
    1: getattr(board, "D27", None),
    2: getattr(board, "D10", None),
    3: getattr(board, "D26", None),
    4: getattr(board, "D25", None),
}

LED_PINS = {
    "red":    getattr(board, "D5", None),
    "orange": getattr(board, "D6", None),
    "green":  getattr(board, "D13", None),
}

SERVO_PIN = getattr(board, "D12", None)
SERVO_FREQ = 50

# Choose servo type:
# - "continuous" for 360/continuous rotation
# - "positional" for 0..180 servo
SERVO_MODE = "continuous"

# Continuous tuning (MOST IMPORTANT)
SERVO_STOP_US  = 1500   # tune 1490..1510 if needed
SERVO_OPEN_US  = 1300   # one direction (tune)
SERVO_CLOSE_US = 1700   # opposite direction (tune)
SERVO_RUN_SECONDS = 1.2 # how long to rotate then stop

# Positional range
MIN_PULSE_US = 500
MAX_PULSE_US = 2500

BUZZER_PIN = getattr(board, "D16", None)
BUZZER_ACTIVE_LOW = False


# ==========================
# GLOBAL STATE
# ==========================
running = True
cmd_q: "queue.Queue[dict]" = queue.Queue(maxsize=50)

relay_ios = {}
led_ios = {}
servo_pwm = None
buzzer_io = None

io_lock = threading.Lock()  # protect shared GPIO objects


def log(*args):
    print("[EX22]", *args, flush=True)


def gpio_ready():
    return SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("digitalio")


def safe_deinit(io):
    try:
        if io is not None:
            io.deinit()
    except Exception:
        pass


# ==========================
# RELAYS
# ==========================
def init_relays():
    if not gpio_ready():
        return False
    with io_lock:
        for ch, pin in RELAY_PINS.items():
            if pin is None:
                continue
            if ch not in relay_ios:
                io = digitalio.DigitalInOut(pin)
                io.direction = digitalio.Direction.OUTPUT
                io.value = True  # OFF (active-low)
                relay_ios[ch] = io
    return True


def set_relay(ch: int, on: bool):
    if not init_relays():
        log("GPIO not available -> relay ignored")
        return False
    with io_lock:
        io = relay_ios.get(int(ch))
        if io is None:
            log(f"Relay CH{ch} not configured")
            return False
        io.value = (not bool(on))  # active-low
    log(f"Relay CH{ch} -> {'ON' if on else 'OFF'}")
    return True


def all_relays_off():
    if not init_relays():
        return
    with io_lock:
        for ch, io in relay_ios.items():
            try:
                io.value = True
            except Exception:
                pass


# ==========================
# LEDS
# ==========================
def init_leds():
    if not gpio_ready():
        return False
    with io_lock:
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
    with io_lock:
        io = led_ios.get(color)
        if io is None:
            log(f"LED '{color}' not configured")
            return False
        io.value = bool(on)
    log(f"LED {color} -> {'ON' if on else 'OFF'}")
    return True


def all_leds_off():
    if not init_leds():
        return
    with io_lock:
        for c, io in led_ios.items():
            try:
                io.value = False
            except Exception:
                pass


# ==========================
# SERVO
# ==========================
def init_servo():
    global servo_pwm
    if not (SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("pwmio")):
        return False
    if SERVO_PIN is None:
        return False
    with io_lock:
        if servo_pwm is None:
            servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=SERVO_FREQ)
    return True


def _pulse_to_duty(pulse_us: int) -> int:
    return int((pulse_us / 20000.0) * 65535.0)  # 20ms @ 50Hz


def servo_write_us(pulse_us: int):
    if not init_servo():
        log("PWM/servo not available -> servo ignored")
        return False
    pulse_us = int(max(400, min(2600, pulse_us)))
    with io_lock:
        servo_pwm.duty_cycle = _pulse_to_duty(pulse_us)
    return True


def servo_stop():
    # IMPORTANT: for continuous servos, don't set duty_cycle=0 (signal off).
    # Keep sending STOP pulse.
    if SERVO_MODE == "continuous":
        servo_write_us(SERVO_STOP_US)
        log(f"Servo STOP (continuous, {SERVO_STOP_US}us)")
        return True
    else:
        # positional: relax
        if init_servo():
            with io_lock:
                servo_pwm.duty_cycle = 0
        log("Servo relax (positional)")
        return True


def servo_open():
    if SERVO_MODE == "positional":
        return set_servo_angle(90)

    log(f"Servo OPEN (continuous {SERVO_OPEN_US}us) for {SERVO_RUN_SECONDS}s")
    servo_write_us(SERVO_OPEN_US)
    time.sleep(max(0.1, float(SERVO_RUN_SECONDS)))
    return servo_stop()


def servo_close():
    if SERVO_MODE == "positional":
        return set_servo_angle(0)

    log(f"Servo CLOSE (continuous {SERVO_CLOSE_US}us) for {SERVO_RUN_SECONDS}s")
    servo_write_us(SERVO_CLOSE_US)
    time.sleep(max(0.1, float(SERVO_RUN_SECONDS)))
    return servo_stop()


def set_servo_angle(angle: int):
    if SERVO_MODE != "positional":
        log("Servo angle ignored (SERVO_MODE is continuous)")
        return False
    if not init_servo():
        log("PWM/servo not available -> servo ignored")
        return False
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    with io_lock:
        servo_pwm.duty_cycle = _pulse_to_duty(int(pulse_us))
    log(f"Servo angle -> {angle}°")
    return True


# ==========================
# BUZZER
# ==========================
def init_buzzer():
    global buzzer_io
    if not gpio_ready():
        return False
    if BUZZER_PIN is None:
        return False
    with io_lock:
        if buzzer_io is None:
            buzzer_io = digitalio.DigitalInOut(BUZZER_PIN)
            buzzer_io.direction = digitalio.Direction.OUTPUT
            buzzer_io.value = True if BUZZER_ACTIVE_LOW else False
    return True


def set_buzzer(on: bool):
    if not init_buzzer():
        log("GPIO/buzzer not available -> buzzer ignored")
        return False
    with io_lock:
        buzzer_io.value = (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)
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
    log(f"Beep x{count}")


# ==========================
# SEQUENCES (RUN IN WORKER)
# ==========================
def led_sequence(mode="traffic", repeat=2, delay_ms=220):
    if not init_leds():
        log("LED seq ignored (no GPIO)")
        return
    repeat = int(max(1, repeat))
    delay = max(0.03, int(delay_ms) / 1000.0)
    mode = (mode or "traffic").lower()

    log(f"LED sequence start: {mode} repeat={repeat} delay={delay_ms}ms")

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
                all_leds_off()
                set_led(c, True)
                time.sleep(delay)
            all_leds_off()
            time.sleep(delay)

    all_leds_off()
    log("LED sequence done")


def relay_sequence(mode="chase", repeat=2, delay_ms=250):
    if not init_relays():
        log("Relay seq ignored (no GPIO)")
        return

    chs = [ch for ch in sorted(RELAY_PINS.keys()) if RELAY_PINS[ch] is not None]
    if not chs:
        log("Relay seq: no channels configured")
        return

    repeat = int(max(1, repeat))
    delay = max(0.03, int(delay_ms) / 1000.0)
    mode = (mode or "chase").lower()

    log(f"Relay sequence start: {mode} repeat={repeat} delay={delay_ms}ms")

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
    log("Relay sequence done")


def all_off():
    all_relays_off()
    all_leds_off()
    set_buzzer(False)
    servo_stop()
    log("ALL OFF")


# ==========================
# COMMAND WORKER
# ==========================
def parse_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "on", "yes")


def do_command(data: dict):
    device = (data.get("device") or "").lower()

    if device == "relay":
        ch = int(data.get("ch", 1))
        state = parse_bool(data.get("state", "off"))
        set_relay(ch, state)

    elif device == "relay_seq":
        relay_sequence(
            mode=data.get("mode", "chase"),
            repeat=data.get("repeat", 2),
            delay_ms=data.get("delay_ms", 250),
        )

    elif device == "led":
        set_led(
            color=(data.get("color") or "red"),
            on=parse_bool(data.get("state", "off")),
        )

    elif device == "led_seq":
        led_sequence(
            mode=data.get("mode", "traffic"),
            repeat=data.get("repeat", 2),
            delay_ms=data.get("delay_ms", 220),
        )

    elif device == "servo":
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

    elif device == "beep":
        beep(
            count=data.get("count", 2),
            on_ms=data.get("on_ms", 120),
            off_ms=data.get("off_ms", 120),
        )

    elif device == "all_off":
        all_off()

    else:
        log("Unknown device:", device, "payload:", data)


def worker_loop():
    log("Worker started")
    while running:
        try:
            data = cmd_q.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            do_command(data)
        except Exception as e:
            log("Worker error:", e)
        finally:
            try:
                cmd_q.task_done()
            except Exception:
                pass
    log("Worker stopped")


# ==========================
# MQTT callbacks (FAST ONLY)
# ==========================
def on_connect(client, userdata, flags, rc):
    log("MQTT connected rc=", rc)
    if rc == 0:
        client.subscribe(TOPIC_CMD)
        log("Subscribed:", TOPIC_CMD)
    else:
        log("Connect failed rc=", rc)


def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8", errors="replace")
    # Keep this callback FAST (no sleep / sequences here)
    try:
        data = json.loads(raw)
    except Exception:
        log("Invalid JSON:", raw)
        return

    try:
        cmd_q.put_nowait(data)
    except queue.Full:
        log("Command queue FULL -> dropped:", data)


# ==========================
# cleanup/exit
# ==========================
def cleanup():
    global servo_pwm
    try:
        all_off()
    finally:
        with io_lock:
            for io in relay_ios.values():
                safe_deinit(io)
            relay_ios.clear()

            for io in led_ios.values():
                safe_deinit(io)
            led_ios.clear()

            safe_deinit(buzzer_io)

            try:
                if servo_pwm is not None:
                    # keep it polite
                    servo_pwm.duty_cycle = 0
                    servo_pwm.deinit()
            except Exception:
                pass
            servo_pwm = None


def handle_exit(*_):
    global running
    running = False


def main():
    global running

    log("Exercise 22: Receive Command (MQTT) [QUEUE FIX]")
    log(f"Broker: {MQTT_HOST}:{MQTT_PORT}")
    log(f"Topic : {TOPIC_CMD}")
    log(f"Servo : mode={SERVO_MODE}")
    log("Stop  : Ctrl+C or dashboard Stop")

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Start worker
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as e:
        log("MQTT connect failed:", e)
        running = False
        cleanup()
        sys.exit(1)

    client.loop_start()

    try:
        while running:
            time.sleep(0.2)
    finally:
        running = False
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        cleanup()
        log("Stopped cleanly.")


if __name__ == "__main__":
    main()