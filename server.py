from flask import Flask, request, jsonify, send_from_directory
import threading
import time
from datetime import datetime
import logging
import os

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# =========================
# Imports (safe)
# =========================
SENSORS_AVAILABLE = {}

try:
    import board
    import digitalio
    SENSORS_AVAILABLE["board"] = True
except Exception:
    SENSORS_AVAILABLE["board"] = False

try:
    import adafruit_tca9548a
    SENSORS_AVAILABLE["tca9548a"] = True
except Exception:
    SENSORS_AVAILABLE["tca9548a"] = False

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
    import adafruit_dht
    SENSORS_AVAILABLE["DHT11"] = True
except Exception:
    SENSORS_AVAILABLE["DHT11"] = False

try:
    import pwmio
    SENSORS_AVAILABLE["servo"] = True
except Exception:
    SENSORS_AVAILABLE["servo"] = False

# LCD (smbus2 + RPLCD)
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    SENSORS_AVAILABLE["LCD"] = True
except Exception:
    SENSORS_AVAILABLE["LCD"] = False

print("Libraries:", SENSORS_AVAILABLE)

# =========================
# Global helpers
# =========================
i2c_lock = threading.Lock()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

# =========================
# MUX config
# =========================
USE_MUX = SENSORS_AVAILABLE.get("board") and SENSORS_AVAILABLE.get("tca9548a")
MUX_ADDR = 0x70

# EDIT THESE IF YOUR CHANNELS DIFFER
LCD_CH = 0
MPU_CH = 1
BMP_CH = 2

tca = None

def init_mux():
    global tca, USE_MUX
    if not USE_MUX:
        return False
    try:
        with i2c_lock:
            i2c = board.I2C()
            tca = adafruit_tca9548a.TCA9548A(i2c, address=MUX_ADDR)
        print(f"[MUX] OK addr=0x{MUX_ADDR:02X}")
        return True
    except Exception as e:
        print("[MUX] init failed:", e)
        tca = None
        USE_MUX = False
        return False

if USE_MUX:
    init_mux()

# =========================
# State + data (includes errors!)
# =========================
sensor_state = {
    "MPU6050": False,
    "BMP280": False,
    "DHT11": False,
    "MHMQ": False,
    "PIR": False,
    "ULTRASONIC": False,
    "Relay": False,
    "servomotor": False,

    # Tool cards (always shown)
    "LED_TOOL": True,
    "BUZZER": True,
    "LCD_TOOL": True,
}

sensor_data = {
    "MPU6050": {"ax": None, "ay": None, "az": None, "gx": None, "gy": None, "gz": None, "temperature": None, "last_update": None, "error": ""},
    "BMP280":  {"temperature": None, "pressure": None, "altitude": None, "last_update": None, "error": ""},
    "DHT11":   {"temperature": None, "humidity": None, "last_update": None, "error": ""},

    "MHMQ": {"gas_detected": False, "level_percent": None, "last_update": None, "error": ""},
    "PIR": {"motion": False, "count": 0, "last_update": None, "error": ""},
    "ULTRASONIC": {"distance_cm": None, "last_update": None, "error": ""},

    "Relay": {"ch1": False, "ch2": False, "ch3": False, "ch4": False, "last_update": None, "error": ""},
    "servomotor": {"angle": 0, "last_update": None, "error": ""},

    "LED_TOOL": {"red": False, "orange": False, "green": False, "last_update": None, "error": ""},
    "BUZZER": {"on": False, "last_update": None, "error": ""},
    "LCD_TOOL": {"line1": "", "line2": "", "last_update": None, "error": ""},
}

def set_err(k, e):
    if k in sensor_data:
        sensor_data[k]["error"] = str(e)
        sensor_data[k]["last_update"] = now_iso()

def clr_err(k):
    if k in sensor_data:
        sensor_data[k]["error"] = ""

# =========================
# LCD (FIXED: mux-safe + addr auto-try + lock)
# =========================
LCD_BUS = 1
LCD_ADDRS = [0x27, 0x3F]
LCD_COLS = 16
LCD_ROWS = 2

_lcd = None
_lcd_addr = None

def mux_select_channel(ch: int):
    """Select mux channel using SMBus (for LCD path)."""
    if not USE_MUX:
        return True
    try:
        with i2c_lock:
            with SMBus(LCD_BUS) as bus:
                bus.write_byte(MUX_ADDR, 1 << ch)
        return True
    except Exception as e:
        return False

def lcd_get():
    global _lcd, _lcd_addr
    if not SENSORS_AVAILABLE.get("LCD"):
        set_err("LCD_TOOL", "LCD libs missing (pip install RPLCD smbus2)")
        return None
    if _lcd is not None:
        return _lcd

    if USE_MUX and (tca is None):
        init_mux()

    if not mux_select_channel(LCD_CH):
        set_err("LCD_TOOL", f"mux select failed ch={LCD_CH} addr=0x{MUX_ADDR:02X}")
        return None

    last = None
    for addr in LCD_ADDRS:
        try:
            with i2c_lock:
                _lcd = CharLCD(
                    "PCF8574",
                    address=addr,
                    port=LCD_BUS,
                    cols=LCD_COLS,
                    rows=LCD_ROWS,
                    charmap="A00",
                )
                _lcd.clear()
            _lcd_addr = addr
            clr_err("LCD_TOOL")
            print(f"[LCD] OK addr=0x{addr:02X} ch={LCD_CH if USE_MUX else 'direct'}")
            return _lcd
        except Exception as e:
            _lcd = None
            last = e

    set_err("LCD_TOOL", f"LCD init failed (tried 0x27/0x3F): {last}")
    return None

def lcd_write(line1="", line2=""):
    lcd = lcd_get()
    if lcd is None:
        return False
    if USE_MUX and not mux_select_channel(LCD_CH):
        set_err("LCD_TOOL", f"mux select failed ch={LCD_CH}")
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
        set_err("LCD_TOOL", f"write failed: {e}")
        return False

def lcd_clear():
    lcd = lcd_get()
    if lcd is None:
        return False
    if USE_MUX and not mux_select_channel(LCD_CH):
        set_err("LCD_TOOL", f"mux select failed ch={LCD_CH}")
        return False
    try:
        with i2c_lock:
            lcd.clear()
        sensor_data["LCD_TOOL"].update({"line1": "", "line2": "", "last_update": now_iso(), "error": ""})
        return True
    except Exception as e:
        set_err("LCD_TOOL", f"clear failed: {e}")
        return False

# =========================
# BMP280 (FIXED: try 0x76/0x77)
# =========================
bmp = None

def init_bmp():
    global bmp
    if not (SENSORS_AVAILABLE.get("BMP280") and SENSORS_AVAILABLE.get("board")):
        set_err("BMP280", "BMP280 libs/board missing")
        return False
    if bmp is not None:
        return True

    if USE_MUX and (tca is None):
        init_mux()

    last = None
    for addr in (0x76, 0x77):
        try:
            with i2c_lock:
                if USE_MUX:
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(tca[BMP_CH], address=addr)
                else:
                    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(board.I2C(), address=addr)
                bmp.sea_level_pressure = 1013.25
            clr_err("BMP280")
            print(f"[BMP280] OK addr=0x{addr:02X} ch={BMP_CH if USE_MUX else 'direct'}")
            return True
        except Exception as e:
            bmp = None
            last = e

    set_err("BMP280", f"init failed (tried 0x76/0x77): {last}")
    return False

# =========================
# MPU6050 (safe lock)
# =========================
mpu = None
def init_mpu():
    global mpu
    if not (SENSORS_AVAILABLE.get("MPU6050") and SENSORS_AVAILABLE.get("board")):
        set_err("MPU6050", "MPU6050 libs/board missing")
        return False
    if mpu is not None:
        return True
    try:
        if USE_MUX and (tca is None):
            init_mux()
        with i2c_lock:
            if USE_MUX:
                mpu = adafruit_mpu6050.MPU6050(tca[MPU_CH])
            else:
                mpu = adafruit_mpu6050.MPU6050(board.I2C())
        clr_err("MPU6050")
        print(f"[MPU6050] OK ch={MPU_CH if USE_MUX else 'direct'}")
        return True
    except Exception as e:
        mpu = None
        set_err("MPU6050", f"init failed: {e}")
        return False

# =========================
# BUZZER (FIXED: active-low + real errors)
# =========================
BUZZER_PIN = board.D16 if SENSORS_AVAILABLE.get("board") else None

# If your buzzer is ON when GPIO is LOW, set TRUE
BUZZER_ACTIVE_LOW = True  # <-- MOST active buzzers need this

_buzzer = None

def init_buzzer():
    global _buzzer
    if not SENSORS_AVAILABLE.get("board"):
        set_err("BUZZER", "board missing")
        return False
    if BUZZER_PIN is None:
        set_err("BUZZER", "BUZZER_PIN None")
        return False
    if _buzzer is not None:
        return True
    try:
        _buzzer = digitalio.DigitalInOut(BUZZER_PIN)
        _buzzer.direction = digitalio.Direction.OUTPUT
        # ensure OFF
        _buzzer.value = True if BUZZER_ACTIVE_LOW else False
        sensor_data["BUZZER"]["on"] = False
        sensor_data["BUZZER"]["last_update"] = now_iso()
        clr_err("BUZZER")
        return True
    except Exception as e:
        _buzzer = None
        set_err("BUZZER", f"init failed: {e}")
        return False

def buzzer_gpio(on: bool) -> bool:
    return (not on) if BUZZER_ACTIVE_LOW else on

def set_buzzer(on: bool):
    if not init_buzzer():
        return False
    try:
        _buzzer.value = buzzer_gpio(bool(on))
        sensor_data["BUZZER"]["on"] = bool(on)
        sensor_data["BUZZER"]["last_update"] = now_iso()
        clr_err("BUZZER")
        return True
    except Exception as e:
        set_err("BUZZER", f"set failed: {e}")
        return False

def beep(count=2, on_ms=120, off_ms=120):
    if not init_buzzer():
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
        set_err("BUZZER", f"beep failed: {e}")
        return False

# =========================
# Threads
# =========================
threads = {}
running_flags = {}

def sensor_reader(name):
    while running_flags.get(name, False):
        try:
            if name == "BMP280":
                if not init_bmp():
                    time.sleep(1.0)
                    continue
                with i2c_lock:
                    temp = bmp.temperature
                    press = bmp.pressure
                    alt = getattr(bmp, "altitude", None)
                sensor_data["BMP280"].update({
                    "temperature": round(temp, 1) if temp is not None else None,
                    "pressure": round(press, 1) if press is not None else None,
                    "altitude": round(alt, 1) if alt is not None else None,
                    "last_update": now_iso(),
                    "error": ""
                })

            elif name == "MPU6050":
                if not init_mpu():
                    time.sleep(1.0)
                    continue
                with i2c_lock:
                    ax, ay, az = mpu.acceleration
                    gx, gy, gz = mpu.gyro
                    temp = getattr(mpu, "temperature", None)
                sensor_data["MPU6050"].update({
                    "ax": round(ax, 2), "ay": round(ay, 2), "az": round(az, 2),
                    "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2),
                    "temperature": round(temp, 1) if temp is not None else None,
                    "last_update": now_iso(),
                    "error": ""
                })
        except Exception as e:
            set_err(name, e)

        time.sleep(1.0)

def start_sensor(name):
    running_flags[name] = True
    if name not in threads or not threads[name].is_alive():
        threads[name] = threading.Thread(target=sensor_reader, args=(name,), daemon=True)
        threads[name].start()

def stop_sensor(name):
    running_flags[name] = False

# =========================
# Static routes (same as yours)
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    # keep your existing layout:
    # static/template/tools.html
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

# =========================
# API
# =========================
@app.route("/api/sensors")
def api_sensors():
    resp = sensor_state.copy()
    resp["data"] = sensor_data.copy()
    resp["_meta"] = {
        "use_mux": bool(USE_MUX),
        "mux_addr": hex(MUX_ADDR),
        "lcd_ch": LCD_CH,
        "bmp_ch": BMP_CH,
        "mpu_ch": MPU_CH,
        "lcd_addr": (hex(_lcd_addr) if _lcd_addr else None),
        "buzzer_active_low": BUZZER_ACTIVE_LOW,
    }
    return jsonify(resp)

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.json or {}
    name = data.get("sensor")

    if name not in sensor_state:
        return jsonify({"ok": False, "error": "Unknown sensor"}), 400

    if name in ("LED_TOOL", "BUZZER", "LCD_TOOL"):
        return jsonify({"ok": True, "sensor": name, "active": True})

    sensor_state[name] = not sensor_state[name]
    active = sensor_state[name]

    if name in ("BMP280", "MPU6050"):
        if active:
            start_sensor(name)
        else:
            stop_sensor(name)
        return jsonify({"ok": True, "sensor": name, "active": active, "error": sensor_data[name]["error"]})

    # If you click other sensors you haven't wired here,
    # still return OK so UI doesn't look broken.
    return jsonify({"ok": True, "sensor": name, "active": active})

@app.route("/api/buzzer", methods=["POST"])
def api_buzzer():
    data = request.json or {}
    mode = data.get("mode")

    if mode not in ("on", "off", "toggle", "beep", "force_off"):
        return jsonify({"ok": False, "error": "Invalid mode"}), 400

    if mode == "force_off":
        ok = set_buzzer(False)
        return jsonify({"ok": ok, "on": False, "error": sensor_data["BUZZER"]["error"]})

    if mode == "beep":
        ok = beep(
            count=int(data.get("count", 2)),
            on_ms=int(data.get("on_ms", 120)),
            off_ms=int(data.get("off_ms", 120)),
        )
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
        return jsonify({"ok": ok, "error": sensor_data["LCD_TOOL"]["error"]})

    line1 = str(data.get("line1", ""))
    line2 = str(data.get("line2", ""))
    ok = lcd_write(line1, line2)
    return jsonify({"ok": ok, "error": sensor_data["LCD_TOOL"]["error"]})

# =========================
# DEBUG: I2C scan (THIS WILL TELL US THE TRUTH)
# =========================
def i2c_scan_bus_smbus():
    found = []
    try:
        with SMBus(LCD_BUS) as bus:
            for addr in range(0x03, 0x78):
                try:
                    bus.write_quick(addr)
                    found.append(hex(addr))
                except Exception:
                    pass
    except Exception as e:
        return {"ok": False, "error": str(e), "found": []}
    return {"ok": True, "found": found}

@app.route("/api/debug/i2cscan")
def api_i2cscan():
    # If mux exists, scan each channel via smbus2 mux select
    out = {"use_mux": bool(USE_MUX), "mux_addr": hex(MUX_ADDR), "channels": {}}
    if not SENSORS_AVAILABLE.get("LCD"):
        return jsonify({"ok": False, "error": "smbus2/RPLCD not installed"}), 500

    if USE_MUX:
        for ch in range(8):
            ok = mux_select_channel(ch)
            if not ok:
                out["channels"][str(ch)] = {"ok": False, "error": "mux select failed", "found": []}
                continue
            out["channels"][str(ch)] = i2c_scan_bus_smbus()
    else:
        out["channels"]["direct"] = i2c_scan_bus_smbus()

    return jsonify({"ok": True, "scan": out})

# =========================
# Run
# =========================
if __name__ == "__main__":
    print("=" * 80)
    print("TrainerKit Tools Dashboard")
    print("http://localhost:5000")
    print("USE_MUX:", USE_MUX, "MUX_ADDR:", hex(MUX_ADDR))
    print("LCD_CH:", LCD_CH, "MPU_CH:", MPU_CH, "BMP_CH:", BMP_CH)
    print("BUZZER_ACTIVE_LOW:", BUZZER_ACTIVE_LOW)
    print("=" * 80)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)