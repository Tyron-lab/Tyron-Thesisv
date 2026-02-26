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

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
#   APP + GLOBALS
# ────────────────────────────────────────────────
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "static", "template")

# I2C lock is CRITICAL: BMP/MPU (Blinka I2C) + LCD (smbus2) will fight otherwise
i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

# ────────────────────────────────────────────────
#   SENSOR DATA/STATE (must exist before set_error)
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

    "LED_TOOL":   True,
    "BUZZER":     True,
    "LCD_TOOL":   True,
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

    "LED_TOOL":   {"red": False, "orange": False, "green": False, "last_update": None, "error": ""},
    "BUZZER":     {"on": False, "last_update": None, "error": ""},
    "LCD_TOOL":   {"line1": "", "line2": "", "last_update": None, "error": ""},
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

# ────────────────────────────────────────────────
#   EXERCISE MAP (RUN PY FILES FROM FOLDERS)
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

    "a5-ex21": os.path.join(BASE_DIR, "activity5", "Exercise21.py"),
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
#   MUX (TCA9548A) CONFIG
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
#   LCD CONFIG
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

def lcd_release():
    global _lcd
    try:
        if _lcd is not None:
            if mux_select_for_lcd():
                with i2c_lock:
                    _lcd.clear()
            _lcd = None
    except Exception:
        _lcd = None

# ────────────────────────────────────────────────
#   GPIO OUTPUTS (LEDs + BUZZER)
# ────────────────────────────────────────────────
LED_RED_PIN    = board.D5  if SENSORS_AVAILABLE.get("board") else None
LED_ORANGE_PIN = board.D6  if SENSORS_AVAILABLE.get("board") else None
LED_GREEN_PIN  = board.D13 if SENSORS_AVAILABLE.get("board") else None
BUZZER_PIN     = board.D16 if SENSORS_AVAILABLE.get("board") else None

BUZZER_ACTIVE_LOW = False

led_red = None
led_orange = None
led_green = None
buzzer = None

def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = bool(initial)
    return io

def release_tools_outputs():
    global led_red, led_orange, led_green, buzzer
    _safe_deinit(led_red); led_red = None
    _safe_deinit(led_orange); led_orange = None
    _safe_deinit(led_green); led_green = None
    _safe_deinit(buzzer); buzzer = None

# ✅ FIXED: retry if GPIO busy
def init_tools_outputs():
    global led_red, led_orange, led_green, buzzer
    if not SENSORS_AVAILABLE.get("board"):
        set_error("LED_TOOL", "board not available")
        set_error("BUZZER", "board not available")
        return False

    def _do_init():
        global led_red, led_orange, led_green, buzzer

        if led_red is None and LED_RED_PIN is not None:
            led_red = make_out(LED_RED_PIN, False)
        if led_orange is None and LED_ORANGE_PIN is not None:
            led_orange = make_out(LED_ORANGE_PIN, False)
        if led_green is None and LED_GREEN_PIN is not None:
            led_green = make_out(LED_GREEN_PIN, False)

        if buzzer is None and BUZZER_PIN is not None:
            off_value = True if BUZZER_ACTIVE_LOW else False
            buzzer = make_out(BUZZER_PIN, off_value)

    try:
        _do_init()
        return True
    except Exception as e:
        # likely "GPIO busy" or left open by previous script
        release_tools_outputs()
        time.sleep(0.05)
        try:
            _do_init()
            clear_error("LED_TOOL")
            clear_error("BUZZER")
            return True
        except Exception as e2:
            set_error("LED_TOOL", f"init failed: {e2}")
            set_error("BUZZER", f"init failed: {e2}")
            return False

def set_led(color: str, on: bool):
    if not init_tools_outputs():
        return False
    color = (color or "").lower()
    io = {"red": led_red, "orange": led_orange, "green": led_green}.get(color)
    if io is None:
        set_error("LED_TOOL", f"unknown color {color}")
        return False
    io.value = bool(on)
    sensor_data["LED_TOOL"][color] = bool(on)
    sensor_data["LED_TOOL"]["last_update"] = now_iso()
    clear_error("LED_TOOL")
    return True

def _buzzer_gpio_value(on: bool) -> bool:
    return (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)

def set_buzzer(on: bool):
    if not init_tools_outputs():
        return False
    if buzzer is None:
        set_error("BUZZER", "buzzer pin not set")
        return False
    try:
        buzzer.value = _buzzer_gpio_value(on)
        sensor_data["BUZZER"]["on"] = bool(on)
        sensor_data["BUZZER"]["last_update"] = now_iso()
        clear_error("BUZZER")
        return True
    except Exception as e:
        set_error("BUZZER", f"set failed: {e}")
        return False

def beep(count=2, on_ms=120, off_ms=120):
    if not init_tools_outputs():
        return False
    if buzzer is None:
        set_error("BUZZER", "buzzer pin not set")
        return False
    try:
        for _ in range(int(count)):
            set_buzzer(True)
            time.sleep(max(0.01, on_ms / 1000.0))
            set_buzzer(False)
            time.sleep(max(0.01, off_ms / 1000.0))
        set_buzzer(False)
        return True
    except Exception as e:
        set_error("BUZZER", f"beep failed: {e}")
        return False

# ────────────────────────────────────────────────
#   SENSOR THREADS / GPIO
# ────────────────────────────────────────────────
threads = {}
running_flags = {}

dht_device = None
mpu = None
bmp = None

pir_pin = None
motion_count = 0

ultra_trig = None
ultra_echo = None

mq_pin = None
relay_pins = {}

servo_pwm = None
SERVO_PIN = board.D12 if SENSORS_AVAILABLE.get("board") else None
MIN_PULSE = 500
MAX_PULSE = 2500
FREQUENCY = 50

def release_all_sensor_gpio():
    global pir_pin, ultra_trig, ultra_echo, mq_pin, relay_pins, servo_pwm

    for k in list(running_flags.keys()):
        running_flags[k] = False

    time.sleep(0.15)

    _safe_deinit(pir_pin); pir_pin = None
    _safe_deinit(ultra_trig); ultra_trig = None
    _safe_deinit(ultra_echo); ultra_echo = None
    _safe_deinit(mq_pin); mq_pin = None

    if relay_pins:
        for ch, io in list(relay_pins.items()):
            _safe_deinit(io)
        relay_pins = {}

    try:
        if servo_pwm is not None:
            servo_pwm.duty_cycle = 0
            servo_pwm.deinit()
    except Exception:
        pass
    servo_pwm = None

    release_tools_outputs()
    lcd_release()

    for s in ("MPU6050", "BMP280", "DHT11", "MHMQ", "PIR", "ULTRASONIC", "Relay", "servomotor"):
        sensor_state[s] = False

# ────────────────────────────────────────────────
# ✅ GLOBAL CLEANUP (fix GPIO busy forever)
# ────────────────────────────────────────────────
def stop_current_exercise():
    global exercise_proc, exercise_stop_requested
    with exercise_lock:
        if exercise_proc is None:
            return True
        try:
            exercise_stop_requested = True
            exercise_proc.terminate()
            try:
                exercise_proc.wait(timeout=2)
            except Exception:
                exercise_proc.kill()
            return True
        except Exception:
            return False

def cleanup_everything():
    try:
        stop_current_exercise()
    except Exception:
        pass
    try:
        release_all_sensor_gpio()
    except Exception:
        pass
    try:
        if mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    except Exception:
        pass

atexit.register(cleanup_everything)

def _handle_sig(*_):
    cleanup_everything()
    raise SystemExit(0)

try:
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)
except Exception:
    pass

# ────────────────────────────────────────────────
#   SENSOR INIT FUNCTIONS (unchanged from yours)
# ────────────────────────────────────────────────
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
            io.value = True
            relay_pins[ch] = io
        sensor_data["Relay"].update({"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": now_iso(), "error": ""})
        clear_error("Relay")
        print("[RELAY] OK 4ch")
        return True
    except Exception as e:
        relay_pins = {}
        set_error("Relay", f"init failed: {e}")
        return False

def init_servomotor():
    if not SENSORS_AVAILABLE.get("servomotor") or not SENSORS_AVAILABLE.get("board") or SERVO_PIN is None:
        set_error("servomotor", "servo not available")
        return False
    clear_error("servomotor")
    return True

def set_servo_angle(angle):
    global servo_pwm
    if not init_servomotor():
        return False

    if servo_pwm is None:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (angle / 180.0)
    duty = int((pulse_us / 20000.0) * 65535.0)
    servo_pwm.duty_cycle = duty

    sensor_data["servomotor"].update({"angle": angle, "last_update": now_iso(), "error": ""})
    return True

# ────────────────────────────────────────────────
#   GAS LEVEL
# ────────────────────────────────────────────────
GAS_SAMPLES = 20
GAS_SAMPLE_DELAY = 0.02
GAS_INVERT_DO = True
GAS_ALERT_PERCENT = 30

def read_gas_level_percent():
    if mq_pin is None:
        return None
    hits = 0
    for _ in range(GAS_SAMPLES):
        v = mq_pin.value
        if GAS_INVERT_DO:
            v = not v
        if v:
            hits += 1
        time.sleep(GAS_SAMPLE_DELAY)
    return int(round(100 * hits / GAS_SAMPLES))

def ensure_sensor_init(sensor: str) -> bool:
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
        return init_servomotor()
    return True

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
#   ROUTES (PAGES + STATIC + API + EXERCISES)
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

@app.route("/api/sensors")
def get_sensors():
    resp = sensor_state.copy()
    resp["data"] = sensor_data.copy()
    return jsonify(resp)

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    data = request.json or {}
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"ok": False, "error": "Unknown sensor"}), 400

    if sensor in ("LED_TOOL", "BUZZER", "LCD_TOOL"):
        return jsonify({"ok": True, "sensor": sensor, "active": True})

    sensor_state[sensor] = not sensor_state[sensor]
    active = sensor_state[sensor]

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

@app.route("/api/led", methods=["POST"])
def api_led():
    data = request.json or {}
    color = (data.get("color") or "").lower()
    action = data.get("action")

    if color not in ("red", "orange", "green") or action not in ("on", "off", "toggle"):
        return jsonify({"ok": False, "error": "Invalid"}), 400

    cur = bool(sensor_data["LED_TOOL"].get(color, False))
    target = (not cur) if action == "toggle" else (action == "on")

    if not set_led(color, target):
        return jsonify({"ok": False, "error": sensor_data["LED_TOOL"]["error"] or "LED failed"}), 500

    return jsonify({"ok": True, "all": sensor_data["LED_TOOL"]})

@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode")
    if mode not in ("on", "off", "toggle", "beep"):
        return jsonify({"ok": False, "error": "Invalid"}), 400

    if mode == "beep":
        count = int(data.get("count", 2))
        on_ms = int(data.get("on_ms", 120))
        off_ms = int(data.get("off_ms", 120))
        if not beep(count=count, on_ms=on_ms, off_ms=off_ms):
            return jsonify({"ok": False, "error": sensor_data["BUZZER"]["error"] or "Buzzer failed"}), 500
        return jsonify({"ok": True, "on": False, "active_low": BUZZER_ACTIVE_LOW})

    cur = bool(sensor_data["BUZZER"].get("on", False))
    target = (not cur) if mode == "toggle" else (mode == "on")

    if not set_buzzer(target):
        return jsonify({"ok": False, "error": sensor_data["BUZZER"]["error"] or "Buzzer failed"}), 500

    return jsonify({"ok": True, "on": target, "active_low": BUZZER_ACTIVE_LOW})

@app.route("/api/lcd", methods=["POST"])
def api_lcd():
    data = request.json or {}

    if data.get("clear"):
        if not lcd_clear():
            return jsonify({"ok": False, "error": sensor_data["LCD_TOOL"]["error"] or "LCD failed"}), 500
        return jsonify({"ok": True, "line1": "", "line2": ""})

    line1 = str(data.get("line1", ""))
    line2 = str(data.get("line2", ""))

    if not lcd_write(line1, line2):
        return jsonify({"ok": False, "error": sensor_data["LCD_TOOL"]["error"] or "LCD failed"}), 500

    return jsonify({"ok": True, "line1": line1, "line2": line2})

# ✅ NEW: Activity 5 API (ESP32 telemetry + commands)
@app.route("/api/a5/latest")
def api_a5_latest():
    with latest_a5_lock:
        return jsonify({"ok": True, **latest_a5})

@app.route("/api/a5/command", methods=["POST"])
def api_a5_command():
    data = request.json or {}
    if mqtt_client is None:
        return jsonify({"ok": False, "error": "MQTT not started"}), 500
    try:
        mqtt_client.publish(A5_TOPIC_CMD, json.dumps(data))
        return jsonify({"ok": True, "topic": A5_TOPIC_CMD, "sent": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ────────────────────────────────────────────────
#   EXERCISE RUNNER (same as yours)
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
                for line in proc.stderr.readlines():
                    _append_log(stderr_line=line)
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

@app.route("/api/exercise", methods=["POST"])
def api_exercise_run():
    global exercise_proc, exercise_reader_thread, exercise_stop_requested

    data = request.json or {}
    ex_id = data.get("exercise_id")

    if not ex_id or ex_id not in EXERCISE_MAP:
        return jsonify({"ok": False, "error": "Unknown exercise_id"}), 400

    script_path = EXERCISE_MAP[ex_id]
    if not os.path.exists(script_path):
        return jsonify({"ok": False, "error": f"File not found: {script_path}"}), 404

    with exercise_lock:
        if exercise_proc is not None and exercise_proc.poll() is None:
            stop_current_exercise()

        # release GPIO so scripts can reuse
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
    ok = stop_current_exercise()
    return jsonify({"ok": bool(ok), "stopped": bool(ok)})

@app.route("/api/exercise_status")
def api_exercise_status():
    with exercise_lock:
        return jsonify({"ok": True, **exercise_status})

@app.route("/api/exercise_logs")
def api_exercise_logs():
    with exercise_log_lock:
        return jsonify({
            "ok": True,
            "stdout": "\n".join(exercise_stdout),
            "stderr": "\n".join(exercise_stderr),
        })

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
    print("=" * 80)

    # ✅ Start MQTT bridge so Flask can read ESP32 data
    start_a5_mqtt()

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)