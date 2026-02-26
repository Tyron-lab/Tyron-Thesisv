# activity5/Exercise23.py
# Exercise 23: Local Data Storage (PIR + BMP280 via TCA9548A CH2 + Buzzer -> Save to file)
#
# PIR pin   : board.D22
# Buzzer pin: board.D21
# BMP280    : I2C through TCA9548A MUX @ 0x70 on channel 2
#
# Optional: also logs MQTT telemetry topic trainerkit/a5/telemetry
# (set A5_EX23_ENABLE_MQTT=0 to disable)
#
# Storage:
#   activity5/logs/ex23_events.csv
#   activity5/logs/ex23_events.jsonl
#
# Stop: Ctrl+C or dashboard Stop button

import os
import json
import csv
import time
import signal
from datetime import datetime
import threading
import queue

import paho.mqtt.client as mqtt

# -----------------------------
# Conditional hardware imports
# -----------------------------
SENSORS_AVAILABLE = {"board": False, "digitalio": False, "bmp280": False, "tca9548a": False}
try:
    import board
    import digitalio
    SENSORS_AVAILABLE["board"] = True
    SENSORS_AVAILABLE["digitalio"] = True
except Exception:
    pass

try:
    import busio
    import adafruit_bmp280
    SENSORS_AVAILABLE["bmp280"] = True
except Exception:
    pass

try:
    from smbus2 import SMBus
    SENSORS_AVAILABLE["tca9548a"] = True
except Exception:
    pass


# -----------------------------
# TCA9548A MUX SETTINGS
# -----------------------------
USE_MUX = SENSORS_AVAILABLE["tca9548a"]
I2C_BUS = 1
MUX_ADDRESS = 0x70
BMP_MUX_CH = 2  # ✅ your request

def mux_select(ch: int):
    """
    Select one channel on TCA9548A.
    """
    if not USE_MUX:
        return
    ch = int(ch)
    if ch < 0 or ch > 7:
        return
    mask = 1 << ch
    with SMBus(I2C_BUS) as bus:
        bus.write_byte(MUX_ADDRESS, mask)


# -----------------------------
# MQTT settings (optional)
# -----------------------------
MQTT_HOST = os.getenv("A5_MQTT_HOST", "192.168.4.1")
MQTT_PORT = int(os.getenv("A5_MQTT_PORT", "1883"))
TOPIC_TELEMETRY = os.getenv("A5_TOPIC_TELEMETRY", "trainerkit/a5/telemetry")
CLIENT_ID = "trainerkit_pi_ex23_storage"

ENABLE_MQTT = os.getenv("A5_EX23_ENABLE_MQTT", "1") == "1"

# -----------------------------
# Pins (your request)
# -----------------------------
PIR_PIN = getattr(board, "D22", None) if SENSORS_AVAILABLE["board"] else None
BUZZER_PIN = getattr(board, "D21", None) if SENSORS_AVAILABLE["board"] else None
BUZZER_ACTIVE_LOW = False

# -----------------------------
# Local polling behavior
# -----------------------------
LOCAL_POLL_SECONDS = 0.15
BMP_SAMPLE_EVERY_SECONDS = 2.0
MOTION_DEBOUNCE_SECONDS = 1.0
BEEP_ON_MOTION = True

# -----------------------------
# Storage paths
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

CSV_PATH = os.path.join(LOG_DIR, "ex23_events.csv")
JSONL_PATH = os.path.join(LOG_DIR, "ex23_events.jsonl")

MAX_IN_MEMORY = 200
in_memory = []

q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
running = True


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_csv_header():
    if os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0:
        return
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "source", "topic", "event", "payload_json"])


def append_storage(ts: str, source: str, topic: str, event: str, payload: dict):
    ensure_csv_header()
    payload_json = json.dumps(payload, ensure_ascii=False)

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([ts, source, topic, event, payload_json])

    rec = {"timestamp": ts, "source": source, "topic": topic, "event": event, "payload": payload}
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    in_memory.append(rec)
    if len(in_memory) > MAX_IN_MEMORY:
        del in_memory[: len(in_memory) - MAX_IN_MEMORY]


def classify_event(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "Sensor update"

    parts = []

    pir = payload.get("pir", payload.get("motion"))
    if pir is not None:
        s = str(pir).strip().lower()
        if s in ("1", "true", "on", "yes", "detected"):
            parts.append("Motion detected")
        elif s in ("0", "false", "off", "no", "none"):
            parts.append("No motion")
        else:
            parts.append(f"Motion={pir}")

    bmp_t = payload.get("bmp_temp")
    bmp_p = payload.get("pressure")

    if bmp_t is not None:
        try:
            parts.append(f"Temp = {float(bmp_t):.1f}°C")
        except Exception:
            parts.append(f"Temp = {bmp_t}")

    if bmp_p is not None:
        try:
            parts.append(f"Pressure = {float(bmp_p):.1f} hPa")
        except Exception:
            parts.append(f"Pressure = {bmp_p}")

    return " | ".join(parts) if parts else "Sensor update"


# -----------------------------
# Local devices
# -----------------------------
pir_io = None
buzzer_io = None
bmp_sensor = None
bmp_i2c = None


def init_pir():
    global pir_io
    if not (SENSORS_AVAILABLE["board"] and SENSORS_AVAILABLE["digitalio"]) or PIR_PIN is None:
        return False
    if pir_io is None:
        pir_io = digitalio.DigitalInOut(PIR_PIN)
        pir_io.direction = digitalio.Direction.INPUT
        pir_io.pull = digitalio.Pull.DOWN
    return True


def init_buzzer():
    global buzzer_io
    if not (SENSORS_AVAILABLE["board"] and SENSORS_AVAILABLE["digitalio"]) or BUZZER_PIN is None:
        return False
    if buzzer_io is None:
        buzzer_io = digitalio.DigitalInOut(BUZZER_PIN)
        buzzer_io.direction = digitalio.Direction.OUTPUT
        buzzer_io.value = True if BUZZER_ACTIVE_LOW else False
    return True


def buzzer_set(on: bool):
    if not init_buzzer():
        return False
    buzzer_io.value = (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)
    return True


def buzzer_beep(count=1, on_ms=120, off_ms=120):
    for _ in range(max(1, int(count))):
        buzzer_set(True)
        time.sleep(max(0.01, on_ms / 1000.0))
        buzzer_set(False)
        time.sleep(max(0.01, off_ms / 1000.0))


def init_bmp280():
    """
    Create BMP280 on mux channel 2.
    IMPORTANT: select mux channel BEFORE creating I2C + sensor.
    """
    global bmp_sensor, bmp_i2c

    if not (SENSORS_AVAILABLE["bmp280"] and SENSORS_AVAILABLE["board"]):
        return False
    if not USE_MUX:
        # If smbus2 not installed, BMP on mux won't be reachable
        return False
    if bmp_sensor is not None:
        return True

    try:
        mux_select(BMP_MUX_CH)
        bmp_i2c = busio.I2C(board.SCL, board.SDA)
        bmp_sensor = adafruit_bmp280.Adafruit_BMP280_I2C(bmp_i2c)
        return True
    except Exception:
        bmp_sensor = None
        bmp_i2c = None
        return False


def read_bmp280():
    """
    Select mux channel 2 before every read.
    """
    if not init_bmp280():
        return None
    try:
        mux_select(BMP_MUX_CH)
        return {
            "bmp_temp": float(bmp_sensor.temperature),
            "pressure": float(bmp_sensor.pressure),
        }
    except Exception:
        return None


# -----------------------------
# Worker thread (file I/O)
# -----------------------------
def worker():
    while running:
        try:
            item = q.get(timeout=0.25)
        except queue.Empty:
            continue

        try:
            ts = item["timestamp"]
            source = item.get("source", "unknown")
            topic = item.get("topic", "")
            payload = item.get("payload", {}) or {}

            event = classify_event(payload)
            append_storage(ts, source, topic, event, payload)

            short_time = datetime.now().strftime("%H:%M")
            print(f"[EX23] {short_time} {event}", flush=True)

        except Exception as e:
            print("[EX23] Worker error:", e, flush=True)
        finally:
            try:
                q.task_done()
            except Exception:
                pass


# -----------------------------
# Local sensor loop
# -----------------------------
def local_sensor_loop():
    last_motion_ts = 0.0
    last_bmp_ts = 0.0

    init_pir()
    init_buzzer()
    init_bmp280()

    print("[EX23] Local sensors: PIR(D22) + Buzzer(D21) + BMP280(MUX CH2)", flush=True)

    while running:
        now = time.time()

        # PIR
        if init_pir():
            try:
                motion = bool(pir_io.value)
                if motion and (now - last_motion_ts) >= MOTION_DEBOUNCE_SECONDS:
                    last_motion_ts = now

                    if BEEP_ON_MOTION:
                        try:
                            buzzer_beep(count=1, on_ms=120, off_ms=80)
                        except Exception:
                            pass

                    try:
                        q.put_nowait({
                            "timestamp": now_iso(),
                            "source": "LOCAL",
                            "topic": "pir",
                            "payload": {"pir": 1},
                        })
                    except queue.Full:
                        pass
            except Exception:
                pass

        # BMP280 periodic
        if (now - last_bmp_ts) >= BMP_SAMPLE_EVERY_SECONDS:
            last_bmp_ts = now
            bmp_data = read_bmp280()
            if bmp_data:
                try:
                    q.put_nowait({
                        "timestamp": now_iso(),
                        "source": "LOCAL",
                        "topic": "bmp280",
                        "payload": bmp_data,
                    })
                except queue.Full:
                    pass

        time.sleep(LOCAL_POLL_SECONDS)


# -----------------------------
# MQTT (optional)
# -----------------------------
def safe_json_loads(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s}


def on_connect(client, userdata, flags, rc):
    print(f"[EX23] MQTT connected rc={rc}", flush=True)
    if rc == 0:
        client.subscribe(TOPIC_TELEMETRY)
        print(f"[EX23] Subscribed: {TOPIC_TELEMETRY}", flush=True)


def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8", errors="replace")
    payload = safe_json_loads(raw) or {}
    try:
        q.put_nowait({
            "timestamp": now_iso(),
            "source": "MQTT",
            "topic": msg.topic,
            "payload": payload,
        })
    except queue.Full:
        print("[EX23] Queue full, dropping MQTT message", flush=True)


# -----------------------------
# Exit/Cleanup
# -----------------------------
def handle_exit(*_):
    global running
    running = False


def cleanup():
    try:
        if buzzer_io is not None:
            buzzer_io.value = True if BUZZER_ACTIVE_LOW else False
            buzzer_io.deinit()
    except Exception:
        pass

    try:
        if pir_io is not None:
            pir_io.deinit()
    except Exception:
        pass


# -----------------------------
# Main
# -----------------------------
def main():
    global running

    print("[EX23] Exercise 23: Local Data Storage running...", flush=True)
    print(f"[EX23] MQTT enabled  : {ENABLE_MQTT}", flush=True)
    print(f"[EX23] CSV          : {CSV_PATH}", flush=True)
    print(f"[EX23] JSONL        : {JSONL_PATH}", flush=True)
    print(f"[EX23] MUX          : addr=0x{MUX_ADDRESS:02X} ch={BMP_MUX_CH} (USE_MUX={USE_MUX})", flush=True)
    print("[EX23] Stop         : Ctrl+C or dashboard Stop", flush=True)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=local_sensor_loop, daemon=True).start()

    client = None
    if ENABLE_MQTT:
        client = mqtt.Client(client_id=CLIENT_ID)
        client.on_connect = on_connect
        client.on_message = on_message
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            client.loop_start()
        except Exception as e:
            print("[EX23] MQTT connect failed:", e, flush=True)
            client = None

    try:
        while running:
            time.sleep(0.25)
    finally:
        running = False
        try:
            if client:
                client.loop_stop()
                client.disconnect()
        except Exception:
            pass
        cleanup()
        print("[EX23] Stopped cleanly.", flush=True)


if __name__ == "__main__":
    main()