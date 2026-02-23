from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging
import os

# ────────────────────────────────────────────────
#   Conditional imports
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

SENSORS_AVAILABLE["BMP280"] = False

try:
    import adafruit_mpu6050
    SENSORS_AVAILABLE["MPU6050"] = True
except ImportError:
    SENSORS_AVAILABLE["MPU6050"] = False

try:
    import pwmio
    SENSORS_AVAILABLE["servomotor"] = True
except ImportError:
    SENSORS_AVAILABLE["servomotor"] = False

try:
    import adafruit_tca9548a
    SENSORS_AVAILABLE["tca9548a"] = True
except ImportError:
    SENSORS_AVAILABLE["tca9548a"] = False

print("Available libraries:", SENSORS_AVAILABLE)

# ────────────────────────────────────────────────
#   I2C MUX CONFIG
# ────────────────────────────────────────────────
USE_MUX = SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False)
MUX_ADDRESS = 0x70
MPU_MUX_CH = 1
BMP_MUX_CH = 2
LCD_MUX_CH = 0
tca = None

print(f"I2C Multiplexer: {'ENABLED' if USE_MUX else 'DISABLED'}")

# ────────────────────────────────────────────────
#   GLOBAL STATE
# ────────────────────────────────────────────────
app = Flask(__name__)

sensor_state = {
    "MPU6050":    False,
    "DHT11":      False,
    "MHMQ":       False,
    "PIR":        False,
    "ULTRASONIC": False,
    "Relay":      False,
    "servomotor": False,
}

sensor_data = {
    "DHT11":      {"temperature": None, "humidity": None, "last_update": None},
    "MPU6050":    {"ax": None, "ay": None, "az": None, "gx": None, "gy": None, "gz": None, "temperature": None, "last_update": None},
    "PIR":        {"motion": False, "count": 0, "last_update": None},
    "ULTRASONIC": {"distance_cm": None, "last_update": None},
    "MHMQ":       {"gas_detected": False, "last_update": None},
    "Relay":      {"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": None},
    "servomotor": {"angle": 0, "last_update": None},
}

threads = {}
running_flags = {}

pir_pin = None
motion_count = 0
dht_device = None
mpu = None
mq_pin = None
relay_pins = {}
servo_pwm = None
SERVO_PIN = board.D12 if SENSORS_AVAILABLE.get("board") else None
MIN_PULSE = 500
MAX_PULSE = 2500
FREQUENCY = 50

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ────────────────────────────────────────────────
#   HARDWARE INIT (keep your original functions here)
# ────────────────────────────────────────────────

# Paste your init_mux, init_ultrasonic, measure_distance, init_pir, init_dht,
# init_mpu, init_mq, init_relay, init_servomotor, set_servo_angle functions here
# (they are correct, no change needed)

if SENSORS_AVAILABLE.get("board"):
    init_mux()
    init_pir()
    init_dht()
    init_mpu()
    init_mq()
    init_relay()
    init_servomotor()

# ────────────────────────────────────────────────
#   SENSOR READER (keep your original)
# ────────────────────────────────────────────────

# Paste your sensor_reader function here (unchanged)

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

# ────────────────────────────────────────────────
#   ROUTES – FIXED FOR YOUR FOLDER STRUCTURE
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    path = os.path.join(BASE_DIR, "template", "tools.html")
    if not os.path.exists(path):
        return f"<h1>ERROR: File not found</h1><p>Expected: {path}</p><p>Current dir: {BASE_DIR}</p>", 404
    return send_from_directory(os.path.join(BASE_DIR, "template"), "tools.html")

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
        global servo_pwm
        if active:
            set_servo_angle(180)
            print("Servo ON → 180° (holding)")
        else:
            set_servo_angle(0)
            time.sleep(0.8)
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

@app.route("/api/servomotor", methods=["POST"])
def control_servomotor():
    data = request.json
    angle = data.get("angle")
    if angle is None or not (0 <= angle <= 180):
        return jsonify({"error": "Angle must be 0–180"}), 400
    success = set_servo_angle(angle)
    return jsonify({"success": success, "angle": angle})

# ────────────────────────────────────────────────
#   START SERVER
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*80)
    print("  IoT Sensor Dashboard  (Raspberry Pi)")
    print("  Access: http://localhost:5000  (on this Raspberry Pi)")
    print("  Or from phone/laptop: http://<pi-ip>:5000")
    print("="*80)
    print("Available sensors:", list(sensor_state.keys()))
    print("Libraries loaded :", SENSORS_AVAILABLE)
    print("Servo:", "Available" if SENSORS_AVAILABLE.get("servomotor") else "Not available")
    print("I2C Mux:", "Enabled" if USE_MUX else "Disabled")
    print("Current dir:", os.getcwd())
    print("Project root:", BASE_DIR)
    print("Dashboard file:", os.path.join(BASE_DIR, "template", "tools.html"))
    print("Tools.js file:", os.path.join(BASE_DIR, "static/js", "tools.js"))
    print("Tools.css file:", os.path.join(BASE_DIR, "static/css", "tools.css"))
    print("="*80 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)