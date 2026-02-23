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

# I2C lock is CRITICAL
i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

# ────────────────────────────────────────────────
#   STATE + DATA
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

    # Tools (always available; controlled via their own endpoints)
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
#   MUX (TCA9548A) CONFIG
# ────────────────────────────────────────────────
USE_MUX = SENSORS_AVAILABLE.get("tca9548a", False) and SENSORS_AVAILABLE.get("board", False)
MUX_ADDRESS = 0x70

# default channels (we will auto-detect BMP channel if needed)
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

def mux_select_channel_smbus(ch: int) -> bool:
    """Select mux channel using SMBus (works even before Blinka objects)."""
    if not USE_MUX:
        return True
    try:
        with i2c_lock:
            with SMBus(LCD_I2C_BUS) as bus:
                bus.write_byte(MUX_ADDRESS, 1 << ch)
        return True
    except Exception as e:
        return False

def mux_select_for_lcd():
    if not SENSORS_AVAILABLE.get("LCD"):
        return False
    return mux_select_channel_smbus(LCD_MUX_CH)

def lcd_get():
    global _lcd, _lcd_addr
    if not SENSORS_AVAILABLE.get("LCD"):
        set_error("LCD_TOOL", "LCD libraries not installed (pip install RPLCD smbus2)")
        return None
    if _lcd is not None:
        return _lcd

    if not mux_select_for_lcd():
        set_error("LCD_TOOL", "mux select failed for LCD")
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
#   GPIO OUTPUTS (LEDs + BUZZER)
# ────────────────────────────────────────────────
LED_RED_PIN    = board.D5  if SENSORS_AVAILABLE.get("board") else None
LED_ORANGE_PIN = board.D6  if SENSORS_AVAILABLE.get("board") else None
LED_GREEN_PIN  = board.D13 if SENSORS_AVAILABLE.get("board") else None
BUZZER_PIN     = board.D16 if SENSORS_AVAILABLE.get("board") else None

# Active buzzer modules are usually ACTIVE-LOW (signal LOW = ON)
BUZZER_ACTIVE_LOW = True

led_red = None
led_orange = None
led_green = None
buzzer = None

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
            # OFF depends on polarity
            off_value = True if BUZZER_ACTIVE_LOW else False
            buzzer = make_out(BUZZER_PIN, off_value)

            # reflect status
            sensor_data["BUZZER"]["on"] = False
            sensor_data["BUZZER"]["last_update"] = now_iso()
            clear_error("BUZZER")

        return True
    except Exception as e:
        set_error("LED_TOOL", f"init failed: {e}")
        set_error("BUZZER", f"init failed: {e}")
        return False

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
#   SENSOR INSTANCES
# ────────────────────────────────────────────────
dht_device = None
mpu = None
bmp = None

# ────────────────────────────────────────────────
#   BMP280 AUTO-DETECT (channel + address)
# ────────────────────────────────────────────────
def probe_addr_on_channel(ch: int, addr: int) -> bool:
    """Use smbus2 probing (works even when we don't know the channel)."""
    if USE_MUX:
        if not mux_select_channel_smbus(ch):
            return False
    try:
        with i2c_lock:
            with SMBus(LCD_I2C_BUS) as bus:
                # a simple read attempt to see if device ACKs
                bus.read_byte(addr)
        return True
    except Exception:
        return False

def autodetect_bmp_channel_and_addr():
    """
    Finds which mux channel has BMP (0x76 or 0x77).
    Returns (ch, addr) or (None, None)
    """
    if not USE_MUX:
        # direct bus probe
        for a in (0x76, 0x77):
            if probe_addr_on_channel(0, a):  # channel ignored when !USE_MUX
                return (None, a)
        return (None, None)

    for ch in range(8):
        for addr in (0x76, 0x77):
            if probe_addr_on_channel(ch, addr):
                return (ch, addr)
    return (None, None)

# ────────────────────────────────────────────────
#   SENSOR INIT
# ────────────────────────────────────────────────
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
        print(f"[MPU6050] OK mux_ch={MPU_MUX_CH if USE_MUX else 'direct'}")
        return True
    except Exception as e:
        mpu = None
        set_error("MPU6050", f"init failed: {e}")
        return False

def init_bmp():
    """
    FIXED:
    - try configured channel + 0x76/0x77
    - if fail, AUTO-DETECT correct channel/address and re-init
    """
    global bmp, BMP_MUX_CH
    if not SENSORS_AVAILABLE.get("BMP280") or not SENSORS_AVAILABLE.get("board"):
        set_error("BMP280", "BMP280/board not available")
        return False
    if bmp is not None:
        return True

    if USE_MUX and (tca is None) and not init_mux():
        set_error("BMP280", "MUX init failed")
        return False

    # 1) try configured channel first
    last = None
    for addr in (0x76, 0x77):
        try:
            with i2c_lock:
                if USE_MUX:
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_MUX_CH], address=addr)
                else:
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=addr)
                bmp.sea_level_pressure = 1013.25
            clear_error("BMP280")
            print(f"[BMP280] OK mux_ch={BMP_MUX_CH if USE_MUX else 'direct'} addr=0x{addr:02X}")
            return True
        except Exception as e:
            bmp = None
            last = e

    # 2) auto-detect (THIS IS THE REAL FIX)
    ch, addr = autodetect_bmp_channel_and_addr()
    if USE_MUX and ch is not None:
        BMP_MUX_CH = ch

    if addr is None:
        set_error("BMP280", f"init failed (no device found on any mux channel at 0x76/0x77). Last: {last}")
        return False

    try:
        with i2c_lock:
            if USE_MUX:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_MUX_CH], address=addr)
            else:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=addr)
            bmp.sea_level_pressure = 1013.25
        clear_error("BMP280")
        print(f"[BMP280] AUTO OK mux_ch={BMP_MUX_CH if USE_MUX else 'direct'} addr=0x{addr:02X}")
        return True
    except Exception as e:
        bmp = None
        set_error("BMP280", f"auto init failed even after detect: {e}")
        return False

# ────────────────────────────────────────────────
#   BACKGROUND SENSOR READER
# ────────────────────────────────────────────────
threads = {}
running_flags = {}

def sensor_reader(sensor_name):
    while running_flags.get(sensor_name, False):
        now = now_iso()
        try:
            if sensor_name == "MPU6050" and mpu:
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

        except Exception as e:
            set_error(sensor_name, e)

        time.sleep(1.0)

def ensure_sensor_init(sensor: str) -> bool:
    if sensor == "MPU6050":
        return init_mpu()
    if sensor == "BMP280":
        return init_bmp()
    return True

# ────────────────────────────────────────────────
#   ROUTES (STATIC + API)
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

@app.route("/api/toggle", methods=["POST"])
def toggle_sensor():
    """
    IMPORTANT FIX:
    - if user clicks BUZZER card, this now REALLY toggles the buzzer
    - if user clicks BMP card, it starts reading thread
    """
    data = request.json or {}
    sensor = data.get("sensor")

    if sensor not in sensor_state:
        return jsonify({"ok": False, "error": "Unknown sensor"}), 400

    # BUZZER card click support
    if sensor == "BUZZER":
        cur = bool(sensor_data["BUZZER"].get("on", False))
        target = not cur
        ok = set_buzzer(target)
        return jsonify({"ok": ok, "sensor": "BUZZER", "active": True, "on": target, "error": sensor_data["BUZZER"]["error"]})

    # LCD card click just returns ok (LCD uses /api/lcd for sending text)
    if sensor == "LCD_TOOL":
        return jsonify({"ok": True, "sensor": sensor, "active": True})

    # flip state for normal sensors
    sensor_state[sensor] = not sensor_state[sensor]
    active = sensor_state[sensor]

    if sensor in ("MPU6050", "BMP280"):
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

        return jsonify({"ok": True, "sensor": sensor, "active": active, "error": sensor_data[sensor]["error"]})

    return jsonify({"ok": True, "sensor": sensor, "active": active})

# ────────────────────────────────────────────────
#   TOOL ENDPOINTS
# ────────────────────────────────────────────────
@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode")  # on/off/toggle/beep/force_off
    if mode not in ("on", "off", "toggle", "beep", "force_off"):
        return jsonify({"ok": False, "error": "Invalid"}), 400

    if mode == "force_off":
        ok = set_buzzer(False)
        return jsonify({"ok": ok, "on": False, "active_low": BUZZER_ACTIVE_LOW, "error": sensor_data["BUZZER"]["error"]})

    if mode == "beep":
        count = int(data.get("count", 2))
        on_ms = int(data.get("on_ms", 120))
        off_ms = int(data.get("off_ms", 120))
        ok = beep(count=count, on_ms=on_ms, off_ms=off_ms)
        return jsonify({"ok": ok, "on": False, "active_low": BUZZER_ACTIVE_LOW, "error": sensor_data["BUZZER"]["error"]})

    cur = bool(sensor_data["BUZZER"].get("on", False))
    target = (not cur) if mode == "toggle" else (mode == "on")

    ok = set_buzzer(target)
    return jsonify({"ok": ok, "on": target, "active_low": BUZZER_ACTIVE_LOW, "error": sensor_data["BUZZER"]["error"]})

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

# ────────────────────────────────────────────────
#   DEBUG: I2C scan per mux channel (shows where BMP actually is)
# ────────────────────────────────────────────────
def i2c_scan_current_bus():
    found = []
    try:
        with i2c_lock:
            with SMBus(LCD_I2C_BUS) as bus:
                for addr in range(0x03, 0x78):
                    try:
                        bus.write_quick(addr)
                        found.append(hex(addr))
                    except Exception:
                        pass
    except Exception as e:
        return {"ok": False, "error": str(e), "found": []}
    return {"ok": True, "found": found}

@app.get("/api/debug/i2cscan")
def api_debug_i2cscan():
    if not SENSORS_AVAILABLE.get("LCD"):
        return jsonify({"ok": False, "error": "Need smbus2 installed (pip install smbus2)"}), 500

    out = {"use_mux": bool(USE_MUX), "mux_addr": hex(MUX_ADDRESS), "channels": {}}

    if USE_MUX:
        for ch in range(8):
            if not mux_select_channel_smbus(ch):
                out["channels"][str(ch)] = {"ok": False, "error": "mux select failed", "found": []}
                continue
            out["channels"][str(ch)] = i2c_scan_current_bus()
    else:
        out["channels"]["direct"] = i2c_scan_current_bus()

    return jsonify({"ok": True, "scan": out})

# ────────────────────────────────────────────────
#   START
# ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 80)
    print("TrainerKit Tools Dashboard")
    print("Open: http://localhost:5000")
    print("I2C Mux:", "Enabled" if USE_MUX else "Disabled")
    print("LCD_MUX_CH:", LCD_MUX_CH, "MPU_MUX_CH:", MPU_MUX_CH, "BMP_MUX_CH:", BMP_MUX_CH)
    print("BUZZER_ACTIVE_LOW:", BUZZER_ACTIVE_LOW)
    print("=" * 80)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)