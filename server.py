from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging
import os

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

# BMP280 (optional)
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

# TCA9548A I2C multiplexer support
try:
    import adafruit_tca9548a
    SENSORS_AVAILABLE["tca9548a"] = True
except Exception:
    SENSORS_AVAILABLE["tca9548a"] = False

# LCD (optional)
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    SENSORS_AVAILABLE["LCD"] = True
except Exception:
    SENSORS_AVAILABLE["LCD"] = False

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
#   I2C MUX (TCA9548A) CONFIGURATION
# ────────────────────────────────────────────────
USE_MUX = SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False)
MUX_ADDRESS = 0x70
MPU_MUX_CH = 1
BMP_MUX_CH = 2
LCD_MUX_CH = 0

tca = None
print(f"I2C Multiplexer (TCA9548A): {'ENABLED' if USE_MUX else 'DISABLED'}")

# LCD I2C backpack address (common: 0x27 or 0x3F)
LCD_I2C_BUS = 1
LCD_ADDR = 0x27
LCD_COLS = 16
LCD_ROWS = 2
_lcd = None

# ────────────────────────────────────────────────
#   NEW TOOLS PINS (CHANGE IF YOU WANT)
# ────────────────────────────────────────────────
LED_RED_PIN    = board.D5  if SENSORS_AVAILABLE.get("board") else None  # GPIO5 (phys 29)
LED_ORANGE_PIN = board.D6  if SENSORS_AVAILABLE.get("board") else None  # GPIO6 (phys 31)
LED_GREEN_PIN  = board.D13 if SENSORS_AVAILABLE.get("board") else None  # GPIO13 (phys 33)
BUZZER_PIN     = board.D16 if SENSORS_AVAILABLE.get("board") else None  # GPIO16 (phys 36)

# ────────────────────────────────────────────────
#   GLOBAL STATE
# ────────────────────────────────────────────────
app = Flask(__name__)

sensor_state = {
    "MPU6050":    False,
    "BMP280":     False,
    "DHT11":      False,
    "MHMQ":       False,
    "PIR":        False,
    "ULTRASONIC": False,
    "Relay":      False,
    "servomotor": False,

    # Tools (always available; controlled via their own endpoints)
    "LED_TOOL":   True,
    "BUZZER":     True,
    "LCD_TOOL":   True,
}

sensor_data = {
    "DHT11":      {"temperature": None, "humidity": None, "last_update": None},
    "MPU6050":    {"ax": None, "ay": None, "az": None, "gx": None, "gy": None, "gz": None, "temperature": None, "last_update": None},
    "BMP280":     {"temperature": None, "pressure": None, "altitude": None, "last_update": None},

    "PIR":        {"motion": False, "count": 0, "last_update": None},
    "ULTRASONIC": {"distance_cm": None, "last_update": None},

    # Gas sensor now includes a level_percent too
    "MHMQ":       {"gas_detected": False, "level_percent": None, "last_update": None},

    "Relay":      {"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": None},
    "servomotor": {"angle": 0, "last_update": None},

    # Tools data
    "LED_TOOL":   {"red": False, "orange": False, "green": False, "last_update": None},
    "BUZZER":     {"on": False, "last_update": None},
    "LCD_TOOL":   {"line1": "", "line2": "", "last_update": None},
}

threads = {}
running_flags = {}

# Hardware globals
pir_pin = None
motion_count = 0

dht_device = None
mpu = None
bmp = None

mq_pin = None
relay_pins = {}

servo_pwm = None
SERVO_PIN = board.D12 if SENSORS_AVAILABLE.get("board") else None
MIN_PULSE = 500
MAX_PULSE = 2500
FREQUENCY = 50

# Ultrasonic globals (INIT ONCE!)
ultra_trig = None
ultra_echo = None

# Tools hardware
led_red = None
led_orange = None
led_green = None
buzzer = None

# Silence werkzeug request logs
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# ────────────────────────────────────────────────
#   HELPERS
# ────────────────────────────────────────────────
def now_iso():
    return datetime.now().isoformat()

def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = bool(initial)
    return io

def make_in(pin, pull=None):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.INPUT
    if pull is not None:
        try:
            io.pull = pull
        except Exception:
            pass
    return io

# ────────────────────────────────────────────────
#   HARDWARE INITIALIZATION FUNCTIONS
# ────────────────────────────────────────────────
def init_mux():
    global tca, USE_MUX
    if not USE_MUX:
        return False
    try:
        i2c = board.I2C()
        tca = adafruit_tca9548a.TCA9548A(i2c, address=MUX_ADDRESS)
        print(f"TCA9548A initialized at address 0x{MUX_ADDRESS:02X}")
        return True
    except Exception as e:
        print(f"TCA9548A initialization failed: {e}")
        tca = None
        USE_MUX = False
        return False

def init_ultrasonic():
    global ultra_trig, ultra_echo
    if not SENSORS_AVAILABLE.get("board"):
        return False
    if ultra_trig is not None and ultra_echo is not None:
        return True
    try:
        ultra_trig = digitalio.DigitalInOut(board.D23)
        ultra_echo = digitalio.DigitalInOut(board.D24)
        ultra_trig.direction = digitalio.Direction.OUTPUT
        ultra_echo.direction = digitalio.Direction.INPUT
        ultra_trig.value = False
        print("Ultrasonic initialized (TRIG=D23, ECHO=D24)")
        return True
    except Exception as e:
        print(f"Ultrasonic init failed: {e}")
        ultra_trig = None
        ultra_echo = None
        return False

def measure_distance(TRIG, ECHO):
    try:
        TRIG.value = True
        time.sleep(0.00001)
        TRIG.value = False

        pulse_start = time.time()
        timeout = pulse_start + 0.1

        while ECHO.value == 0 and time.time() < timeout:
            pulse_start = time.time()

        pulse_end = time.time()
        while ECHO.value == 1 and time.time() < timeout:
            pulse_end = time.time()

        if pulse_end - pulse_start > 0.1:
            return None

        duration = pulse_end - pulse_start
        return round(duration * 17150, 1)
    except Exception:
        return None

def init_pir():
    global pir_pin
    if not SENSORS_AVAILABLE.get("board"):
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
        print("PIR initialized (D18)")
        return True
    except Exception as e:
        print(f"PIR init failed: {e}")
        pir_pin = None
        return False

def init_dht():
    global dht_device
    if not SENSORS_AVAILABLE.get("DHT11") or not SENSORS_AVAILABLE.get("board"):
        return False
    if dht_device is not None:
        return True
    try:
        dht_device = adafruit_dht.DHT11(board.D4)
        print("DHT11 initialized (D4)")
        return True
    except Exception as e:
        print(f"DHT11 init failed: {e}")
        dht_device = None
        return False

def init_mpu():
    global mpu
    if not SENSORS_AVAILABLE.get("MPU6050") or not SENSORS_AVAILABLE.get("board"):
        return False
    if mpu is not None:
        return True
    try:
        if USE_MUX:
            if tca is None and not init_mux():
                return False
            mpu = adafruit_mpu6050.MPU6050(tca[MPU_MUX_CH])
            print(f"MPU6050 initialized on TCA9548A channel {MPU_MUX_CH}")
        else:
            i2c = board.I2C()
            mpu = adafruit_mpu6050.MPU6050(i2c)
            print("MPU6050 initialized (direct I2C)")
        return True
    except Exception as e:
        print(f"MPU6050 init failed: {e}")
        mpu = None
        return False

def init_bmp():
    global bmp
    if not SENSORS_AVAILABLE.get("BMP280") or not SENSORS_AVAILABLE.get("board"):
        return False
    if bmp is not None:
        return True
    try:
        if USE_MUX:
            if tca is None and not init_mux():
                return False
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_MUX_CH])
            print(f"BMP280 initialized on TCA9548A channel {BMP_MUX_CH}")
        else:
            i2c = board.I2C()
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c)
            print("BMP280 initialized (direct I2C)")

        # Optional sea level pressure for altitude
        bmp.sea_level_pressure = 1013.25
        return True
    except Exception as e:
        print(f"BMP280 init failed: {e}")
        bmp = None
        return False

def init_mq():
    global mq_pin
    if not SENSORS_AVAILABLE.get("board"):
        return False
    if mq_pin is not None:
        return True
    try:
        mq_pin = digitalio.DigitalInOut(board.D17)
        mq_pin.direction = digitalio.Direction.INPUT
        # Usually DO already has pull-up on module; don't force it.
        print("MHMQ initialized (D17)")
        return True
    except Exception as e:
        print(f"MHMQ init failed: {e}")
        mq_pin = None
        return False

def init_relay():
    global relay_pins
    if not SENSORS_AVAILABLE.get("board"):
        return False
    if relay_pins:
        return True
    RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]  # active-low
    relay_pins = {}
    try:
        for ch, gpio_pin in enumerate(RELAY_PINS, 1):
            pin = digitalio.DigitalInOut(gpio_pin)
            pin.direction = digitalio.Direction.OUTPUT
            pin.value = True  # OFF (active low)
            relay_pins[ch] = pin
        sensor_data["Relay"].update({
            "ch1": False, "ch2": False, "ch3": False, "ch4": False,
            "last_update": now_iso()
        })
        print("Relay initialized (4ch)")
        return True
    except Exception as e:
        print(f"Relay init failed: {e}")
        relay_pins = {}
        return False

def init_servomotor():
    global servo_pwm
    if not SENSORS_AVAILABLE.get("servomotor") or not SENSORS_AVAILABLE.get("board"):
        return False
    if SERVO_PIN is None:
        return False
    try:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)
        set_servo_angle(0)
        servo_pwm.duty_cycle = 0
        servo_pwm.deinit()
        servo_pwm = None
        print("Servo initialized OFF at 0° (PWM stopped)")
        return True
    except Exception as e:
        print(f"Servo init failed: {e}")
        servo_pwm = None
        return False

def set_servo_angle(angle):
    global servo_pwm
    if not SENSORS_AVAILABLE.get("servomotor") or not SENSORS_AVAILABLE.get("board"):
        return False
    if SERVO_PIN is None:
        return False
    if servo_pwm is None:
        try:
            servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)
        except Exception as e:
            print(f"Failed to restart PWM: {e}")
            return False
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (angle / 180.0)
    duty = int((pulse_us / 20000.0) * 65535.0)
    servo_pwm.duty_cycle = duty
    sensor_data["servomotor"]["angle"] = angle
    sensor_data["servomotor"]["last_update"] = now_iso()
    return True

# ────────────────────────────────────────────────
#   LCD TOOL
# ────────────────────────────────────────────────
def mux_select_for_lcd():
    if not SENSORS_AVAILABLE.get("LCD"):
        return False
    try:
        with SMBus(LCD_I2C_BUS) as bus:
            bus.write_byte(MUX_ADDRESS, 1 << LCD_MUX_CH)
        return True
    except Exception as e:
        print("[LCD] mux select failed:", e)
        return False

def lcd_get():
    global _lcd
    if not SENSORS_AVAILABLE.get("LCD"):
        return None
    if _lcd is not None:
        return _lcd
    if not mux_select_for_lcd():
        return None
    try:
        _lcd = CharLCD(
            "PCF8574",
            address=LCD_ADDR,
            port=LCD_I2C_BUS,
            cols=LCD_COLS,
            rows=LCD_ROWS,
            charmap="A00",
        )
        _lcd.clear()
        return _lcd
    except Exception as e:
        print("[LCD] init failed:", e)
        _lcd = None
        return None

def lcd_write(line1="", line2=""):
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_for_lcd():
        return False
    try:
        lcd.clear()
        lcd.write_string((line1 or "")[:LCD_COLS])
        lcd.cursor_pos = (1, 0)
        lcd.write_string((line2 or "")[:LCD_COLS])
        sensor_data["LCD_TOOL"].update({"line1": line1, "line2": line2, "last_update": now_iso()})
        return True
    except Exception as e:
        print("[LCD] write failed:", e)
        return False

def lcd_clear():
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_for_lcd():
        return False
    try:
        lcd.clear()
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso()})
        return True
    except Exception as e:
        print("[LCD] clear failed:", e)
        return False

# ────────────────────────────────────────────────
#   LED + BUZZER TOOL INIT
# ────────────────────────────────────────────────
def init_tools_outputs():
    global led_red, led_orange, led_green, buzzer
    if not SENSORS_AVAILABLE.get("board"):
        return False

    try:
        if led_red is None and LED_RED_PIN is not None:
            led_red = make_out(LED_RED_PIN, False)
        if led_orange is None and LED_ORANGE_PIN is not None:
            led_orange = make_out(LED_ORANGE_PIN, False)
        if led_green is None and LED_GREEN_PIN is not None:
            led_green = make_out(LED_GREEN_PIN, False)
        if buzzer is None and BUZZER_PIN is not None:
            buzzer = make_out(BUZZER_PIN, False)
        return True
    except Exception as e:
        print("Tool outputs init failed:", e)
        return False

def set_led(color: str, on: bool):
    if not init_tools_outputs():
        return False
    color = (color or "").lower()
    io = {"red": led_red, "orange": led_orange, "green": led_green}.get(color)
    if io is None:
        return False
    io.value = bool(on)
    sensor_data["LED_TOOL"][color] = bool(on)
    sensor_data["LED_TOOL"]["last_update"] = now_iso()
    return True

def set_buzzer(on: bool):
    if not init_tools_outputs():
        return False
    if buzzer is None:
        return False
    buzzer.value = bool(on)
    sensor_data["BUZZER"]["on"] = bool(on)
    sensor_data["BUZZER"]["last_update"] = now_iso()
    return True

def beep(count=2, on_ms=120, off_ms=120):
    if not init_tools_outputs():
        return False
    if buzzer is None:
        return False
    try:
        for _ in range(int(count)):
            buzzer.value = True
            time.sleep(max(0.01, on_ms / 1000.0))
            buzzer.value = False
            time.sleep(max(0.01, off_ms / 1000.0))
        sensor_data["BUZZER"]["on"] = False
        sensor_data["BUZZER"]["last_update"] = now_iso()
        return True
    except Exception as e:
        print("Beep failed:", e)
        return False

# ────────────────────────────────────────────────
#   GAS LEVEL (DO sampling -> percent)
# ────────────────────────────────────────────────
GAS_SAMPLES = 20
GAS_SAMPLE_DELAY = 0.02
GAS_INVERT_DO = True          # your typical MQ DO boards often invert
GAS_ALERT_PERCENT = 30        # detected when >= 30% hits

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

# ────────────────────────────────────────────────
#   LAZY INIT ON DEMAND
# ────────────────────────────────────────────────
def ensure_sensor_init(sensor: str) -> bool:
    if sensor == "PIR":
        return init_pir()
    if sensor == "DHT11":
        return init_dht()
    if sensor == "MPU6050":
        return init_mpu()
    if sensor == "BMP280":
        return init_bmp()
    if sensor == "MHMQ":
        return init_mq()
    if sensor == "ULTRASONIC":
        return init_ultrasonic()
    if sensor == "Relay":
        return init_relay()
    if sensor == "servomotor":
        return SENSORS_AVAILABLE.get("servomotor", False) and SENSORS_AVAILABLE.get("board", False) and SERVO_PIN is not None
    return True

# ────────────────────────────────────────────────
#   BOOT SAFE INIT: only mux (avoid hangs)
# ────────────────────────────────────────────────
if SENSORS_AVAILABLE.get("board"):
    init_mux()

# ────────────────────────────────────────────────
#   BACKGROUND READERS
# ────────────────────────────────────────────────
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
                        sensor_data["DHT11"].update({
                            "temperature": round(t, 1),
                            "humidity": round(h, 1),
                            "last_update": now
                        })
                except Exception as e:
                    print("DHT read error:", e)

            elif sensor_name == "MPU6050" and mpu:
                ax, ay, az = mpu.acceleration
                gx, gy, gz = mpu.gyro
                temp = getattr(mpu, "temperature", None)
                sensor_data["MPU6050"].update({
                    "ax": round(ax, 2), "ay": round(ay, 2), "az": round(az, 2),
                    "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2),
                    "temperature": round(temp, 1) if temp is not None else None,
                    "last_update": now
                })

            elif sensor_name == "BMP280" and bmp:
                try:
                    temp = bmp.temperature
                    press = bmp.pressure
                    alt = getattr(bmp, "altitude", None)
                    sensor_data["BMP280"].update({
                        "temperature": round(temp, 1) if temp is not None else None,
                        "pressure": round(press, 1) if press is not None else None,
                        "altitude": round(alt, 1) if alt is not None else None,
                        "last_update": now
                    })
                except Exception as e:
                    print("BMP read error:", e)

            elif sensor_name == "PIR" and pir_pin:
                state = bool(pir_pin.value)
                if state and not last_pir_state:
                    motion_count += 1
                sensor_data["PIR"].update({
                    "motion": state,
                    "count": int(motion_count),
                    "last_update": now
                })
                last_pir_state = state

            elif sensor_name == "ULTRASONIC" and ultra_trig and ultra_echo:
                dist = measure_distance(ultra_trig, ultra_echo)
                sensor_data["ULTRASONIC"].update({"distance_cm": dist, "last_update": now})

            elif sensor_name == "MHMQ" and mq_pin:
                level = read_gas_level_percent()
                if level is None:
                    sensor_data["MHMQ"].update({"gas_detected": False, "level_percent": None, "last_update": now})
                else:
                    detected = (level >= GAS_ALERT_PERCENT)
                    sensor_data["MHMQ"].update({"gas_detected": bool(detected), "level_percent": int(level), "last_update": now})

        except Exception as e:
            print(f"Error in {sensor_name}: {e}")

        time.sleep(1.2)

# ────────────────────────────────────────────────
#   CONTROL FUNCTIONS
# ────────────────────────────────────────────────
def set_relay_channel(channel: int, on: bool):
    if channel not in relay_pins:
        return False
    relay_pins[channel].value = not on  # active-low
    sensor_data["Relay"][f"ch{channel}"] = bool(on)
    sensor_data["Relay"]["last_update"] = now_iso()
    print(f"Relay Ch{channel} → {'ON' if on else 'OFF'}")
    return True

# ────────────────────────────────────────────────
#   ROUTES
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

@app.route("/api/sensors")
def get_sensors():
    response = sensor_state.copy()
    response["data"] = sensor_data.copy()
    return jsonify(response)

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    data = request.json or {}
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"error": "Unknown sensor"}), 400

    # Don't toggle tool cards via /api/toggle
    if sensor in ("LED_TOOL", "BUZZER", "LCD_TOOL"):
        return jsonify({"sensor": sensor, "active": True})

    # flip state
    sensor_state[sensor] = not sensor_state[sensor]
    active = sensor_state[sensor]

    # Relay: toggle all channels together
    if sensor == "Relay":
        if active:
            if not ensure_sensor_init("Relay"):
                sensor_state[sensor] = False
                return jsonify({"sensor": sensor, "active": False, "error": "Relay init failed"}), 500
        for ch in range(1, 5):
            set_relay_channel(ch, active)
        return jsonify({"sensor": sensor, "active": active})

    # Servo: on -> 90, off -> 0 then stop PWM
    if sensor == "servomotor":
        global servo_pwm
        if active:
            if not ensure_sensor_init("servomotor"):
                sensor_state[sensor] = False
                return jsonify({"sensor": sensor, "active": False, "error": "Servo not available"}), 500
            set_servo_angle(90)
        else:
            set_servo_angle(0)
            time.sleep(0.6)
            if servo_pwm is not None:
                try:
                    servo_pwm.duty_cycle = 0
                    servo_pwm.deinit()
                except Exception:
                    pass
                servo_pwm = None
        return jsonify({"sensor": sensor, "active": active})

    # All other sensors: start/stop background thread
    if active:
        if not ensure_sensor_init(sensor):
            sensor_state[sensor] = False
            return jsonify({"sensor": sensor, "active": False, "error": f"{sensor} init failed"}), 500

        running_flags[sensor] = True
        if sensor not in threads or not threads[sensor].is_alive():
            threads[sensor] = threading.Thread(target=sensor_reader, args=(sensor,), daemon=True)
            threads[sensor].start()
    else:
        running_flags[sensor] = False

    return jsonify({"sensor": sensor, "active": active})

# ────────────────────────────────────────────────
#   NEW TOOL ENDPOINTS
# ────────────────────────────────────────────────
@app.route("/api/led", methods=["POST"])
def api_led():
    data = request.json or {}
    color = (data.get("color") or "").lower()
    action = data.get("action")  # "on" "off" "toggle"
    if color not in ("red", "orange", "green") or action not in ("on", "off", "toggle"):
        return jsonify({"error": "Invalid"}), 400

    cur = bool(sensor_data["LED_TOOL"].get(color, False))
    target = (not cur) if action == "toggle" else (action == "on")

    ok = set_led(color, target)
    if not ok:
        return jsonify({"error": "LED init failed"}), 500

    return jsonify({"success": True, "color": color, "state": target, "all": sensor_data["LED_TOOL"]})

@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode")  # "on" "off" "toggle" "beep"
    if mode not in ("on", "off", "toggle", "beep"):
        return jsonify({"error": "Invalid"}), 400

    if mode == "beep":
        count = int(data.get("count", 2))
        on_ms = int(data.get("on_ms", 120))
        off_ms = int(data.get("off_ms", 120))
        ok = beep(count=count, on_ms=on_ms, off_ms=off_ms)
        if not ok:
            return jsonify({"error": "Buzzer init failed"}), 500
        return jsonify({"success": True, "on": False})

    cur = bool(sensor_data["BUZZER"].get("on", False))
    target = (not cur) if mode == "toggle" else (mode == "on")
    ok = set_buzzer(target)
    if not ok:
        return jsonify({"error": "Buzzer init failed"}), 500
    return jsonify({"success": True, "on": target})

@app.route("/api/lcd", methods=["POST"])
def api_lcd():
    data = request.json or {}
    if data.get("clear"):
        ok = lcd_clear()
        if not ok:
            return jsonify({"error": "LCD not available"}), 500
        return jsonify({"success": True})

    line1 = str(data.get("line1", ""))
    line2 = str(data.get("line2", ""))
    ok = lcd_write(line1, line2)
    if not ok:
        return jsonify({"error": "LCD not available"}), 500
    return jsonify({"success": True})

# ────────────────────────────────────────────────
#   START SERVER
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 80)
    print("  IoT Sensor Dashboard  (Raspberry Pi)")
    print("  Access: http://localhost:5000  (on this Raspberry Pi)")
    print("  Or from other device: http://<pi-ip>:5000")
    print("=" * 80)
    print("Available sensors:", list(sensor_state.keys()))
    print("Libraries loaded :", SENSORS_AVAILABLE)
    print("I2C Mux:", "Enabled" if USE_MUX else "Disabled")
    print("=" * 80 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)