# server.py — TrainerKit Tools Dashboard (FULL UPDATE)
# Voice trigger: "open" / "hello" / "hello hello" (no clap)
# Live audio wave: /api/mic_wave returns last N RMS samples
# Uses queue worker to avoid sounddevice input overflow

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

# ✅ NEW
import json
import atexit
import paho.mqtt.client as mqtt

# ✅ MIC + VOSK
import queue

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

# I2C lock is CRITICAL
i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ────────────────────────────────────────────────
#   SHARED "FOCUS" STATE (multi-phone lock)
#   Used by Activities pages to lock UI to one running exercise across devices
#   API:
#     GET  /api/focus
#     POST /api/focus   {"exercise_id":"a1-ex1","running":true,"by":"..."}
# ────────────────────────────────────────────────
FOCUS_LOCK = threading.Lock()
focus_state = {
    "running": False,
    "exercise_id": None,
    "since": None,
    "by": None,
}

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
    "LCD_TOOL":   {"line1": "", "line2": "", "last_update": None, "error": ""},

    # NEW fields: command + command_at
    "MIC":        {
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
# ✅ ACTIVITY 5 MQTT BRIDGE (ESP32)
# ────────────────────────────────────────────────
MQTT_HOST = "192.168.4.1"
MQTT_PORT = 1883

A5_TOPIC_TELE = "trainerkit/a5/telemetry"
A5_TOPIC_CMD  = "trainerkit/a5/command"
A5_TOPIC_STAT = "trainerkit/a5/status"

latest_a5 = {"connected": False, "last_update": None, "payload": None, "raw": None}
latest_a5_lock = threading.Lock()
mqtt_client = None

def _a5_on_connect(client, userdata, flags, rc):
    print("[A5 MQTT] connected rc=", rc)
    with latest_a5_lock:
        latest_a5["connected"] = (rc == 0)
    if rc == 0:
        client.subscribe(A5_TOPIC_TELE)
        client.subscribe(A5_TOPIC_STAT)

def _a5_on_message(client, userdata, msg):
    try:
        raw = msg.payload.decode("utf-8", errors="replace")
        payload = None
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None

        with latest_a5_lock:
            latest_a5["last_update"] = now_iso()
            latest_a5["raw"] = raw
            latest_a5["payload"] = payload
    except Exception as e:
        print("[A5 MQTT] message error:", e)

def start_a5_mqtt():
    global mqtt_client
    try:
        c = mqtt.Client()
        c.on_connect = _a5_on_connect
        c.on_message = _a5_on_message
        c.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        c.loop_start()
        mqtt_client = c
        print("[A5 MQTT] loop started")
    except Exception as e:
        print("[A5 MQTT] start failed:", e)
        mqtt_client = None

def a5_send_cmd(payload: dict):
    if mqtt_client is None:
        raise RuntimeError("MQTT not started")
    mqtt_client.publish(A5_TOPIC_CMD, json.dumps(payload))

# ────────────────────────────────────────────────
#   EXERCISE MAP
# ────────────────────────────────────────────────
EXERCISE_MAP = {
    "a1-ex1": os.path.join(BASE_DIR, "activity1", "Exercise1.py"),
    "a1-ex2": os.path.join(BASE_DIR, "activity1", "Exercise2.py"),
    "a1-ex3": os.path.join(BASE_DIR, "activity1", "Exercise3.py"),
    "a1-ex4": os.path.join(BASE_DIR, "activity1", "Exercise4.py"),
    "a1-ex5": os.path.join(BASE_DIR, "activity1", "Exercise5.py"),

    "a2-ex6":  os.path.join(BASE_DIR, "activity2", "Exercise6.py"),
    "a2-ex7":  os.path.join(BASE_DIR, "activity2", "Exercise7.py"),
    "a2-ex8":  os.path.join(BASE_DIR, "activity2", "Exercise8.py"),
    "a2-ex9":  os.path.join(BASE_DIR, "activity2", "Exercise9.py"),
    "a2-ex10": os.path.join(BASE_DIR, "activity2", "Exercise10.py"),

    "a3-ex11": os.path.join(BASE_DIR, "activity3", "Exercise11.py"),
    "a3-ex12": os.path.join(BASE_DIR, "activity3", "Exercise12.py"),
    "a3-ex13": os.path.join(BASE_DIR, "activity3", "Exercise13.py"),
    "a3-ex14": os.path.join(BASE_DIR, "activity3", "Exercise14.py"),
    "a3-ex15": os.path.join(BASE_DIR, "activity3", "Exercise15.py"),

    "a4-ex16": os.path.join(BASE_DIR, "activity4", "Exercise16.py"),
    "a4-ex17": os.path.join(BASE_DIR, "activity4", "Exercise17.py"),
    "a4-ex18": os.path.join(BASE_DIR, "activity4", "Exercise18.py"),
    "a4-ex19": os.path.join(BASE_DIR, "activity4", "Exercise19.py"),
    "a4-ex20": os.path.join(BASE_DIR, "activity4", "Exercise20.py"),

    "a5-ex22": os.path.join(BASE_DIR, "activity5", "Exercise22.py"),
    "a5-ex23": os.path.join(BASE_DIR, "activity5", "Exercise23.py"),
    "a5-ex24": os.path.join(BASE_DIR, "activity5", "Exercise24.py"),
    "a5-ex25": os.path.join(BASE_DIR, "activity5", "Exercise25.py"),
}

exercise_proc = None
exercise_lock = threading.Lock()

exercise_status = {
    "exercise_id": None,
    "running": False,
    "ended": False,
    "end_reason": "",
    "exit_code": None,
    "started_at": None,
    "ended_at": None,
}
exercise_stdout = deque(maxlen=600)
exercise_stderr = deque(maxlen=600)
exercise_log_lock = threading.Lock()
exercise_reader_thread = None
exercise_stop_requested = False

def _python_cmd():
    return sys.executable

def _safe_deinit(io):
    try:
        if io is not None:
            io.deinit()
    except Exception:
        pass

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

if SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False):
    init_mux()

# ────────────────────────────────────────────────
#   LCD TOOL (RPLCD)
# ────────────────────────────────────────────────
lcd = None
LCD_ADDRS = [0x27, 0x3F]
LCD_COLS = 16
LCD_ROWS = 2

def init_lcd():
    global lcd
    if not SENSORS_AVAILABLE.get("LCD"):
        set_error("LCD_TOOL", "LCD libs not available")
        return False
    if not SENSORS_AVAILABLE.get("board"):
        set_error("LCD_TOOL", "board not available")
        return False
    if lcd is not None:
        return True

    last = None
    for addr in LCD_ADDRS:
        try:
            with i2c_lock:
                # RPLCD handles I2C internally; MUX isn’t used here by RPLCD directly.
                lcd = CharLCD("PCF8574", address=addr, port=1, cols=LCD_COLS, rows=LCD_ROWS)
                lcd.clear()
            sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})
            clear_error("LCD_TOOL")
            print(f"[LCD] OK addr=0x{addr:02X}")
            return True
        except Exception as e:
            lcd = None
            last = e

    set_error("LCD_TOOL", f"init failed: {last}")
    return False

def lcd_clear():
    if not init_lcd():
        return False
    try:
        with i2c_lock:
            lcd.clear()
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_error("LCD_TOOL", e)
        return False

def lcd_write(line1="", line2=""):
    if not init_lcd():
        return False
    try:
        with i2c_lock:
            lcd.clear()
            lcd.cursor_pos = (0, 0)
            lcd.write_string((line1 or "")[:LCD_COLS].ljust(LCD_COLS))
            lcd.cursor_pos = (1, 0)
            lcd.write_string((line2 or "")[:LCD_COLS].ljust(LCD_COLS))
        sensor_data["LCD_TOOL"].update({"line1": line1, "line2": line2, "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_error("LCD_TOOL", e)
        return False

# ────────────────────────────────────────────────
#   BUZZER
# ────────────────────────────────────────────────
BUZZER_ACTIVE_LOW = True
buzzer_pin = None

def init_buzzer():
    global buzzer_pin
    if not SENSORS_AVAILABLE.get("board"):
        set_error("BUZZER", "board not available")
        return False
    if buzzer_pin is not None:
        return True
    try:
        buzzer_pin = digitalio.DigitalInOut(board.D21)
        buzzer_pin.direction = digitalio.Direction.OUTPUT
        buzzer_pin.value = True if BUZZER_ACTIVE_LOW else False  # OFF
        clear_error("BUZZER")
        print("[BUZZER] OK D21")
        return True
    except Exception as e:
        buzzer_pin = None
        set_error("BUZZER", f"init failed: {e}")
        return False

def set_buzzer(on: bool):
    if not init_buzzer():
        return False
    try:
        buzzer_pin.value = (not on) if BUZZER_ACTIVE_LOW else bool(on)
        sensor_data["BUZZER"].update({"on": bool(on), "last_update": now_iso(), "error": ""})
        clear_error("BUZZER")
        return True
    except Exception as e:
        set_error("BUZZER", e)
        return False

def beep(count=1, on_ms=100, off_ms=100):
    if not init_buzzer():
        return False
    try:
        for _ in range(int(count)):
            set_buzzer(True)
            time.sleep(on_ms / 1000.0)
            set_buzzer(False)
            time.sleep(off_ms / 1000.0)
        return True
    except Exception as e:
        set_error("BUZZER", e)
        return False

# ────────────────────────────────────────────────
#   SERVO
# ────────────────────────────────────────────────
SERVO_FREQ = 50
servo_pwm = None

def init_servo():
    global servo_pwm
    if not SENSORS_AVAILABLE.get("servomotor") or not SENSORS_AVAILABLE.get("board"):
        set_error("servomotor", "servo/board not available")
        return False
    if servo_pwm is not None:
        return True
    try:
        servo_pwm = pwmio.PWMOut(board.D18, frequency=SERVO_FREQ, duty_cycle=0)
        clear_error("servomotor")
        print("[SERVO] OK D18")
        return True
    except Exception as e:
        servo_pwm = None
        set_error("servomotor", f"init failed: {e}")
        return False

def set_servo_angle(angle: int):
    if not init_servo():
        return False
    try:
        a = max(0, min(180, int(angle)))
        # map 0..180 to duty cycle (approx 2.5%..12.5%)
        min_dc = int(65535 * 0.025)
        max_dc = int(65535 * 0.125)
        dc = min_dc + (max_dc - min_dc) * a // 180
        servo_pwm.duty_cycle = int(dc)
        sensor_data["servomotor"].update({"angle": a, "last_update": now_iso(), "error": ""})
        clear_error("servomotor")
        return True
    except Exception as e:
        set_error("servomotor", e)
        return False

def stop_servo():
    global servo_pwm
    try:
        if servo_pwm is not None:
            servo_pwm.duty_cycle = 0
            servo_pwm.deinit()
    except Exception:
        pass
    servo_pwm = None
    sensor_data["servomotor"].update({"angle": 0, "last_update": now_iso()})

# ────────────────────────────────────────────────
#   RELAY (4ch active-low)
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
            io.value = True  # OFF (active-low)
            relay_pins[ch] = io
        sensor_data["Relay"].update({"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": now_iso(), "error": ""})
        clear_error("Relay")
        print("[RELAY] OK 4ch")
        return True
    except Exception as e:
        relay_pins = {}
        set_error("Relay", f"init failed: {e}")
        return False

def set_all_relays(on: bool):
    if not init_relay():
        return False
    try:
        for ch, io in relay_pins.items():
            io.value = (not on)  # active-low
        sensor_data["Relay"].update({
            "ch1": bool(on), "ch2": bool(on), "ch3": bool(on), "ch4": bool(on),
            "last_update": now_iso(), "error": ""
        })
        clear_error("Relay")
        return True
    except Exception as e:
        set_error("Relay", e)
        return False

# ────────────────────────────────────────────────
#   PIR / ULTRASONIC / MQ / DHT / MPU / BMP
# ────────────────────────────────────────────────
pir_pin = None
ultra_trig = None
ultra_echo = None
mq_pin = None
dht_device = None
mpu = None
bmp = None

GAS_ALERT_PERCENT = 30

def init_dht():
    global dht_device
    if not SENSORS_AVAILABLE.get("DHT11") or not SENSORS_AVAILABLE.get("board"):
        set_error("DHT11", "DHT11/board not available")
        return False
    if dht_device is not None:
        return True
    try:
        dht_device = adafruit_dht.DHT11(board.D4)
        clear_error("DHT11")
        print("[DHT11] OK D4")
        return True
    except Exception as e:
        dht_device = None
        set_error("DHT11", f"init failed: {e}")
        return False

def init_mpu():
    global mpu
    if not SENSORS_AVAILABLE.get("MPU6050") or not SENSORS_AVAILABLE.get("board"):
        set_error("MPU6050", "MPU6050/board not available")
        return False
    if mpu is not None:
        return True
    try:
        with i2c_lock:
            if USE_MUX:
                if tca is None and not init_mux():
                    raise RuntimeError("MUX init failed")
                mpu = adafruit_mpu6050.MPU6050(tca[MPU_MUX_CH])
                print(f"[MPU6050] OK mux_ch={MPU_MUX_CH}")
            else:
                i2c = board.I2C()
                mpu = adafruit_mpu6050.MPU6050(i2c)
                print("[MPU6050] OK direct")
        clear_error("MPU6050")
        return True
    except Exception as e:
        mpu = None
        set_error("MPU6050", f"init failed: {e}")
        return False

def init_bmp():
    global bmp
    if not SENSORS_AVAILABLE.get("BMP280") or not SENSORS_AVAILABLE.get("board"):
        set_error("BMP280", "BMP280/board not available")
        return False
    if bmp is not None:
        return True

    last = None
    for addr in (0x76, 0x77):
        try:
            with i2c_lock:
                if USE_MUX:
                    if tca is None and not init_mux():
                        raise RuntimeError("MUX init failed")
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_MUX_CH], address=addr)
                    print(f"[BMP280] OK mux_ch={BMP_MUX_CH} addr=0x{addr:02X}")
                else:
                    i2c = board.I2C()
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                    print(f"[BMP280] OK direct addr=0x{addr:02X}")
                bmp.sea_level_pressure = 1013.25
            clear_error("BMP280")
            return True
        except Exception as e:
            bmp = None
            last = e

    set_error("BMP280", f"init failed: {last}")
    return False

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

def read_gas_level_percent():
    # Digital MQ style: 1=OK, 0=GAS (or vice versa) depends on module.
    # Here we fake a "percent" from digital: 0% or 100%.
    if mq_pin is None:
        return None
    try:
        raw = bool(mq_pin.value)
        # If your sensor is inverted, swap here.
        return 0 if raw else 100
    except Exception:
        return None

def ensure_sensor_init(sensor):
    if sensor == "DHT11":
        return init_dht()
    if sensor == "MPU6050":
        return init_mpu()
    if sensor == "BMP280":
        return init_bmp()
    if sensor == "PIR":
        return init_pir()
    if sensor == "ULTRASONIC":
        return init_ultrasonic()
    if sensor == "MHMQ":
        return init_mq()
    if sensor == "Relay":
        return init_relay()
    if sensor == "servomotor":
        return init_servo()
    if sensor == "BUZZER":
        return init_buzzer()
    if sensor == "LCD_TOOL":
        return init_lcd()
    if sensor == "MIC":
        return True
    return True

def release_all_sensor_gpio():
    global pir_pin, ultra_trig, ultra_echo, mq_pin, dht_device, mpu, bmp

    # Keep I2C lock safe
    try:
        _safe_deinit(pir_pin); pir_pin = None
    except Exception:
        pass
    try:
        _safe_deinit(ultra_trig); ultra_trig = None
        _safe_deinit(ultra_echo); ultra_echo = None
    except Exception:
        pass
    try:
        _safe_deinit(mq_pin); mq_pin = None
    except Exception:
        pass

    # DHT device
    try:
        if dht_device is not None:
            dht_device.exit()
    except Exception:
        pass
    dht_device = None

    # I2C devices: keep for speed; don’t force deinit
    # mpu / bmp can stay allocated; they’re protected by i2c_lock.

# ────────────────────────────────────────────────
#   SENSOR READER THREADS
# ────────────────────────────────────────────────
threads = {}
running_flags = {k: False for k in sensor_state.keys()}

def sensor_reader(sensor_name: str):
    last_pir_state = False
    motion_count = 0

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
                        temp = bmp.temperature
                        press = bmp.pressure
                        alt = getattr(bmp, "altitude", None)
                    sensor_data["BMP280"].update({
                        "temperature": round(temp, 1) if temp is not None else None,
                        "pressure": round(press, 1) if press is not None else None,
                        "altitude": round(alt, 1) if alt is not None else None,
                        "last_update": now, "error": ""
                    })
                    clear_error("BMP280")
                except Exception as e:
                    set_error("BMP280", e)

            elif sensor_name == "PIR" and pir_pin:
                state = bool(pir_pin.value)
                if state and not last_pir_state:
                    motion_count += 1
                sensor_data["PIR"].update({"motion": state, "count": int(motion_count), "last_update": now, "error": ""})
                clear_error("PIR")
                last_pir_state = state

            elif sensor_name == "ULTRASONIC" and ultra_trig and ultra_echo:
                dist = measure_distance(ultra_trig, ultra_echo)
                sensor_data["ULTRASONIC"].update({"distance_cm": dist, "last_update": now, "error": ""})
                clear_error("ULTRASONIC")

            elif sensor_name == "MHMQ" and mq_pin:
                level = read_gas_level_percent()
                detected = (level is not None and level >= GAS_ALERT_PERCENT)
                sensor_data["MHMQ"].update({"gas_detected": bool(detected), "level_percent": level, "last_update": now, "error": ""})
                clear_error("MHMQ")

        except Exception as e:
            set_error(sensor_name, e)

        time.sleep(1.0)

# ────────────────────────────────────────────────
#   ROUTES (PAGES + STATIC)
# ────────────────────────────────────────────────
@app.route("/")
def welcome_page():
    return send_from_directory(TEMPLATE_DIR, "welcome.html")

@app.route("/choices")
def choices_page():
    return send_from_directory(TEMPLATE_DIR, "choices.html")

@app.route("/tools")
def tools_page():
    return send_from_directory(TEMPLATE_DIR, "tools.html")

@app.route("/activityfolder")
def activityfolder_page():
    return send_from_directory(TEMPLATE_DIR, "activityfolder.html")

@app.route("/activity1")
def activity1_page():
    return send_from_directory(TEMPLATE_DIR, "activity1.html")

@app.route("/activity2")
def activity2_page():
    return send_from_directory(TEMPLATE_DIR, "activity2.html")

@app.route("/activity3")
def activity3_page():
    return send_from_directory(TEMPLATE_DIR, "activity3.html")

@app.route("/activity4")
def activity4_page():
    return send_from_directory(TEMPLATE_DIR, "activity4.html")

@app.route("/activity5")
def activity5_page():
    return send_from_directory(TEMPLATE_DIR, "activity5.html")

@app.route("/static/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "css"), filename)

@app.route("/static/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "js"), filename)

@app.route("/static/images/<path:filename>")
def serve_images(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "images"), filename)

# ────────────────────────────────────────────────
#   API: SHARED FOCUS (multi-phone lock)
# ────────────────────────────────────────────────
@app.route("/api/focus", methods=["GET", "POST"])
def api_focus():
    """Shared focus lock for multi-phone UI.

    POST:
      - running=true sets global focus to exercise_id
      - running=false clears focus (only if same exercise_id or exercise_id omitted)
    """
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
                    focus_state["running"] = False
                    focus_state["exercise_id"] = None
                    focus_state["since"] = None
                    focus_state["by"] = None

        return jsonify({"ok": True, **focus_state})

    with FOCUS_LOCK:
        return jsonify({**focus_state})

# ────────────────────────────────────────────────
#   API: SENSORS
# ────────────────────────────────────────────────
@app.route("/api/sensors")
def get_sensors():
    resp = sensor_state.copy()
    resp["data"] = sensor_data.copy()
    return jsonify(resp)

# NEW: live wave samples
MIC_LOCK = threading.Lock()
MIC_Q = queue.Queue(maxsize=80)
MIC_WORKER_THREAD = None
MIC_WORKER_RUN = False

MIC_WAVE = deque(maxlen=250)
MIC_WAVE_LOCK = threading.Lock()

VOSK_MODEL_PATH = os.environ.get(
    "VOSK_MODEL_PATH",
    os.path.join(BASE_DIR, "models", "vosk-model-small-en-us-0.15")
)
VOSK_MODEL = None
VOSK_REC = None
VOSK_LOCK = threading.Lock()

MIC_SR_CANDIDATES = [
    int(os.environ.get("MIC_SAMPLE_RATE", "48000")),
    48000,
    44100,
    16000,
]
VOSK_TARGET_SR = 16000

VOICE_TRIGGERS = {"open", "hello", "hey", "hi"}

def _detect_trigger(final_text: str) -> str:
    t = (final_text or "").strip().lower()
    if not t:
        return ""
    if t in VOICE_TRIGGERS:
        return t
    if "hello hello" in t:
        return "hello hello"
    if "open open" in t:
        return "open open"
    return ""

def _fast_resample_mono_float32(x: "np.ndarray", src_sr: int, dst_sr: int = 16000) -> "np.ndarray":
    if src_sr == dst_sr:
        return x
    if src_sr % dst_sr == 0:
        step = src_sr // dst_sr
        if step > 1:
            return x[::step].astype(np.float32, copy=False)
    if len(x) < 2:
        return x.astype(np.float32, copy=False)

    duration = len(x) / float(src_sr)
    dst_len = int(duration * dst_sr)
    if dst_len <= 1:
        return x[:1].astype(np.float32, copy=False)

    src_idx = np.linspace(0, len(x) - 1, num=len(x), dtype=np.float64)
    dst_idx = np.linspace(0, len(x) - 1, num=dst_len, dtype=np.float64)
    y = np.interp(dst_idx, src_idx, x).astype(np.float32)
    return y

def vosk_init():
    global VOSK_MODEL, VOSK_REC
    if not SENSORS_AVAILABLE.get("VOSK", False):
        set_error("MIC", "vosk not installed. pip install vosk")
        return False
    if not os.path.isdir(VOSK_MODEL_PATH):
        set_error("MIC", f"Vosk model not found: {VOSK_MODEL_PATH}")
        return False

    with VOSK_LOCK:
        if VOSK_MODEL is None:
            VOSK_MODEL = Model(VOSK_MODEL_PATH)
        VOSK_REC = KaldiRecognizer(VOSK_MODEL, VOSK_TARGET_SR)
        try:
            VOSK_REC.SetWords(False)
        except Exception:
            pass

    sensor_data["MIC"]["listening_rate"] = VOSK_TARGET_SR
    clear_error("MIC")
    return True

MIC_STREAM = None

def _mic_worker_loop(src_sr: int):
    global MIC_WORKER_RUN

    with VOSK_LOCK:
        if VOSK_MODEL is not None:
            globals()["VOSK_REC"] = KaldiRecognizer(VOSK_MODEL, VOSK_TARGET_SR)

    while MIC_WORKER_RUN:
        try:
            item = MIC_Q.get(timeout=0.25)
        except queue.Empty:
            continue
        if item is None:
            continue

        try:
            pcm16_bytes, rms, peak, ts = item

            with MIC_WAVE_LOCK:
                MIC_WAVE.append(float(rms))

            x16 = np.frombuffer(pcm16_bytes, dtype=np.int16)
            x = (x16.astype(np.float32) / 32768.0)

            y = _fast_resample_mono_float32(x, src_sr, VOSK_TARGET_SR)
            y16 = np.clip(y * 32767.0, -32768, 32767).astype(np.int16).tobytes()

            partial_txt = ""
            final_txt = None

            with VOSK_LOCK:
                if VOSK_REC is not None:
                    ok = VOSK_REC.AcceptWaveform(y16)
                    if ok:
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
    last_err = None

    for sr in MIC_SR_CANDIDATES:
        try:
            sd.check_input_settings(samplerate=sr, channels=1, dtype="int16")
            src_sr = sr
            break
        except Exception as e:
            last_err = e

    if src_sr is None:
        set_error("MIC", f"No valid sample rate. Last: {last_err}")
        return False

    def _audio_cb(indata, frames, time_info, status):
        try:
            if status:
                pass
            x16 = indata[:, 0].astype(np.int16, copy=False)
            xf = (x16.astype(np.float32) / 32768.0)
            rms = float(np.sqrt(np.mean(xf * xf)) + 1e-12)
            peak = float(np.max(np.abs(xf)) + 1e-12)
            ts = now_iso()

            try:
                MIC_Q.put_nowait((x16.tobytes(), rms, peak, ts))
            except queue.Full:
                pass
        except Exception:
            pass

    try:
        with MIC_LOCK:
            MIC_STREAM = sd.InputStream(
                samplerate=src_sr,
                channels=1,
                dtype="int16",
                blocksize=0,
                callback=_audio_cb,
            )
            MIC_STREAM.start()

        sensor_data["MIC"]["sample_rate"] = src_sr
        clear_error("MIC")

        MIC_WORKER_RUN = True
        MIC_WORKER_THREAD = threading.Thread(target=_mic_worker_loop, args=(src_sr,), daemon=True)
        MIC_WORKER_THREAD.start()

        return True
    except Exception as e:
        set_error("MIC", e)
        mic_stop()
        return False

@app.route("/api/mic_wave")
def api_mic_wave():
    with MIC_WAVE_LOCK:
        wave = list(MIC_WAVE)
    return jsonify({
        "ok": True,
        "active": bool(sensor_state.get("MIC")),
        "wave": wave[-200:],
        "rms": sensor_data["MIC"].get("rms"),
        "peak": sensor_data["MIC"].get("peak"),
        "text": sensor_data["MIC"].get("text"),
        "partial": sensor_data["MIC"].get("partial"),
        "command": sensor_data["MIC"].get("command"),
        "command_at": sensor_data["MIC"].get("command_at"),
        "error": sensor_data["MIC"].get("error"),
        "last_update": sensor_data["MIC"].get("last_update"),
    })

@app.route("/api/mic_command", methods=["GET", "POST"])
def api_mic_command():
    if request.method == "POST":
        data = request.json or {}
        if data.get("clear"):
            sensor_data["MIC"]["command"] = ""
            sensor_data["MIC"]["command_at"] = None
        return jsonify({"ok": True, "cleared": True})

    return jsonify({
        "ok": True,
        "command": sensor_data["MIC"].get("command", ""),
        "command_at": sensor_data["MIC"].get("command_at"),
        "text": sensor_data["MIC"].get("text", ""),
    })

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    data = request.json or {}
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"ok": False, "error": "Unknown sensor"}), 400

    sensor_state[sensor] = not bool(sensor_state[sensor])
    active = bool(sensor_state[sensor])

    if sensor == "BUZZER":
        ok = set_buzzer(active)
        return jsonify({"ok": bool(ok), "sensor": sensor, "active": active,
                        "on": sensor_data["BUZZER"]["on"], "active_low": BUZZER_ACTIVE_LOW,
                        "error": sensor_data["BUZZER"]["error"] if not ok else ""}), (200 if ok else 500)

    if sensor == "LCD_TOOL":
        if active:
            ok = lcd_write("LCD READY", now_iso()[-8:])
        else:
            ok = lcd_clear()
        return jsonify({"ok": bool(ok), "sensor": sensor, "active": active,
                        "line1": sensor_data["LCD_TOOL"]["line1"], "line2": sensor_data["LCD_TOOL"]["line2"],
                        "error": sensor_data["LCD_TOOL"]["error"] if not ok else ""}), (200 if ok else 500)

    if sensor == "Relay":
        ok = set_all_relays(active)
        if not ok:
            sensor_state[sensor] = False
        return jsonify({"ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
                        "relay": sensor_data["Relay"], "error": sensor_data["Relay"]["error"] if not ok else ""}), (200 if ok else 500)

    if sensor == "servomotor":
        if active:
            ok = set_servo_angle(90)
            if not ok:
                sensor_state[sensor] = False
        else:
            stop_servo()
            sensor_data["servomotor"].update({"angle": 0, "last_update": now_iso(), "error": ""})
            ok = True
        return jsonify({"ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
                        "servo": sensor_data["servomotor"], "error": sensor_data["servomotor"]["error"] if not ok else ""}), (200 if ok else 500)

    if sensor == "MIC":
        if active:
            ok = mic_start()
            if not ok:
                sensor_state[sensor] = False
        else:
            mic_stop()
            ok = True
        return jsonify({"ok": bool(ok), "sensor": sensor, "active": bool(sensor_state[sensor]),
                        "mic": sensor_data["MIC"], "error": sensor_data["MIC"]["error"] if not ok else ""}), (200 if ok else 500)

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
        ok = beep(count=int(data.get("count", 2)), on_ms=int(data.get("on_ms", 140)), off_ms=int(data.get("off_ms", 140)))
        return jsonify({"ok": bool(ok), "on": False, "error": sensor_data["BUZZER"]["error"] if not ok else ""}), (200 if ok else 500)
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
#   API: Activity 5 MQTT endpoints
# ────────────────────────────────────────────────
@app.route("/api/a5/latest")
def api_a5_latest():
    with latest_a5_lock:
        return jsonify({"ok": True, **latest_a5})

@app.route("/api/a5/command", methods=["POST"])
def api_a5_command():
    try:
        payload = request.json or {}
        a5_send_cmd(payload)
        return jsonify({"ok": True, "sent": payload})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ────────────────────────────────────────────────
#   EXERCISE RUNNER
# ────────────────────────────────────────────────
def _append_log(stdout_line=None, stderr_line=None):
    with exercise_log_lock:
        if stdout_line is not None:
            exercise_stdout.append(stdout_line.rstrip("\n"))
        if stderr_line is not None:
            exercise_stderr.append(stderr_line.rstrip("\n"))

def _exercise_reader(proc: subprocess.Popen):
    global exercise_proc
    try:
        while proc.poll() is None:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                _append_log(stdout_line=line)

            eline = proc.stderr.readline() if proc.stderr else ""
            if eline:
                _append_log(stderr_line=eline)

            time.sleep(0.01)

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

@app.route("/api/exercise", methods=["POST"])
def api_exercise_run():
    global exercise_proc, exercise_reader_thread, exercise_stop_requested

    data = request.json or {}
    ex_id = data.get("exercise_id")

    if not ex_id:
        return jsonify({"ok": False, "error": "Missing exercise_id"}), 400

    # A5 EX21 = ESP32 streaming control (no local script)
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
        return jsonify({"ok": False, "error": "Unknown exercise_id"}), 400

    script_path = EXERCISE_MAP[ex_id]
    if not os.path.exists(script_path):
        return jsonify({"ok": False, "error": f"File not found: {script_path}"}), 404

    with exercise_lock:
        if exercise_proc is not None and exercise_proc.poll() is None:
            stop_current_exercise()

        release_all_sensor_gpio()

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
                [_python_cmd(), script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            exercise_reader_thread = threading.Thread(
                target=_exercise_reader, args=(exercise_proc,), daemon=True
            )
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
    with exercise_lock:
        current = exercise_status.get("exercise_id")
        running = bool(exercise_status.get("running"))

    if running and current == "a5-ex21":
        try:
            a5_send_cmd({"stream": "off"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        with exercise_lock:
            exercise_status.update({
                "running": False,
                "ended": True,
                "end_reason": "stopped",
                "exit_code": 0,
                "ended_at": now_iso(),
            })

        return jsonify({"ok": True, "stopped": True, "mode": "mqtt", "sent": {"stream": "off"}})

    ok = stop_current_exercise()
    return jsonify({"ok": bool(ok), "stopped": bool(ok)})

@app.route("/api/exercise_status")
def api_exercise_status():
    with exercise_lock:
        return jsonify({"ok": True, **exercise_status})

@app.route("/api/exercise_logs")
def api_exercise_logs():
    with exercise_log_lock:
        return jsonify({"ok": True, "stdout": "\n".join(exercise_stdout), "stderr": "\n".join(exercise_stderr)})

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
    print("Voice triggers:", sorted(list(VOICE_TRIGGERS)) + ["hello hello", "open open"])
    print("=" * 80)

    start_a5_mqtt()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)