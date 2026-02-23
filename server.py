from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging
import os

# ────────────────────────────────────────────────
# Conditional imports
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

# LCD via smbus2 + RPLCD
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    SENSORS_AVAILABLE["LCD"] = True
except Exception:
    SENSORS_AVAILABLE["LCD"] = False

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
# App + globals
# ────────────────────────────────────────────────
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

# ────────────────────────────────────────────────
# MUX (TCA9548A)
# ────────────────────────────────────────────────
USE_MUX = SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False)
MUX_ADDRESS = 0x70

# Your known-good channels (from scan)
LCD_MUX_CH = 0
MPU_MUX_CH = 1
BMP_MUX_CH = 2  # change if your BMP is on a different channel

tca = None

def init_mux():
    global tca, USE_MUX
    if not USE_MUX:
        return False
    try:
        with i2c_lock:
            i2c = board.I2C()
            tca = adafruit_tca9548a.TCA9548A(i2c, address=MUX_ADDRESS)
        print(f"[MUX] OK addr=0x{MUX_ADDRESS:02X}")
        return True
    except Exception as e:
        print("[MUX] init failed:", e)
        tca = None
        USE_MUX = False
        return False

if USE_MUX:
    init_mux()

# ────────────────────────────────────────────────
# State + data (MUST match HTML card ids)
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

    # tools
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
# LCD
# ────────────────────────────────────────────────
LCD_I2C_BUS = 1
LCD_ADDRS = [0x27, 0x3F]
LCD_COLS = 16
LCD_ROWS = 2

_lcd = None
_lcd_addr = None

def mux_select_channel_smbus(ch: int) -> bool:
    if not USE_MUX:
        return True
    try:
        with i2c_lock:
            with SMBus(LCD_I2C_BUS) as bus:
                bus.write_byte(MUX_ADDRESS, 1 << ch)
        return True
    except Exception as e:
        set_error("LCD_TOOL", f"mux select failed: {e}")
        return False

def lcd_get():
    global _lcd, _lcd_addr
    if not SENSORS_AVAILABLE.get("LCD"):
        set_error("LCD_TOOL", "LCD libs missing: pip install RPLCD smbus2")
        return None
    if _lcd is not None:
        return _lcd

    if not mux_select_channel_smbus(LCD_MUX_CH):
        return None

    last = None
    for addr in LCD_ADDRS:
        try:
            with i2c_lock:
                _lcd = CharLCD("PCF8574", address=addr, port=LCD_I2C_BUS, cols=LCD_COLS, rows=LCD_ROWS, charmap="A00")
                _lcd.clear()
            _lcd_addr = addr
            clear_error("LCD_TOOL")
            print(f"[LCD] OK addr=0x{addr:02X} ch={LCD_MUX_CH if USE_MUX else 'direct'}")
            return _lcd
        except Exception as e:
            _lcd = None
            last = e

    set_error("LCD_TOOL", f"LCD init failed: {last}")
    return None

def lcd_write(line1="", line2=""):
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_channel_smbus(LCD_MUX_CH):
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
        set_error("LCD_TOOL", f"LCD write failed: {e}")
        return False

def lcd_clear():
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_channel_smbus(LCD_MUX_CH):
        return False
    try:
        with i2c_lock:
            lcd.clear()
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_error("LCD_TOOL", f"LCD clear failed: {e}")
        return False

# ────────────────────────────────────────────────
# Tools: LEDs + Active buzzer
# ────────────────────────────────────────────────
LED_RED_PIN    = board.D5  if SENSORS_AVAILABLE.get("board") else None
LED_ORANGE_PIN = board.D6  if SENSORS_AVAILABLE.get("board") else None
LED_GREEN_PIN  = board.D13 if SENSORS_AVAILABLE.get("board") else None

BUZZER_PIN = board.D16 if SENSORS_AVAILABLE.get("board") else None
BUZZER_ACTIVE_LOW = True

led_red = led_orange = led_green = buzzer = None

def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = bool(initial)
    return io

def init_tools_outputs():
    global led_red, led_orange, led_green, buzzer
    if not SENSORS_AVAILABLE.get("board"):
        set_error("LED_TOOL", "board not available")
        set_error("BUZZER", "board not available")
        return False
    try:
        if led_red is None and LED_RED_PIN is not None:
            led_red = make_out(LED_RED_PIN, False)
        if led_orange is None and LED_ORANGE_PIN is not None:
            led_orange = make_out(LED_ORANGE_PIN, False)
        if led_green is None and LED_GREEN_PIN is not None:
            led_green = make_out(LED_GREEN_PIN, False)

        if buzzer is None and BUZZER_PIN is not None:
            off_value = True if BUZZER_ACTIVE_LOW else False
            buzzer = make_out(BUZZER_PIN, off_value)
            sensor_data["BUZZER"]["on"] = False
            sensor_data["BUZZER"]["last_update"] = now_iso()
            clear_error("BUZZER")

        return True
    except Exception as e:
        set_error("LED_TOOL", f"init failed: {e}")
        set_error("BUZZER", f"init failed: {e}")
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
# Sensor instances/pins
# ────────────────────────────────────────────────
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

# ────────────────────────────────────────────────
# Sensor init functions
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
            else:
                mpu = adafruit_mpu6050.MPU6050(board.I2C())
        clear_error("MPU6050")
        print("[MPU6050] OK")
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
                else:
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=addr)
                bmp.sea_level_pressure = 1013.25
            clear_error("BMP280")
            print(f"[BMP280] OK addr=0x{addr:02X} ch={BMP_MUX_CH if USE_MUX else 'direct'}")
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
        pir_pin = digitalio.DigitalInOut(board.D18)
        pir_pin.direction = digitalio.Direction.INPUT
        try:
            pir_pin.pull = digitalio.Pull.DOWN
        except Exception:
            pass
        clear_error("PIR")
        print("[PIR] OK D18")
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
        mq_pin = digitalio.DigitalInOut(board.D17)  # MQ DO pin
        mq_pin.direction = digitalio.Direction.INPUT
        clear_error("MHMQ")
        print("[MHMQ] OK D17")
        return True
    except Exception as e:
        mq_pin = None
        set_error("MHMQ", f"init failed: {e}")
        return False

# Gas sampling
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

def set_relay_channel(channel: int, on: bool):
    if channel not in relay_pins:
        return False
    relay_pins[channel].value = (not on)  # active-low
    sensor_data["Relay"][f"ch{channel}"] = bool(on)
    sensor_data["Relay"]["last_update"] = now_iso()
    clear_error("Relay")
    return True

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

def stop_servo_pwm():
    global servo_pwm
    if servo_pwm is not None:
        try:
            servo_pwm.duty_cycle = 0
            servo_pwm.deinit()
        except Exception:
            pass
        servo_pwm = None

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

# ────────────────────────────────────────────────
# Background sensor reader
# ────────────────────────────────────────────────
threads = {}
running_flags = {}

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

            elif sensor_name == "BMP280" and bmp:
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

            elif sensor_name == "PIR" and pir_pin:
                state = bool(pir_pin.value)
                if state and not last_pir_state:
                    motion_count += 1
                last_pir_state = state
                sensor_data["PIR"].update({"motion": state, "count": int(motion_count), "last_update": now, "error": ""})
                clear_error("PIR")

            elif sensor_name == "ULTRASONIC" and ultra_trig and ultra_echo:
                dist = measure_distance(ultra_trig, ultra_echo)
                sensor_data["ULTRASONIC"].update({"distance_cm": dist, "last_update": now, "error": ""})
                clear_error("ULTRASONIC")

            elif sensor_name == "MHMQ" and mq_pin:
                lvl = read_gas_level_percent()
                detected = (lvl is not None and lvl >= GAS_ALERT_PERCENT)
                sensor_data["MHMQ"].update({"gas_detected": bool(detected), "level_percent": lvl, "last_update": now, "error": ""})
                clear_error("MHMQ")

        except Exception as e:
            set_error(sensor_name, e)

        time.sleep(1.0)

# ────────────────────────────────────────────────
# Routes (static)
# ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE_DIR, "static", "template"), "tools.html")

@app.route("/static/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static/css"), filename)

@app.route("/static/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static/js"), filename)

@app.route("/static/images/<path:filename>")
def serve_images(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static/images"), filename)

# ────────────────────────────────────────────────
# API
# ────────────────────────────────────────────────
@app.route("/api/sensors")
def get_sensors():
    resp = sensor_state.copy()
    resp["data"] = sensor_data.copy()
    resp["_meta"] = {
        "use_mux": bool(USE_MUX),
        "mux_addr": hex(MUX_ADDRESS),
        "lcd_ch": LCD_MUX_CH,
        "mpu_ch": MPU_MUX_CH,
        "bmp_ch": BMP_MUX_CH,
        "lcd_addr": hex(_lcd_addr) if _lcd_addr else None,
        "buzzer_active_low": BUZZER_ACTIVE_LOW,
    }
    return jsonify(resp)

# VERY IMPORTANT: check what IDs your UI must use
@app.get("/api/debug/keys")
def api_debug_keys():
    return jsonify({
        "sensor_state_keys": list(sensor_state.keys()),
        "sensor_data_keys": list(sensor_data.keys()),
        "note": "Your HTML card id MUST match these keys exactly."
    })

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    data = request.json or {}
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"ok": False, "error": f"Unknown sensor id '{sensor}'"}), 400

    # If BUZZER card gets clicked, toggle it too
    if sensor == "BUZZER":
        cur = bool(sensor_data["BUZZER"].get("on", False))
        target = not cur
        ok = set_buzzer(target)
        return jsonify({"ok": ok, "sensor": "BUZZER", "active": True, "on": target, "error": sensor_data["BUZZER"]["error"]})

    # tool cards are controlled via their endpoints
    if sensor in ("LED_TOOL", "LCD_TOOL"):
        return jsonify({"ok": True, "sensor": sensor, "active": True})

    # flip state
    sensor_state[sensor] = not sensor_state[sensor]
    active = sensor_state[sensor]

    # Relay toggles all channels
    if sensor == "Relay":
        if active and not ensure_sensor_init("Relay"):
            sensor_state[sensor] = False
            return jsonify({"ok": False, "error": sensor_data["Relay"]["error"]}), 500
        for ch in (1, 2, 3, 4):
            set_relay_channel(ch, active)
        return jsonify({"ok": True, "sensor": sensor, "active": active})

    # Servo on -> 90, off -> 0 then stop PWM
    if sensor == "servomotor":
        if active:
            if not ensure_sensor_init("servomotor"):
                sensor_state[sensor] = False
                return jsonify({"ok": False, "error": sensor_data["servomotor"]["error"]}), 500
            set_servo_angle(90)
        else:
            set_servo_angle(0)
            time.sleep(0.5)
            stop_servo_pwm()
        return jsonify({"ok": True, "sensor": sensor, "active": active})

    # Start/stop threads for sensors
    if active:
        if not ensure_sensor_init(sensor):
            sensor_state[sensor] = False
            return jsonify({"ok": False, "error": sensor_data[sensor]["error"]}), 500

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
    ok = set_led(color, target)

    if not ok:
        return jsonify({"ok": False, "error": sensor_data["LED_TOOL"]["error"] or "LED failed"}), 500
    return jsonify({"ok": True, "all": sensor_data["LED_TOOL"]})

@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode")  # on/off/toggle/beep/force_off

    if mode not in ("on", "off", "toggle", "beep", "force_off"):
        return jsonify({"ok": False, "error": "Invalid"}), 400

    if mode == "force_off":
        ok = set_buzzer(False)
        return jsonify({"ok": ok, "on": False, "error": sensor_data["BUZZER"]["error"]})

    if mode == "beep":
        ok = beep(count=int(data.get("count", 2)), on_ms=int(data.get("on_ms", 120)), off_ms=int(data.get("off_ms", 120)))
        return jsonify({"ok": ok, "on": False, "error": sensor_data["BUZZER"]["error"]})

    cur = bool(sensor_data["BUZZER"].get("on", False))
    target = (not cur) if mode == "toggle" else (mode == "on")
    ok = set_buzzer(target)
    return jsonify({"ok": ok, "on": target, "error": sensor_data["BUZZER"]["error"]})

@app.route("/api/lcd", methods=["POST"])
def api_lcd():
    data = request.json or {}
    if data.get("clear"):
        ok = lcd_clear()
        if not ok:
            return jsonify({"ok": False, "error": sensor_data["LCD_TOOL"]["error"] or "LCD failed"}), 500
        return jsonify({"ok": True, "line1": "", "line2": ""})

    line1 = str(data.get("line1", ""))
    line2 = str(data.get("line2", ""))
    ok = lcd_write(line1, line2)
    if not ok:
        return jsonify({"ok": False, "error": sensor_data["LCD_TOOL"]["error"] or "LCD failed"}), 500
    return jsonify({"ok": True, "line1": line1, "line2": line2})

# ────────────────────────────────────────────────
# START
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 80)
    print("TrainerKit Tools Dashboard")
    print("Open: http://localhost:5000")
    print("I2C Mux:", "Enabled" if USE_MUX else "Disabled")
    print("LCD CH:", LCD_MUX_CH, "MPU CH:", MPU_MUX_CH, "BMP CH:", BMP_MUX_CH)
    print("BUZZER_ACTIVE_LOW:", BUZZER_ACTIVE_LOW)
    print("=" * 80)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)