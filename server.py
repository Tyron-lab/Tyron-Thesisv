from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging

# ────────────────────────────────────────────────
#   Conditional imports – only load what we can
# ────────────────────────────────────────────────
SENSORS_AVAILABLE = {}

try:
    import board
    import digitalio
    SENSORS_AVAILABLE["board"] = True
except ImportError:
    SENSORS_AVAILABLE["board"] = False

try:
    import adafruit_dht
    SENSORS_AVAILABLE["DHT11"] = True
except ImportError:
    SENSORS_AVAILABLE["DHT11"] = False

try:
    import adafruit_bmp280
    SENSORS_AVAILABLE["BMP280"] = True
except ImportError:
    SENSORS_AVAILABLE["BMP280"] = False

try:
    import adafruit_adxl34x
    SENSORS_AVAILABLE["ADXL345"] = True
except ImportError:
    SENSORS_AVAILABLE["ADXL345"] = False

# For servo
try:
    import pwmio
    SENSORS_AVAILABLE["servomotor"] = True
except ImportError:
    SENSORS_AVAILABLE["servomotor"] = False

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
#   GLOBAL STATE
# ────────────────────────────────────────────────
app = Flask(__name__)

sensor_state = {  
    "ADXL345":    False,
    "BMP280":     False,
    "DHT11":      False,
    "MHMQ":       False,
    "PIR":        False,
    "ULTRASONIC": False,
    "Relay":      False,
    "Motor":      False,
    "servomotor": False,   # OFF at startup
}

# Latest readings / states
sensor_data = {
    "DHT11":      {"temperature": None, "humidity": None, "last_update": None},
    "BMP280":     {"temperature": None, "pressure": None, "altitude": None, "last_update": None},
    "ADXL345":    {"x": None, "y": None, "z": None, "last_update": None},
    "PIR":        {"motion": False, "count": 0, "last_update": None},
    "ULTRASONIC": {"distance_cm": None, "last_update": None},
    "MHMQ":       {"gas_detected": False, "last_update": None},
    "Relay":      {
        "ch1": False, "ch2": False, "ch3": False, "ch4": False,
        "last_update": None
    },
    "Motor":      {"state": False, "last_update": None},
    "servomotor": {"angle": 0, "last_update": None},  # start OFF at 0°
}

# Thread control for sensors
threads = {}
running_flags = {}

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ────────────────────────────────────────────────
#   HARDWARE PINS & INITIALIZATION
# ────────────────────────────────────────────────

# ── Ultrasonic ──
def init_ultrasonic():
    if not SENSORS_AVAILABLE.get("board"): return None, None
    TRIG = digitalio.DigitalInOut(board.D23)
    ECHO = digitalio.DigitalInOut(board.D24)
    TRIG.direction = digitalio.Direction.OUTPUT
    ECHO.direction = digitalio.Direction.INPUT
    TRIG.value = False
    return TRIG, ECHO

def measure_distance(TRIG, ECHO):
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

# ── PIR ──
pir_pin = None
motion_count = 0

def init_pir():
    global pir_pin
    if not SENSORS_AVAILABLE.get("board"): return
    pir_pin = digitalio.DigitalInOut(board.D18)
    pir_pin.direction = digitalio.Direction.INPUT

# ── DHT11 ──
dht_device = None
def init_dht():
    global dht_device
    if not SENSORS_AVAILABLE.get("DHT11"): return
    if not SENSORS_AVAILABLE.get("board"): return
    dht_device = adafruit_dht.DHT11(board.D4)

# ── BMP280 ──
bmp280 = None
def init_bmp():
    global bmp280
    if not SENSORS_AVAILABLE.get("BMP280"): return
    if not SENSORS_AVAILABLE.get("board"): return
    try:
        i2c = board.I2C()
        bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76)
        bmp280.sea_level_pressure = 1013.25
    except Exception as e:
        print(f"BMP280 init failed: {e}")

# ── ADXL345 ──
adxl = None
def init_adxl():
    global adxl
    if not SENSORS_AVAILABLE.get("ADXL345"): return
    if not SENSORS_AVAILABLE.get("board"): return
    try:
        i2c = board.I2C()
        adxl = adafruit_adxl34x.ADXL345(i2c)
    except Exception as e:
        print(f"ADXL345 init failed: {e}")

# ── MQ ──
mq_pin = None
def init_mq():
    global mq_pin
    if not SENSORS_AVAILABLE.get("board"): return
    mq_pin = digitalio.DigitalInOut(board.D17)
    mq_pin.direction = digitalio.Direction.INPUT

# ── 4-Channel Relay ──
relay_pins = {}

def init_relay():
    global relay_pins
    if not SENSORS_AVAILABLE.get("board"): return
    
    RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]

    for ch, gpio_pin in enumerate(RELAY_PINS, 1):
        pin = digitalio.DigitalInOut(gpio_pin)
        pin.direction = digitalio.Direction.OUTPUT
        pin.value = True  # OFF
        relay_pins[ch] = pin
    
    sensor_data["Relay"] = {
        "ch1": False, "ch2": False, "ch3": False, "ch4": False,
        "last_update": datetime.now().isoformat()
    }
    print("Relay initialized:", [f"Ch{ch}: {p}" for ch, p in relay_pins.items()])

# ── DC Motor ──
motor_pin = None
def init_motor():
    global motor_pin
    if not SENSORS_AVAILABLE.get("board"): return
    motor_pin = digitalio.DigitalInOut(board.D22)
    motor_pin.direction = digitalio.Direction.OUTPUT
    motor_pin.value = False

# ── Servo Motor (PWM) ──
servo_pwm = None
SERVO_PIN = board.D12
MIN_PULSE = 500
MAX_PULSE = 2500
FREQUENCY = 50

def init_servomotor():
    global servo_pwm
    if not SENSORS_AVAILABLE.get("servomotor"): return
    if not SENSORS_AVAILABLE.get("board"): return
    try:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)
        set_servo_angle(0)           # start OFF at 0°
        servo_pwm.duty_cycle = 0     # immediately stop PWM
        servo_pwm.deinit()
        servo_pwm = None
        print(f"Servo initialized OFF at 0° (PWM stopped)")
    except Exception as e:
        print(f"Servo init failed: {e}")
        servo_pwm = None

def set_servo_angle(angle):
    global servo_pwm
    if not servo_pwm:
        try:
            servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)
            print("PWM restarted for servo")
        except Exception as e:
            print(f"Failed to restart PWM: {e}")
            return False

    angle = max(0, min(180, angle))
    pulse_us = MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (angle / 180)
    duty = int((pulse_us / 20000) * 65535)
    servo_pwm.duty_cycle = duty
    sensor_data["servomotor"]["angle"] = angle
    sensor_data["servomotor"]["last_update"] = datetime.now().isoformat()
    print(f"Servo moved to {angle}°")
    return True

# Call inits
if SENSORS_AVAILABLE.get("board"):
    init_pir()
    init_dht()
    init_bmp()
    init_adxl()
    init_mq()
    init_relay()
    init_motor()
    init_servomotor()

# ────────────────────────────────────────────────
#   CONTROL FUNCTIONS
# ────────────────────────────────────────────────

def set_relay_channel(channel: int, on: bool):
    if channel not in relay_pins: return False
    relay_pins[channel].value = not on
    sensor_data["Relay"][f"ch{channel}"] = on
    sensor_data["Relay"]["last_update"] = datetime.now().isoformat()
    print(f"Relay Ch{channel} → {'ON' if on else 'OFF'}")
    return True

def set_motor(on: bool):
    if not motor_pin: return False
    motor_pin.value = on
    sensor_data["Motor"]["state"] = on
    sensor_data["Motor"]["last_update"] = datetime.now().isoformat()
    print(f"Motor → {'ON' if on else 'OFF'}")
    return True

# ────────────────────────────────────────────────
#   BACKGROUND READERS
# ────────────────────────────────────────────────

def sensor_reader(sensor_name):
    global motion_count
    last_pir_state = False

    while running_flags.get(sensor_name, False):
        now = datetime.now().isoformat()
        try:
            if sensor_name == "DHT11" and dht_device:
                t = dht_device.temperature
                h = dht_device.humidity
                if t is not None and h is not None:
                    sensor_data["DHT11"].update({"temperature": round(t,1), "humidity": round(h,1), "last_update": now})

            elif sensor_name == "BMP280" and bmp280:
                sensor_data["BMP280"].update({
                    "temperature": round(bmp280.temperature,1),
                    "pressure": round(bmp280.pressure,1),
                    "altitude": round(bmp280.altitude,1),
                    "last_update": now
                })

            elif sensor_name == "ADXL345" and adxl:
                x,y,z = adxl.acceleration
                sensor_data["ADXL345"].update({"x":round(x,2),"y":round(y,2),"z":round(z,2),"last_update":now})

            elif sensor_name == "PIR" and pir_pin:
                state = pir_pin.value
                if state and not last_pir_state:
                    motion_count += 1
                    sensor_data["PIR"].update({"motion":True, "count":motion_count, "last_update":now})
                elif not state and last_pir_state:
                    sensor_data["PIR"]["motion"] = False
                    sensor_data["PIR"]["last_update"] = now
                last_pir_state = state

            elif sensor_name == "ULTRASONIC":
                trig, echo = init_ultrasonic()
                if trig and echo:
                    dist = measure_distance(trig, echo)
                    sensor_data["ULTRASONIC"].update({"distance_cm":dist, "last_update":now})

            elif sensor_name == "MHMQ" and mq_pin:
                detected = not mq_pin.value
                sensor_data["MHMQ"].update({"gas_detected":detected, "last_update":now})

        except Exception as e:
            print(f"Error in {sensor_name}: {e}")

        time.sleep(1.2)

# ────────────────────────────────────────────────
#   ROUTES
# ────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("gui", "front.html")

@app.route("/script.js")
def script():
    return send_from_directory("gui", "script.js")

@app.route("/style.css")
def style():
    return send_from_directory("gui", "style.css")

@app.route("/images/<path:filename>")
def images(filename):
    return send_from_directory("gui/images", filename)

@app.route("/api/sensors")
def get_sensors():
    response = sensor_state.copy()
    response["data"] = sensor_data.copy()
    return jsonify(response)

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    data = request.json
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"error": "Unknown sensor"}), 400

    sensor_state[sensor] = not sensor_state[sensor]
    active = sensor_state[sensor]

    if sensor == "Relay":
        for ch in range(1, 5):
            set_relay_channel(ch, active)
        print(f"Relay {'all ON' if active else 'all OFF'}")

    elif sensor == "servomotor":
        global servo_pwm  # IMPORTANT: declare global to avoid UnboundLocalError

        if active:
            # ON → move to 180° and hold
            set_servo_angle(180)
            print("Servo ON → 180° (holding)")
        else:
            # OFF → move to 0° then STOP PWM completely
            set_servo_angle(0)
            time.sleep(0.8)  # give time to reach position
            if servo_pwm is not None:
                servo_pwm.duty_cycle = 0
                servo_pwm.deinit()
                servo_pwm = None
                print("Servo OFF → 0° and PWM STOPPED")
    else:
        if active:
            if sensor not in threads or not threads[sensor].is_alive():
                running_flags[sensor] = True
                threads[sensor] = threading.Thread(target=sensor_reader, args=(sensor,), daemon=True)
                threads[sensor].start()
        else:
            running_flags[sensor] = False

    return jsonify({"sensor": sensor, "active": active})

@app.route("/api/relay", methods=["POST"])
def control_relay():
    data = request.json
    channel = data.get("channel")
    action = data.get("action")

    if channel not in [1,2,3,4] or action not in ["on","off","toggle"]:
        return jsonify({"error": "Invalid"}), 400

    current = sensor_data["Relay"][f"ch{channel}"]
    target = not current if action == "toggle" else (action == "on")

    success = set_relay_channel(channel, target)
    return jsonify({"success": success, "state": target})

@app.route("/api/motor", methods=["POST"])
def control_motor():
    data = request.json
    action = data.get("action")
    if action not in ["on","off","toggle"]:
        return jsonify({"error": "Invalid"}), 400

    current = sensor_data["Motor"]["state"]
    target = not current if action == "toggle" else (action == "on")
    success = set_motor(target)
    return jsonify({"success": success, "state": target})

@app.route("/api/servomotor", methods=["POST"])
def control_servomotor():
    data = request.json
    angle = data.get("angle")
    if angle is None or not (0 <= angle <= 180):
        return jsonify({"error": "Angle must be 0–180"}), 400

    success = set_servo_angle(angle)
    return jsonify({"success": success, "angle": angle})

# ────────────────────────────────────────────────
#   START
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*80)
    print("  IoT Sensor Dashboard  (Raspberry Pi)")
    print("  http://localhost:5000  or  http://<pi-ip>:5000")
    print("="*80)
    print("Available sensors:", list(sensor_state.keys()))
    print("Libraries loaded :", SENSORS_AVAILABLE)
    print("Servo pin:", SERVO_PIN if SENSORS_AVAILABLE.get("servomotor") else "Not available")
    print("Servo behavior:")
    print("   - Starts OFF at 0° (PWM stopped)")
    print("   - Click Servo Motor card:")
    print("      ON  → move to 180° and hold")
    print("      OFF → move to 0° and stop (PWM off)")
    print("="*80 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)