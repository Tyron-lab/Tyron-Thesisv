# server.py — TrainerKit Tools Dashboard (FULL UPDATE)
# - Tools (toggle sensors)
# - MIC VOSK + live wave
# - Activity 5 MQTT bridge
# - Exercise runner (subprocess) for Exercise scripts
# - ✅ Multi-phone focus lock: /api/focus
# - ✅ Exercise map checker: /api/exercise_map_check
# - ✅ /api/exercise supports ALL ids in EXERCISE_MAP (a1..a5), plus a5-ex21 special
# - ✅ EX24: Event Logging Terminal endpoints + Local GPIO control via /api/a5/command
# - ✅ EX24: Servo move-then-release (fully stops holding)
# - ✅ EX24: Relay ALL ON + ALL OFF

from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging
import os
import subprocess
import sys
import signal
from collections import deque
import json
import atexit
import queue

import paho.mqtt.client as mqtt

# ────────────────────────────────────────────────
#   Conditional imports – only load what we can
# ────────────────────────────────────────────────
SENSORS_AVAILABLE = {}

try:
    import board
    import digitalio
    SENSORS_AVAILABLE["board"] = True
except Exception:
    SENSORS_AVAILABLE["board"] = False

try:
    import adafruit_dht
    SENSORS_AVAILABLE["DHT11"] = True
except Exception:
    SENSORS_AVAILABLE["DHT11"] = False

try:
    import adafruit_mpu6050
    SENSORS_AVAILABLE["MPU6050"] = True
except Exception:
    SENSORS_AVAILABLE["MPU6050"] = False

try:
    import adafruit_bmp280
    SENSORS_AVAILABLE["BMP280"] = True
except Exception:
    SENSORS_AVAILABLE["BMP280"] = False

try:
    import pwmio
    SENSORS_AVAILABLE["servomotor"] = True
except Exception:
    SENSORS_AVAILABLE["servomotor"] = False

try:
    import adafruit_tca9548a
    SENSORS_AVAILABLE["tca9548a"] = True
except Exception:
    SENSORS_AVAILABLE["tca9548a"] = False

# LCD via smbus2 + RPLCD (optional)
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    SENSORS_AVAILABLE["LCD"] = True
except Exception:
    SENSORS_AVAILABLE["LCD"] = False

# MIC
try:
    import sounddevice as sd
    import numpy as np
    SENSORS_AVAILABLE["MIC"] = True
except Exception:
    SENSORS_AVAILABLE["MIC"] = False

# VOSK
try:
    from vosk import Model, KaldiRecognizer
    SENSORS_AVAILABLE["VOSK"] = True
except Exception:
    SENSORS_AVAILABLE["VOSK"] = False

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
#   APP + GLOBALS
# ────────────────────────────────────────────────
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "static", "template")

i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

# ────────────────────────────────────────────────
#   ✅ MULTI-PHONE FOCUS LOCK
# ────────────────────────────────────────────────
FOCUS_LOCK = threading.Lock()
focus_state = {"running": False, "exercise_id": None, "since": None, "by": None}

@app.route("/api/focus", methods=["GET", "POST"])
def api_focus():
    global focus_state
    if request.method == "POST":
        data = request.json or {}
        ex_id = data.get("exercise_id")
        running = bool(data.get("running"))
        by = data.get("by")

        with FOCUS_LOCK:
            if running:
                focus_state["running"] = True
                focus_state["exercise_id"] = ex_id
                focus_state["since"] = now_iso()
                focus_state["by"] = by
            else:
                if (ex_id is None) or (focus_state.get("exercise_id") == ex_id):
                    focus_state = {"running": False, "exercise_id": None, "since": None, "by": None}

        return jsonify({"ok": True, **focus_state})

    with FOCUS_LOCK:
        return jsonify({**focus_state})

# ────────────────────────────────────────────────
#   ✅ EX24: SERVER-SIDE EVENT LOG (Terminal)
# ────────────────────────────────────────────────
EX24_LOG_LOCK = threading.Lock()
EX24_LOG = deque(maxlen=900)

def ex24_log(level: str, msg: str):
    ts = now_iso()
    line = f"[{ts}] {level.upper()}: {msg}"
    with EX24_LOG_LOCK:
        EX24_LOG.append(line)

@app.route("/api/ex24/logs", methods=["GET"])
def api_ex24_logs():
    with EX24_LOG_LOCK:
        text = "\n".join(EX24_LOG)
    if not text:
        text = "[INFO] Waiting for events..."
    return jsonify({"ok": True, "text": text + "\n"})

@app.route("/api/ex24/clear", methods=["POST"])
def api_ex24_clear():
    with EX24_LOG_LOCK:
        EX24_LOG.clear()
    ex24_log("INFO", "Log cleared")
    return jsonify({"ok": True})

# ────────────────────────────────────────────────
#   SENSOR DATA/STATE
# ────────────────────────────────────────────────
sensor_state = {
    "MPU6050":    False,
    "BMP280":     False,
    "DHT11":      False,
    "MHMQ":       False,
    "PIR":        False,
    "ULTRASONIC": False,
    "Relay":      False,
    "servomotor": False,
    "BUZZER":     False,
    "LED":        False,     # ✅ EX24
    "LCD_TOOL":   False,
    "MIC":        False,
}

sensor_data = {
    "DHT11":      {"temperature": None, "humidity": None, "last_update": None, "error": ""},
    "MPU6050":    {"ax": None, "ay": None, "az": None, "gx": None, "gy": None, "gz": None, "temperature": None, "last_update": None, "error": ""},
    "BMP280":     {"temperature": None, "pressure": None, "altitude": None, "last_update": None, "error": ""},

    "PIR":        {"motion": False, "count": 0, "last_update": None, "error": ""},
    "ULTRASONIC": {"distance_cm": None, "last_update": None, "error": ""},

    "MHMQ":       {"gas_detected": False, "level_percent": None, "last_update": None, "error": ""},

    "Relay":      {"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": None, "error": ""},
    "servomotor": {"angle": 0, "last_update": None, "error": ""},
    "BUZZER":     {"on": False, "last_update": None, "error": ""},
    "LED":        {"color": "off", "last_update": None, "error": ""},  # ✅ EX24
    "LCD_TOOL":   {"line1": "", "line2": "", "last_update": None, "error": ""},

    "MIC": {
        "rms": None, "peak": None, "sample_rate": None, "listening_rate": 16000,
        "partial": "", "text": "", "command": "", "command_at": None,
        "last_update": None, "error": ""
    },
}

def set_error(key: str, msg):
    if key in sensor_data:
        sensor_data[key]["error"] = str(msg)
        sensor_data[key]["last_update"] = now_iso()

def clear_error(key: str):
    if key in sensor_data:
        sensor_data[key]["error"] = ""

# ────────────────────────────────────────────────
#   ✅ ACTIVITY 5 MQTT BRIDGE (ESP32)
# ────────────────────────────────────────────────
MQTT_HOST = "192.168.4.1"
MQTT_PORT = 1883
MQTT_CMD_TOPIC = "trainerkit/a5/cmd"
MQTT_TELE_TOPIC = "trainerkit/a5/telemetry"

mqtt_client = None
a5_latest = {
    "topic": MQTT_TELE_TOPIC,
    "connected": False,
    "last_message_at": None,
    "payload": None,
    "json": None,
    "error": "",
}

def on_mqtt_connect(client, userdata, flags, rc):
    a5_latest["connected"] = (rc == 0)
    if rc == 0:
        try:
            client.subscribe(MQTT_TELE_TOPIC)
            print(f"[MQTT] Connected -> subscribed {MQTT_TELE_TOPIC}")
        except Exception as e:
            a5_latest["error"] = str(e)
    else:
        a5_latest["error"] = f"connect rc={rc}"

def on_mqtt_message(client, userdata, msg):
    try:
        raw = msg.payload.decode("utf-8", errors="ignore")
        a5_latest["last_message_at"] = now_iso()
        a5_latest["payload"] = raw
        try:
            a5_latest["json"] = json.loads(raw)
        except Exception:
            a5_latest["json"] = None
    except Exception as e:
        a5_latest["error"] = str(e)

def start_a5_mqtt():
    global mqtt_client
    try:
        mqtt_client = mqtt.Client()
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        mqtt_client.loop_start()
        print(f"[MQTT] bridge starting -> {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        a5_latest["error"] = str(e)
        print("[MQTT] start failed:", e)

def a5_send_cmd(payload: dict):
    global mqtt_client
    if mqtt_client is None:
        raise RuntimeError("MQTT client not ready")
    msg = json.dumps(payload)
    info = mqtt_client.publish(MQTT_CMD_TOPIC, msg, qos=0, retain=False)
    return {"topic": MQTT_CMD_TOPIC, "payload": payload, "rc": int(info.rc)}

@app.route("/api/a5/latest", methods=["GET"])
def api_a5_latest():
    return jsonify({"ok": True, **a5_latest})

@app.route("/api/a5/command", methods=["POST"])
def api_a5_command():
    data = request.json or {}
    cmd = data.get("cmd")
    if not cmd:
        return jsonify({"ok": False, "error": "Missing cmd"}), 400

    # normalize common commands
    payload = {}

    if cmd == "stream_on":
        payload = {"stream": "on"}
    elif cmd == "stream_off":
        payload = {"stream": "off"}

    # ✅ EX24 relay commands
    elif cmd == "relay1_on":
        payload = {"relay1": 1}
    elif cmd == "relay1_off":
        payload = {"relay1": 0}
    elif cmd == "relay2_on":
        payload = {"relay2": 1}
    elif cmd == "relay2_off":
        payload = {"relay2": 0}
    elif cmd == "relay_all_on":
        payload = {"relay1": 1, "relay2": 1}
    elif cmd == "relay_all_off":
        payload = {"relay1": 0, "relay2": 0}

    # ✅ EX24 buzzer
    elif cmd == "buzzer_on":
        payload = {"buzzer": 1}
    elif cmd == "buzzer_off":
        payload = {"buzzer": 0}

    # ✅ EX24 LED
    elif cmd == "led_red_on":
        payload = {"led": "red_on"}
    elif cmd == "led_red_off":
        payload = {"led": "red_off"}
    elif cmd == "led_green_on":
        payload = {"led": "green_on"}
    elif cmd == "led_green_off":
        payload = {"led": "green_off"}
    elif cmd == "led_blue_on":
        payload = {"led": "blue_on"}
    elif cmd == "led_blue_off":
        payload = {"led": "blue_off"}
    elif cmd == "led_all_off":
        payload = {"led": "all_off"}

    # ✅ EX24 servo
    elif cmd == "servo_open":
        payload = {"servo": "open"}
    elif cmd == "servo_close":
        payload = {"servo": "close"}

    else:
        return jsonify({"ok": False, "error": f"Unknown cmd: {cmd}"}), 400

    try:
        sent = a5_send_cmd(payload)
        ex24_log("CMD", f"{cmd} -> {json.dumps(payload)}")
        return jsonify({"ok": True, "sent": sent})
    except Exception as e:
        ex24_log("ERROR", f"{cmd} failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ────────────────────────────────────────────────
#   EXERCISE RUNNER (Mode B)
# ────────────────────────────────────────────────
exercise_lock = threading.Lock()
exercise_proc = None
exercise_reader_thread = None
exercise_stop_requested = False

exercise_status = {
    "exercise_id": None,
    "running": False,
    "ended": False,
    "end_reason": "",
    "exit_code": None,
    "started_at": None,
    "ended_at": None,
}

exercise_log_lock = threading.Lock()
exercise_stdout = deque(maxlen=800)
exercise_stderr = deque(maxlen=400)

EXERCISE_MAP = {
    # Activity 1
    "a1-ex1": os.path.join(BASE_DIR, "activity1", "Exercise1.py"),
    "a1-ex2": os.path.join(BASE_DIR, "activity1", "Exercise2.py"),
    "a1-ex3": os.path.join(BASE_DIR, "activity1", "Exercise3.py"),
    "a1-ex4": os.path.join(BASE_DIR, "activity1", "Exercise4.py"),
    "a1-ex5": os.path.join(BASE_DIR, "activity1", "Exercise5.py"),
    "a1-ex6": os.path.join(BASE_DIR, "activity1", "Exercise6.py"),
    "a1-ex7": os.path.join(BASE_DIR, "activity1", "Exercise7.py"),
    "a1-ex8": os.path.join(BASE_DIR, "activity1", "Exercise8.py"),
    "a1-ex9": os.path.join(BASE_DIR, "activity1", "Exercise9.py"),
    "a1-ex10": os.path.join(BASE_DIR, "activity1", "Exercise10.py"),

    # Activity 2
    "a2-ex11": os.path.join(BASE_DIR, "activity2", "Exercise11.py"),
    "a2-ex12": os.path.join(BASE_DIR, "activity2", "Exercise12.py"),
    "a2-ex13": os.path.join(BASE_DIR, "activity2", "Exercise13.py"),
    "a2-ex14": os.path.join(BASE_DIR, "activity2", "Exercise14.py"),
    "a2-ex15": os.path.join(BASE_DIR, "activity2", "Exercise15.py"),
    "a2-ex16": os.path.join(BASE_DIR, "activity2", "Exercise16.py"),
    "a2-ex17": os.path.join(BASE_DIR, "activity2", "Exercise17.py"),
    "a2-ex18": os.path.join(BASE_DIR, "activity2", "Exercise18.py"),
    "a2-ex19": os.path.join(BASE_DIR, "activity2", "Exercise19.py"),
    "a2-ex20": os.path.join(BASE_DIR, "activity2", "Exercise20.py"),

    # Activity 3
    "a3-ex11": os.path.join(BASE_DIR, "activity3", "Exercise11.py"),
    "a3-ex12": os.path.join(BASE_DIR, "activity3", "Exercise12.py"),
    "a3-ex13": os.path.join(BASE_DIR, "activity3", "Exercise13.py"),
    "a3-ex14": os.path.join(BASE_DIR, "activity3", "Exercise14.py"),
    "a3-ex15": os.path.join(BASE_DIR, "activity3", "Exercise15.py"),
    "a3-ex16": os.path.join(BASE_DIR, "activity3", "Exercise16.py"),
    "a3-ex17": os.path.join(BASE_DIR, "activity3", "Exercise17.py"),
    "a3-ex18": os.path.join(BASE_DIR, "activity3", "Exercise18.py"),
    "a3-ex19": os.path.join(BASE_DIR, "activity3", "Exercise19.py"),
    "a3-ex20": os.path.join(BASE_DIR, "activity3", "Exercise20.py"),

    # Activity 4
    "a4-ex11": os.path.join(BASE_DIR, "activity4", "Exercise11.py"),
    "a4-ex12": os.path.join(BASE_DIR, "activity4", "Exercise12.py"),
    "a4-ex13": os.path.join(BASE_DIR, "activity4", "Exercise13.py"),
    "a4-ex14": os.path.join(BASE_DIR, "activity4", "Exercise14.py"),
    "a4-ex15": os.path.join(BASE_DIR, "activity4", "Exercise15.py"),
    "a4-ex16": os.path.join(BASE_DIR, "activity4", "Exercise16.py"),
    "a4-ex17": os.path.join(BASE_DIR, "activity4", "Exercise17.py"),
    "a4-ex18": os.path.join(BASE_DIR, "activity4", "Exercise18.py"),
    "a4-ex19": os.path.join(BASE_DIR, "activity4", "Exercise19.py"),
    "a4-ex20": os.path.join(BASE_DIR, "activity4", "Exercise20.py"),

    # Activity 5
    "a5-ex21": os.path.join(BASE_DIR, "activity5", "Exercise21.py"),  # special MQTT mode
    "a5-ex22": os.path.join(BASE_DIR, "activity5", "Exercise22.py"),
    "a5-ex23": os.path.join(BASE_DIR, "activity5", "Exercise23.py"),
    "a5-ex24": os.path.join(BASE_DIR, "activity5", "Exercise24.py"),
    "a5-ex25": os.path.join(BASE_DIR, "activity5", "Exercise25.py"),
}

def _append_log(stdout_line=None, stderr_line=None):
    with exercise_log_lock:
        if stdout_line is not None:
            exercise_stdout.append(stdout_line.rstrip("\n"))
        if stderr_line is not None:
            exercise_stderr.append(stderr_line.rstrip("\n"))

def _exercise_reader(proc):
    global exercise_proc
    try:
        while proc.poll() is None:
            if proc.stdout:
                line = proc.stdout.readline()
                if line:
                    _append_log(stdout_line=line)
            if proc.stderr:
                eline = proc.stderr.readline()
                if eline:
                    _append_log(stderr_line=eline)
            time.sleep(0.01)

        # flush remaining
        try:
            if proc.stdout:
                for line in proc.stdout.readlines():
                    _append_log(stdout_line=line)
            if proc.stderr:
                for eline in proc.stderr.readlines():
                    _append_log(stderr_line=eline)
        except Exception:
            pass

    finally:
        with exercise_lock:
            exit_code = proc.poll()
            exercise_status["running"] = False
            exercise_status["ended"] = True
            exercise_status["exit_code"] = exit_code
            exercise_status["ended_at"] = now_iso()
            if exercise_stop_requested:
                exercise_status["end_reason"] = "stopped"
            else:
                exercise_status["end_reason"] = "finished" if (exit_code == 0) else "error"
            exercise_proc = None

def stop_current_exercise():
    global exercise_proc, exercise_stop_requested
    with exercise_lock:
        if exercise_proc is None or exercise_proc.poll() is not None:
            return False
        exercise_stop_requested = True
        try:
            exercise_proc.send_signal(signal.SIGINT)
        except Exception:
            try:
                exercise_proc.terminate()
            except Exception:
                pass
        return True

# ────────────────────────────────────────────────
#   MUX (TCA9548A)
# ────────────────────────────────────────────────
USE_MUX = SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False)
MUX_ADDRESS = 0x70
LCD_MUX_CH = 0
MPU_MUX_CH = 1
BMP_MUX_CH = 2
tca = None

def init_mux():
    global tca, USE_MUX
    if not USE_MUX:
        return False
    try:
        with i2c_lock:
            i2c = board.I2C()
            tca = adafruit_tca9548a.TCA9548A(i2c, address=MUX_ADDRESS)
        print(f"[MUX] TCA9548A OK addr=0x{MUX_ADDRESS:02X}")
        return True
    except Exception as e:
        print("[MUX] init failed:", e)
        tca = None
        USE_MUX = False
        return False

if SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("tca9548a"):
    init_mux()

# ────────────────────────────────────────────────
#   LCD (with MUX select)
# ────────────────────────────────────────────────
LCD_I2C_BUS = 1
LCD_ADDRS = [0x27, 0x3F]
LCD_COLS = 16
LCD_ROWS = 2
_lcd = None
_lcd_addr = None

def mux_select_for_lcd():
    if not SENSORS_AVAILABLE.get("LCD"):
        return False
    if not USE_MUX:
        return True
    try:
        with i2c_lock:
            with SMBus(LCD_I2C_BUS) as bus:
                bus.write_byte(MUX_ADDRESS, 1 << LCD_MUX_CH)
        return True
    except Exception as e:
        set_error("LCD_TOOL", f"mux select failed: {e}")
        return False

def lcd_get():
    global _lcd, _lcd_addr
    if not SENSORS_AVAILABLE.get("LCD"):
        set_error("LCD_TOOL", "LCD libraries not installed")
        return None
    if _lcd is not None:
        return _lcd

    if not mux_select_for_lcd():
        return None

    last_err = None
    for addr in LCD_ADDRS:
        try:
            with i2c_lock:
                _lcd = CharLCD(
                    "PCF8574",
                    address=addr,
                    port=LCD_I2C_BUS,
                    cols=LCD_COLS,
                    rows=LCD_ROWS,
                    charmap="A00",
                )
                _lcd.clear()
            _lcd_addr = addr
            clear_error("LCD_TOOL")
            print(f"[LCD] OK addr=0x{addr:02X} mux_ch={LCD_MUX_CH if USE_MUX else 'direct'}")
            return _lcd
        except Exception as e:
            _lcd = None
            last_err = e

    set_error("LCD_TOOL", f"init failed: {last_err}")
    return None

def lcd_write(line1="", line2=""):
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_for_lcd():
        return False
    try:
        with i2c_lock:
            lcd.clear()
            lcd.write_string((line1 or "")[:LCD_COLS])
            lcd.cursor_pos = (1, 0)
            lcd.write_string((line2 or "")[:LCD_COLS])
        sensor_data["LCD_TOOL"].update({"line1": line1, "line2": line2, "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_error("LCD_TOOL", f"write failed: {e}")
        return False

def lcd_clear():
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_for_lcd():
        return False
    try:
        with i2c_lock:
            lcd.clear()
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_error("LCD_TOOL", f"clear failed: {e}")
        return False

# ────────────────────────────────────────────────
#   RELAY
# ────────────────────────────────────────────────
relay_pins = {}

def init_relay():
    global relay_pins
    if not SENSORS_AVAILABLE.get("board"):
        set_error("Relay", "board not available")
        return False
    if relay_pins:
        return True
    RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]  # active-low
    try:
        relay_pins = {}
        for ch, pin in enumerate(RELAY_PINS, 1):
            io = digitalio.DigitalInOut(pin)
            io.direction = digitalio.Direction.OUTPUT
            io.value = True  # OFF if active-low
            relay_pins[ch] = io
        sensor_data["Relay"].update({"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": now_iso(), "error": ""})
        clear_error("Relay")
        print("[RELAY] OK 4ch")
        return True
    except Exception as e:
        relay_pins = {}
        set_error("Relay", f"init failed: {e}")
        return False

RELAY_ACTIVE_LOW = True
def _relay_gpio_value(on: bool) -> bool:
    return (not bool(on)) if RELAY_ACTIVE_LOW else bool(on)

def set_relay(ch: int, on: bool) -> bool:
    if not init_relay():
        return False
    io = relay_pins.get(int(ch))
    if io is None:
        set_error("Relay", f"unknown channel {ch}")
        return False
    try:
        io.value = _relay_gpio_value(on)
        data = {
            "ch1": bool(relay_pins.get(1) and relay_pins[1].value == _relay_gpio_value(True)),
            "ch2": bool(relay_pins.get(2) and relay_pins[2].value == _relay_gpio_value(True)),
            "ch3": bool(relay_pins.get(3) and relay_pins[3].value == _relay_gpio_value(True)),
            "ch4": bool(relay_pins.get(4) and relay_pins[4].value == _relay_gpio_value(True)),
            "last_update": now_iso(),
            "error": "",
        }
        sensor_data["Relay"].update(data)
        clear_error("Relay")
        return True
    except Exception as e:
        set_error("Relay", e)
        return False

def set_all_relays(on: bool) -> bool:
    if not init_relay():
        return False
    ok = True
    for ch in [1, 2, 3, 4]:
        ok = set_relay(ch, on) and ok
    return ok

# ────────────────────────────────────────────────
#   BUZZER
# ────────────────────────────────────────────────
buzzer = None
BUZZER_PIN = "D21"
BUZZER_ACTIVE_LOW = True

def _get_board_pin(name: str):
    return getattr(board, name)

def init_buzzer():
    global buzzer
    if not SENSORS_AVAILABLE.get("board"):
        set_error("BUZZER", "board not available")
        return False
    if buzzer is not None:
        return True
    try:
        buzzer = digitalio.DigitalInOut(_get_board_pin(BUZZER_PIN))
        buzzer.direction = digitalio.Direction.OUTPUT
        buzzer.value = True if BUZZER_ACTIVE_LOW else False  # OFF
        sensor_data["BUZZER"].update({"on": False, "last_update": now_iso(), "error": ""})
        clear_error("BUZZER")
        print(f"[BUZZER] OK pin={BUZZER_PIN} active_low={BUZZER_ACTIVE_LOW}")
        return True
    except Exception as e:
        buzzer = None
        set_error("BUZZER", f"init failed: {e}")
        return False

def _buzzer_gpio_value(on: bool) -> bool:
    return (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)

def set_buzzer(on: bool) -> bool:
    if not init_buzzer():
        return False
    try:
        buzzer.value = _buzzer_gpio_value(on)
        sensor_data["BUZZER"].update({"on": bool(on), "last_update": now_iso(), "error": ""})
        clear_error("BUZZER")
        return True
    except Exception as e:
        set_error("BUZZER", e)
        return False

def beep(count=2, on_ms=140, off_ms=140):
    if not init_buzzer():
        return False
    for _ in range(int(count)):
        set_buzzer(True)
        time.sleep(max(0.01, on_ms / 1000))
        set_buzzer(False)
        time.sleep(max(0.01, off_ms / 1000))
    return True

# ────────────────────────────────────────────────
#   LED (D5 red, D6 green, D13 orange)
# ────────────────────────────────────────────────
led_red = None
led_green = None
led_orange = None

def init_leds():
    global led_red, led_green, led_orange
    if not SENSORS_AVAILABLE.get("board"):
        set_error("LED", "board not available")
        return False
    if led_red and led_green and led_orange:
        return True
    try:
        led_red = digitalio.DigitalInOut(board.D5)
        led_green = digitalio.DigitalInOut(board.D6)
        led_orange = digitalio.DigitalInOut(board.D13)
        for io in (led_red, led_green, led_orange):
            io.direction = digitalio.Direction.OUTPUT
            io.value = False
        sensor_data["LED"].update({"color": "off", "last_update": now_iso(), "error": ""})
        clear_error("LED")
        print("[LED] OK pins RED=D5 GREEN=D6 ORANGE=D13")
        return True
    except Exception as e:
        led_red = None
        led_green = None
        led_orange = None
        set_error("LED", f"init failed: {e}")
        return False

def leds_off():
    if not init_leds():
        return False
    try:
        led_red.value = False
        led_green.value = False
        led_orange.value = False
        sensor_data["LED"].update({"color": "off", "last_update": now_iso(), "error": ""})
        clear_error("LED")
        return True
    except Exception as e:
        set_error("LED", e)
        return False

def led_set(color: str, on: bool) -> bool:
    if not init_leds():
        return False
    color = (color or "").strip().lower()
    mp = {
        "red": led_red,
        "green": led_green,
        "orange": led_orange,
    }
    io = mp.get(color)
    if io is None:
        set_error("LED", f"unknown color: {color}")
        return False
    try:
        if on:
            led_red.value = False
            led_green.value = False
            led_orange.value = False
        io.value = bool(on)
        sensor_data["LED"].update({"color": color if on else "off", "last_update": now_iso(), "error": ""})
        clear_error("LED")
        return True
    except Exception as e:
        set_error("LED", e)
        return False

def leds_deinit():
    global led_red, led_green, led_orange
    for io in (led_red, led_green, led_orange):
        try:
            if io is not None:
                io.value = False
        except Exception:
            pass
        try:
            if io is not None:
                io.deinit()
        except Exception:
            pass
    led_red = None
    led_green = None
    led_orange = None
    sensor_data["LED"].update({"color": "off", "last_update": now_iso(), "error": ""})

# ────────────────────────────────────────────────
#   SERVO
# ────────────────────────────────────────────────
servo_pwm = None
SERVO_PIN = "D19"
SERVO_FREQ = 50

def init_servomotor():
    global servo_pwm
    if not SENSORS_AVAILABLE.get("servomotor"):
        set_error("servomotor", "pwmio not available")
        return False
    if servo_pwm is not None:
        return True
    try:
        servo_pwm = pwmio.PWMOut(_get_board_pin(SERVO_PIN), duty_cycle=0, frequency=SERVO_FREQ)
        sensor_data["servomotor"].update({"angle": 0, "last_update": now_iso(), "error": ""})
        clear_error("servomotor")
        print(f"[SERVO] OK pin={SERVO_PIN}")
        return True
    except Exception as e:
        servo_pwm = None
        set_error("servomotor", f"init failed: {e}")
        return False

def _angle_to_duty_u16(angle: int) -> int:
    angle = max(0, min(180, int(angle)))
    us = 500 + (angle / 180.0) * 2000
    period_us = 1000000 / SERVO_FREQ
    return int((us / period_us) * 65535)

def move_servo(angle: int) -> bool:
    if not init_servomotor():
        return False
    try:
        servo_pwm.duty_cycle = _angle_to_duty_u16(angle)
        sensor_data["servomotor"].update({"angle": int(angle), "last_update": now_iso(), "error": ""})
        clear_error("servomotor")
        return True
    except Exception as e:
        set_error("servomotor", e)
        return False

def stop_servo():
    global servo_pwm
    if servo_pwm is None:
        return True
    try:
        servo_pwm.duty_cycle = 0
        time.sleep(0.05)
    except Exception:
        pass
    try:
        servo_pwm.deinit()
    except Exception:
        pass
    servo_pwm = None
    sensor_data["servomotor"].update({"angle": 0, "last_update": now_iso(), "error": ""})
    clear_error("servomotor")
    return True

# ────────────────────────────────────────────────
#   I2C SENSORS
# ────────────────────────────────────────────────
i2c_bus = None
mpu = None
bmp = None
dht_device = None

def init_i2c_bus():
    global i2c_bus
    if not SENSORS_AVAILABLE.get("board"):
        return None
    if i2c_bus is not None:
        return i2c_bus
    try:
        i2c_bus = board.I2C()
        return i2c_bus
    except Exception:
        return None

def init_mpu():
    global mpu
    if not SENSORS_AVAILABLE.get("MPU6050"):
        set_error("MPU6050", "library not installed")
        return False
    if mpu is not None:
        return True
    try:
        with i2c_lock:
            bus = init_i2c_bus()
            if bus is None:
                raise RuntimeError("I2C bus init failed")
            if USE_MUX and tca is not None:
                mpu = adafruit_mpu6050.MPU6050(tca[MPU_MUX_CH])
            else:
                mpu = adafruit_mpu6050.MPU6050(bus)
        clear_error("MPU6050")
        print("[MPU6050] OK")
        return True
    except Exception as e:
        mpu = None
        set_error("MPU6050", f"init failed: {e}")
        return False

def init_bmp():
    global bmp
    if not SENSORS_AVAILABLE.get("BMP280"):
        set_error("BMP280", "library not installed")
        return False
    if bmp is not None:
        return True
    try:
        with i2c_lock:
            bus = init_i2c_bus()
            if bus is None:
                raise RuntimeError("I2C bus init failed")
            if USE_MUX and tca is not None:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_MUX_CH])
            else:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(bus)
        clear_error("BMP280")
        print("[BMP280] OK")
        return True
    except Exception as e:
        bmp = None
        set_error("BMP280", f"init failed: {e}")
        return False

def init_dht():
    global dht_device
    if not SENSORS_AVAILABLE.get("DHT11"):
        set_error("DHT11", "library not installed")
        return False
    if dht_device is not None:
        return True
    try:
        dht_device = adafruit_dht.DHT11(board.D4, use_pulseio=False)
        clear_error("DHT11")
        print("[DHT11] OK pin=D4")
        return True
    except Exception as e:
        dht_device = None
        set_error("DHT11", f"init failed: {e}")
        return False

# ────────────────────────────────────────────────
#   DIGITAL INPUT SENSORS
# ────────────────────────────────────────────────
pir_pin = None
ultra_trig = None
ultra_echo = None
mq_pin = None

def init_pir():
    global pir_pin
    if not SENSORS_AVAILABLE.get("board"):
        set_error("PIR", "board not available")
        return False
    if pir_pin is not None:
        return True
    try:
        pir_pin = digitalio.DigitalInOut(board.D22)
        pir_pin.direction = digitalio.Direction.INPUT
        try:
            pir_pin.pull = digitalio.Pull.DOWN
        except Exception:
            pass
        clear_error("PIR")
        print("[PIR] OK D22")
        return True
    except Exception as e:
        pir_pin = None
        set_error("PIR", f"init failed: {e}")
        return False

def init_ultrasonic():
    global ultra_trig, ultra_echo
    if not SENSORS_AVAILABLE.get("board"):
        set_error("ULTRASONIC", "board not available")
        return False
    if ultra_trig is not None and ultra_echo is not None:
        return True
    try:
        ultra_trig = digitalio.DigitalInOut(board.D23)
        ultra_echo = digitalio.DigitalInOut(board.D24)
        ultra_trig.direction = digitalio.Direction.OUTPUT
        ultra_echo.direction = digitalio.Direction.INPUT
        ultra_trig.value = False
        clear_error("ULTRASONIC")
        print("[ULTRASONIC] OK TRIG=D23 ECHO=D24")
        return True
    except Exception as e:
        ultra_trig = None
        ultra_echo = None
        set_error("ULTRASONIC", f"init failed: {e}")
        return False

def measure_distance(TRIG, ECHO):
    try:
        TRIG.value = True
        time.sleep(0.00001)
        TRIG.value = False

        start = time.time()
        timeout = start + 0.1

        while ECHO.value == 0 and time.time() < timeout:
            start = time.time()

        end = time.time()
        while ECHO.value == 1 and time.time() < timeout:
            end = time.time()

        duration = end - start
        if duration <= 0 or duration > 0.1:
            return None
        return round(duration * 17150, 1)
    except Exception:
        return None

def init_mq():
    global mq_pin
    if not SENSORS_AVAILABLE.get("board"):
        set_error("MHMQ", "board not available")
        return False
    if mq_pin is not None:
        return True
    try:
        mq_pin = digitalio.DigitalInOut(board.D17)
        mq_pin.direction = digitalio.Direction.INPUT
        clear_error("MHMQ")
        print("[MHMQ] OK D17")
        return True
    except Exception as e:
        mq_pin = None
        set_error("MHMQ", f"init failed: {e}")
        return False

def ensure_sensor_init(sensor: str) -> bool:
    if sensor == "DHT11": return init_dht()
    if sensor == "MPU6050": return init_mpu()
    if sensor == "BMP280": return init_bmp()
    if sensor == "PIR": return init_pir()
    if sensor == "ULTRASONIC": return init_ultrasonic()
    if sensor == "MHMQ": return init_mq()
    if sensor == "Relay": return init_relay()
    if sensor == "servomotor": return init_servomotor()
    if sensor == "MIC": return mic_start()
    if sensor == "LED": return init_leds()
    return True

def release_all_sensor_gpio():
    global pir_pin, ultra_trig, ultra_echo, mq_pin, dht_device
    try:
        if pir_pin: pir_pin.deinit()
    except Exception:
        pass
    pir_pin = None

    try:
        if ultra_trig: ultra_trig.deinit()
        if ultra_echo: ultra_echo.deinit()
    except Exception:
        pass
    ultra_trig = None
    ultra_echo = None

    try:
        if mq_pin: mq_pin.deinit()
    except Exception:
        pass
    mq_pin = None

    try:
        if dht_device is not None:
            dht_device.exit()
    except Exception:
        pass
    dht_device = None


def deinit_relay_gpio():
    global relay_pins
    try:
        for io in relay_pins.values():
            try:
                io.value = _relay_gpio_value(False)
            except Exception:
                pass
            try:
                io.deinit()
            except Exception:
                pass
    except Exception:
        pass
    relay_pins = {}
    sensor_data["Relay"].update({"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": now_iso(), "error": ""})


def deinit_buzzer_gpio():
    global buzzer
    try:
        if buzzer is not None:
            try:
                buzzer.value = True if BUZZER_ACTIVE_LOW else False
            except Exception:
                pass
            try:
                buzzer.deinit()
            except Exception:
                pass
    except Exception:
        pass
    buzzer = None
    sensor_data["BUZZER"].update({"on": False, "last_update": now_iso(), "error": ""})


def lcd_tool_release():
    global _lcd, _lcd_addr
    try:
        if _lcd is not None:
            try:
                if mux_select_for_lcd():
                    _lcd.clear()
            except Exception:
                pass
    finally:
        _lcd = None
        _lcd_addr = None
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})


def stop_all_tools(reason: str = ""):
    for k in running_flags.keys():
        running_flags[k] = False

    time.sleep(0.15)

    try:
        mic_stop()
    except Exception:
        pass
    try:
        stop_servo()
    except Exception:
        pass
    try:
        set_all_relays(False)
    except Exception:
        pass
    try:
        leds_off()
    except Exception:
        pass
    try:
        set_buzzer(False)
    except Exception:
        pass
    try:
        lcd_clear()
    except Exception:
        pass

    release_all_sensor_gpio()
    deinit_relay_gpio()
    deinit_buzzer_gpio()
    leds_deinit()
    lcd_tool_release()

    for key in sensor_state.keys():
        sensor_state[key] = False

    if reason:
        print(f"[TOOLS] stopped: {reason}")

# ────────────────────────────────────────────────
#   SENSOR READER THREADS (Tools mode)
# ────────────────────────────────────────────────
threads = {}
running_flags = {k: False for k in sensor_state.keys()}
motion_count = 0

def sensor_reader(sensor_name):
    global motion_count
    last_pir_state = False

    while running_flags.get(sensor_name, False):
        now = now_iso()
        try:
            if sensor_name == "DHT11" and dht_device:
                try:
                    t = dht_device.temperature
                    h = dht_device.humidity
                    if t is not None and h is not None:
                        sensor_data["DHT11"].update({"temperature": round(t, 1), "humidity": round(h, 1), "last_update": now, "error": ""})
                        clear_error("DHT11")
                except Exception as e:
                    set_error("DHT11", e)

            elif sensor_name == "MPU6050" and mpu:
                try:
                    with i2c_lock:
                        ax, ay, az = mpu.acceleration
                        gx, gy, gz = mpu.gyro
                        temp = getattr(mpu, "temperature", None)
                    sensor_data["MPU6050"].update({
                        "ax": round(ax, 2), "ay": round(ay, 2), "az": round(az, 2),
                        "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2),
                        "temperature": round(temp, 1) if temp is not None else None,
                        "last_update": now, "error": ""
                    })
                    clear_error("MPU6050")
                except Exception as e:
                    set_error("MPU6050", e)

            elif sensor_name == "BMP280" and bmp:
                try:
                    with i2c_lock:
                        t = bmp.temperature
                        p = bmp.pressure
                        alt = bmp.altitude
                    sensor_data["BMP280"].update({
                        "temperature": round(t, 2),
                        "pressure": round(p, 2),
                        "altitude": round(alt, 2),
                        "last_update": now, "error": ""
                    })
                    clear_error("BMP280")
                except Exception as e:
                    set_error("BMP280", e)

            elif sensor_name == "PIR" and pir_pin:
                motion = bool(pir_pin.value)
                if motion and not last_pir_state:
                    motion_count += 1
                last_pir_state = motion
                sensor_data["PIR"].update({"motion": motion, "count": motion_count, "last_update": now, "error": ""})
                clear_error("PIR")

            elif sensor_name == "ULTRASONIC" and ultra_trig and ultra_echo:
                d = measure_distance(ultra_trig, ultra_echo)
                sensor_data["ULTRASONIC"].update({"distance_cm": d, "last_update": now, "error": ""})
                clear_error("ULTRASONIC")

            elif sensor_name == "MHMQ" and mq_pin:
                detected = bool(mq_pin.value)
                sensor_data["MHMQ"].update({
                    "gas_detected": detected,
                    "level_percent": 100 if detected else 0,
                    "last_update": now,
                    "error": ""
                })
                clear_error("MHMQ")

            time.sleep(1.0)

        except Exception as e:
            set_error(sensor_name, e)
            time.sleep(1.0)

# ────────────────────────────────────────────────
#   MIC + VOSK
# ────────────────────────────────────────────────
MIC_LOCK = threading.Lock()
MIC_STREAM = None
MIC_WORKER_THREAD = None
MIC_WORKER_RUN = False
MIC_Q = queue.Queue(maxsize=16)

MIC_INPUT_DEVICE = None
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "vosk-model-small-en-us-0.15")
VOSK_MODEL = None
VOSK_REC = None
VOSK_TARGET_SR = 16000
VOSK_LOCK = threading.Lock()

VOICE_TRIGGERS = {
    "hello",
    "hello hello",
    "open",
    "open open",
    "close",
    "left",
    "right",
    "red",
    "green",
    "orange",
}

def _detect_trigger(text: str):
    txt = (text or "").strip().lower()
    if not txt:
        return ""
    for trig in sorted(VOICE_TRIGGERS, key=len, reverse=True):
        if trig in txt:
            return trig
    return ""

def vosk_init():
    global VOSK_MODEL, VOSK_REC
    if not SENSORS_AVAILABLE.get("VOSK", False):
        set_error("MIC", "vosk not installed")
        return False
    if not os.path.isdir(VOSK_MODEL_PATH):
        set_error("MIC", f"Vosk model not found: {VOSK_MODEL_PATH}")
        return False
    try:
        with VOSK_LOCK:
            if VOSK_MODEL is None:
                VOSK_MODEL = Model(VOSK_MODEL_PATH)
            if VOSK_REC is None:
                VOSK_REC = KaldiRecognizer(VOSK_MODEL, VOSK_TARGET_SR)
        clear_error("MIC")
        return True
    except Exception as e:
        set_error("MIC", f"Vosk init failed: {e}")
        return False

def _downsample_to_16k(x_float32, src_sr):
    if src_sr == 16000:
        return x_float32
    if len(x_float32) == 0:
        return x_float32
    ratio = 16000.0 / float(src_sr)
    n_out = max(1, int(len(x_float32) * ratio))
    idx = np.linspace(0, len(x_float32) - 1, n_out)
    lo = np.floor(idx).astype(np.int32)
    hi = np.minimum(lo + 1, len(x_float32) - 1)
    frac = (idx - lo).astype(np.float32)
    return (x_float32[lo] * (1.0 - frac) + x_float32[hi] * frac).astype(np.float32)

def _try_open_input_stream(device, samplerate, blocksize, callback):
    try:
        stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="float32",
            callback=callback,
        )
        stream.start()
        return stream
    except Exception:
        return None

def _mic_audio_callback(indata, frames, time_info, status):
    if status:
        pass
    try:
        MIC_Q.put_nowait(indata[:, 0].copy())
    except queue.Full:
        try:
            MIC_Q.get_nowait()
        except Exception:
            pass
        try:
            MIC_Q.put_nowait(indata[:, 0].copy())
        except Exception:
            pass

def _mic_worker(src_sr):
    global MIC_WORKER_RUN
    while MIC_WORKER_RUN:
        try:
            chunk = MIC_Q.get(timeout=0.25)
        except queue.Empty:
            continue

        try:
            ts = now_iso()
            peak = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
            rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
            chunk16 = _downsample_to_16k(chunk, src_sr)
            pcm16 = (chunk16 * 32767.0).astype(np.int16).tobytes()

            partial_txt = ""
            final_txt = ""

            with VOSK_LOCK:
                if VOSK_REC is not None:
                    if VOSK_REC.AcceptWaveform(pcm16):
                        res = json.loads(VOSK_REC.Result() or "{}")
                        final_txt = (res.get("text") or "").strip()
                    else:
                        pres = json.loads(VOSK_REC.PartialResult() or "{}")
                        partial_txt = (pres.get("partial") or "").strip()

            if partial_txt:
                sensor_data["MIC"]["partial"] = partial_txt

            if final_txt:
                sensor_data["MIC"]["text"] = final_txt
                sensor_data["MIC"]["partial"] = ""
                trig = _detect_trigger(final_txt)
                if trig:
                    sensor_data["MIC"]["command"] = trig
                    sensor_data["MIC"]["command_at"] = ts
                    beep(count=1, on_ms=70, off_ms=60)

            sensor_data["MIC"].update({
                "rms": round(float(rms), 4),
                "peak": round(float(peak), 4),
                "last_update": ts,
                "error": sensor_data["MIC"].get("error", ""),
            })

        except Exception as e:
            set_error("MIC", e)

def mic_stop():
    global MIC_STREAM, MIC_WORKER_THREAD, MIC_WORKER_RUN
    with MIC_LOCK:
        try:
            if MIC_STREAM is not None:
                MIC_STREAM.stop()
                MIC_STREAM.close()
        except Exception:
            pass
        MIC_STREAM = None

    MIC_WORKER_RUN = False
    try:
        while True:
            MIC_Q.get_nowait()
    except Exception:
        pass

    if MIC_WORKER_THREAD and MIC_WORKER_THREAD.is_alive():
        try:
            MIC_WORKER_THREAD.join(timeout=1.0)
        except Exception:
            pass
    MIC_WORKER_THREAD = None

    with VOSK_LOCK:
        try:
            if VOSK_MODEL is not None:
                globals()["VOSK_REC"] = KaldiRecognizer(VOSK_MODEL, VOSK_TARGET_SR)
        except Exception:
            pass

def mic_start():
    global MIC_STREAM, MIC_WORKER_THREAD, MIC_WORKER_RUN
    if not SENSORS_AVAILABLE.get("MIC", False):
        set_error("MIC", "sounddevice/numpy not installed")
        return False
    if not vosk_init():
        return False

    src_sr = None

    with MIC_LOCK:
        if MIC_STREAM is not None:
            return True

        dev = sd.default.device[0]
        candidate_rates = [48000, 44100, 32000, 24000, 16000, 8000]
        stream = None

        for r in candidate_rates:
            blocksize = int(r * 0.05)
            stream = _try_open_input_stream(dev, r, blocksize, _mic_audio_callback)
            if stream is not None:
                src_sr = r
                break

        if stream is None:
            set_error("MIC", "Could not open microphone at common sample rates")
            return False

        MIC_STREAM = stream
        MIC_WORKER_RUN = True
        MIC_WORKER_THREAD = threading.Thread(target=_mic_worker, args=(src_sr,), daemon=True)
        MIC_WORKER_THREAD.start()

        sensor_data["MIC"].update({
            "sample_rate": src_sr,
            "listening_rate": VOSK_TARGET_SR,
            "last_update": now_iso(),
            "error": ""
        })
        clear_error("MIC")
        print(f"[MIC] OK stream at {src_sr} Hz -> VOSK {VOSK_TARGET_SR}")
        return True

# ────────────────────────────────────────────────
#   STATIC FILES / PAGES
# ────────────────────────────────────────────────
@app.route("/")
def root():
    return send_from_directory(TEMPLATE_DIR, "welcome.html")

@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory(os.path.join(BASE_DIR, "static"), path)

# ────────────────────────────────────────────────
#   API: STATUS / TOOLS
# ────────────────────────────────────────────────
@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "ok": True,
        "state": sensor_state,
        "data": sensor_data,
        "exercise": exercise_status,
        "a5": a5_latest,
        "focus": focus_state,
        "sensors_available": SENSORS_AVAILABLE,
    })

@app.route("/api/exercise_map_check", methods=["GET"])
def api_exercise_map_check():
    rows = []
    for ex_id, path in EXERCISE_MAP.items():
        rows.append({
            "exercise_id": ex_id,
            "path": path,
            "exists": os.path.exists(path)
        })
    return jsonify({"ok": True, "items": rows})

@app.route("/api/tool/toggle", methods=["POST"])
def api_toggle_sensor():
    data = request.json or {}
    sensor = data.get("sensor")
    active = bool(data.get("active"))

    if sensor not in sensor_state:
        return jsonify({"ok": False, "error": f"Unknown sensor: {sensor}"}), 400

    sensor_state[sensor] = active

    if sensor == "Relay":
        if active:
            ok = init_relay()
            if not ok:
                sensor_state[sensor] = False
        else:
            set_all_relays(False)
            deinit_relay_gpio()
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "relay": sensor_data["Relay"],
            "error": sensor_data["Relay"]["error"] if not ok else ""
        }), (200 if ok else 500)

    if sensor == "BUZZER":
        if active:
            ok = init_buzzer()
            if not ok:
                sensor_state[sensor] = False
        else:
            set_buzzer(False)
            deinit_buzzer_gpio()
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "buzzer": sensor_data["BUZZER"],
            "error": sensor_data["BUZZER"]["error"] if not ok else ""
        }), (200 if ok else 500)

    if sensor == "LCD_TOOL":
        if active:
            ok = lcd_get() is not None
            if not ok:
                sensor_state[sensor] = False
        else:
            lcd_clear()
            lcd_tool_release()
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "lcd": sensor_data["LCD_TOOL"],
            "error": sensor_data["LCD_TOOL"]["error"] if not ok else ""
        }), (200 if ok else 500)

    if sensor == "servomotor":
        if active:
            ok = init_servomotor()
            if not ok:
                sensor_state[sensor] = False
        else:
            stop_servo()
            sensor_data["servomotor"].update({"angle": 0, "last_update": now_iso(), "error": ""})
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "servo": sensor_data["servomotor"],
            "error": sensor_data["servomotor"]["error"] if not ok else ""
        }), (200 if ok else 500)

    if sensor == "MIC":
        if active:
            ok = mic_start()
            if not ok:
                sensor_state[sensor] = False
        else:
            mic_stop()
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "mic": sensor_data["MIC"],
            "error": sensor_data["MIC"]["error"] if not ok else ""
        }), (200 if ok else 500)

    if sensor == "LED":
        if active:
            ok = init_leds()
            if not ok:
                sensor_state[sensor] = False
        else:
            leds_off()
            leds_deinit()
            ok = True
        return jsonify({
            "ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
            "led": sensor_data["LED"],
            "error": sensor_data["LED"]["error"] if not ok else ""
        }), (200 if ok else 500)

    # regular sensors: start/stop reader loop
    if active:
        if not ensure_sensor_init(sensor):
            sensor_state[sensor] = False
            return jsonify({"ok": False, "sensor": sensor, "active": False, "error": sensor_data[sensor]["error"]}), 500

        running_flags[sensor] = True
        if sensor not in threads or not threads[sensor].is_alive():
            threads[sensor] = threading.Thread(target=sensor_reader, args=(sensor,), daemon=True)
            threads[sensor].start()
    else:
        running_flags[sensor] = False

    return jsonify({"ok": True, "sensor": sensor, "active": active})

@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode", "toggle")
    if mode == "toggle":
        desired = not bool(sensor_data["BUZZER"]["on"])
        ok = set_buzzer(desired)
        return jsonify({"ok": bool(ok), "on": sensor_data["BUZZER"]["on"], "error": sensor_data["BUZZER"]["error"] if not ok else ""}), (200 if ok else 500)
    if mode == "beep":
        beep(count=int(data.get("count", 2)), on_ms=int(data.get("on_ms", 140)), off_ms=int(data.get("off_ms", 140)))
        return jsonify({"ok": True, "on": False})
    return jsonify({"ok": False, "error": "Unknown mode"}), 400

@app.route("/api/lcd", methods=["POST"])
def api_lcd():
    data = request.json or {}
    if data.get("clear"):
        ok = lcd_clear()
        return jsonify({"ok": bool(ok), "line1": "", "line2": "", "error": sensor_data["LCD_TOOL"]["error"] if not ok else ""}), (200 if ok else 500)
    line1 = (data.get("line1") or "").strip()
    line2 = (data.get("line2") or "").strip()
    ok = lcd_write(line1, line2)
    return jsonify({"ok": bool(ok), "line1": line1, "line2": line2, "error": sensor_data["LCD_TOOL"]["error"] if not ok else ""}), (200 if ok else 500)

# ────────────────────────────────────────────────
#   API: EXERCISE RUN (Mode B) + A5-EX21 special
# ────────────────────────────────────────────────
@app.route("/api/exercise", methods=["POST"])
def api_exercise_run():
    global exercise_proc, exercise_reader_thread, exercise_stop_requested
    data = request.json or {}
    ex_id = data.get("exercise_id") or data.get("id")

    if not ex_id:
        return jsonify({"ok": False, "error": "Missing exercise_id"}), 400

    # a5-ex21 special (MQTT stream ON)
    if ex_id == "a5-ex21":
        try:
            a5_send_cmd({"stream": "on"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        with exercise_lock:
            exercise_status.update({
                "exercise_id": ex_id,
                "running": True,
                "ended": False,
                "end_reason": "",
                "exit_code": None,
                "started_at": now_iso(),
                "ended_at": None,
            })
        return jsonify({"ok": True, "exercise_id": ex_id, "started": True, "mode": "mqtt", "sent": {"stream": "on"}})

    if ex_id not in EXERCISE_MAP:
        return jsonify({"ok": False, "error": f"Unknown exercise_id: {ex_id}"}), 400

    script_path = EXERCISE_MAP[ex_id]
    if not os.path.exists(script_path):
        return jsonify({"ok": False, "error": f"File not found: {script_path}"}), 404

    with exercise_lock:
        if exercise_proc is not None and exercise_proc.poll() is None:
            stop_current_exercise()

        stop_all_tools("exercise start")

        with exercise_log_lock:
            exercise_stdout.clear()
            exercise_stderr.clear()

        exercise_stop_requested = False
        exercise_status.update({
            "exercise_id": ex_id,
            "running": True,
            "ended": False,
            "end_reason": "",
            "exit_code": None,
            "started_at": now_iso(),
            "ended_at": None,
        })

        try:
            exercise_proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            exercise_reader_thread = threading.Thread(target=_exercise_reader, args=(exercise_proc,), daemon=True)
            exercise_reader_thread.start()
            return jsonify({"ok": True, "exercise_id": ex_id, "started": True, "path": script_path})
        except Exception as e:
            exercise_proc = None
            exercise_status.update({
                "running": False,
                "ended": True,
                "end_reason": "error",
                "exit_code": -1,
                "ended_at": now_iso(),
            })
            return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/exercise_stop", methods=["POST"])
def api_exercise_stop():
    stopped = stop_current_exercise()
    return jsonify({"ok": True, "stopped": bool(stopped)})

@app.route("/api/exercise_status", methods=["GET"])
def api_exercise_status():
    return jsonify({"ok": True, **exercise_status})

@app.route("/api/exercise_logs")
def api_exercise_logs():
    with exercise_log_lock:
        return jsonify({"ok": True, "stdout": "\n".join(exercise_stdout), "stderr": "\n".join(exercise_stderr)})

# ────────────────────────────────────────────────
#   CLEANUP
# ────────────────────────────────────────────────
def _cleanup():
    try:
        stop_all_tools("server cleanup")
    except Exception:
        pass
    try:
        stop_current_exercise()
    except Exception:
        pass
    try:
        if mqtt_client:
            mqtt_client.loop_stop()
    except Exception:
        pass


def _server_signal_cleanup(signum, frame):
    name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n[SERVER] {name} received -> cleanup")
    _cleanup()
    raise SystemExit(0)

signal.signal(signal.SIGINT, _server_signal_cleanup)
signal.signal(signal.SIGTERM, _server_signal_cleanup)

atexit.register(_cleanup)

# ────────────────────────────────────────────────
#   START
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 80)
    print("TrainerKit Tools Dashboard")
    print("Open: http://192.168.4.1:5000")
    print("Template Dir:", TEMPLATE_DIR)
    print("I2C Mux:", "Enabled" if USE_MUX else "Disabled")
    print("LCD MUX CH:", LCD_MUX_CH, "MPU CH:", MPU_MUX_CH, "BMP CH:", BMP_MUX_CH)
    print("BUZZER_ACTIVE_LOW:", BUZZER_ACTIVE_LOW)
    print("LED pins: RED=D5 GREEN=D6 ORANGE=D13")
    print("Voice triggers:", sorted(list(VOICE_TRIGGERS)) + ["hello hello", "open open"])
    print("=" * 80)

    start_a5_mqtt()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)