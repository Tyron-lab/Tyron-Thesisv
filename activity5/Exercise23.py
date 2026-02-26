# activity5/Exercise23.py
# Exercise 23: Local Data Storage (MQTT Subscribe -> Save to file)
#
# Goal: Save sensor data locally for later use.
#
# Default topic: trainerkit/a5/telemetry
# You can change via environment variables:
#   A5_MQTT_HOST, A5_MQTT_PORT, A5_TOPIC_TELEMETRY
#
# Storage:
#   activity5/logs/ex23_events.csv
#   activity5/logs/ex23_events.jsonl
#
# Stop: Ctrl+C or your dashboard Stop button

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
# MQTT settings (safe defaults)
# -----------------------------
MQTT_HOST = os.getenv("A5_MQTT_HOST", "192.168.4.1")
MQTT_PORT = int(os.getenv("A5_MQTT_PORT", "1883"))
TOPIC_TELEMETRY = os.getenv("A5_TOPIC_TELEMETRY", "trainerkit/a5/telemetry")
CLIENT_ID = "trainerkit_pi_ex23_storage"

# -----------------------------
# Local storage paths
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))              # .../activity5
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

CSV_PATH = os.path.join(LOG_DIR, "ex23_events.csv")
JSONL_PATH = os.path.join(LOG_DIR, "ex23_events.jsonl")

# Keep last N events in memory (optional)
MAX_IN_MEMORY = 200
in_memory = []

# Command queue so we NEVER block MQTT thread
q: "queue.Queue[dict]" = queue.Queue(maxsize=500)
running = True


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def classify_event(payload: dict) -> str:
    """
    Turns sensor payload into a human-friendly log message.
    Accepts flexible keys (temp/temperature, noise/sound, motion/pir, etc.)
    """
    if not isinstance(payload, dict):
        return "Sensor update"

    temp = payload.get("temperature", payload.get("temp"))
    noise = payload.get("noise", payload.get("sound"))
    motion = payload.get("motion", payload.get("pir"))

    # Normalize motion value
    motion_str = None
    if motion is not None:
        s = str(motion).strip().lower()
        if s in ("1", "true", "on", "yes", "detected"):
            motion_str = "Motion detected"
        elif s in ("0", "false", "off", "no", "none"):
            motion_str = "No motion"
        else:
            motion_str = f"Motion={motion}"

    # Normalize noise
    noise_str = None
    if noise is not None:
        # If it’s already a string like "loud"
        s = str(noise).strip().lower()
        if s in ("loud", "high", "detected", "1", "true", "on", "yes"):
            noise_str = "Loud noise detected"
        else:
            noise_str = f"Noise={noise}"

    # Normalize temperature
    temp_str = None
    if temp is not None:
        try:
            t = float(temp)
            temp_str = f"Temp = {t:.1f}°C"
        except Exception:
            temp_str = f"Temp = {temp}"

    # Prefer “alert-like” messages
    parts = [p for p in (motion_str, noise_str, temp_str) if p]
    if parts:
        # if multiple, join
        return " | ".join(parts)

    return "Sensor update"


def safe_json_loads(s: str):
    s = (s or "").strip()
    if not s:
        return None
    # Allow raw text too
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s}


def ensure_csv_header():
    """
    Create CSV with headers if not exists.
    """
    if os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0:
        return
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "topic", "event", "payload_json"])


def append_storage(ts: str, topic: str, event: str, payload: dict):
    """
    Append to CSV + JSONL and keep in memory.
    """
    ensure_csv_header()

    payload_json = json.dumps(payload, ensure_ascii=False)

    # CSV
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([ts, topic, event, payload_json])

    # JSONL
    rec = {
        "timestamp": ts,
        "topic": topic,
        "event": event,
        "payload": payload,
    }
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Memory
    in_memory.append(rec)
    if len(in_memory) > MAX_IN_MEMORY:
        del in_memory[: len(in_memory) - MAX_IN_MEMORY]


# -----------------------------
# Worker thread (does file I/O)
# -----------------------------
def worker():
    while running:
        try:
            item = q.get(timeout=0.25)
        except queue.Empty:
            continue

        try:
            ts = item["timestamp"]
            topic = item["topic"]
            payload = item["payload"]

            event = classify_event(payload)
            append_storage(ts, topic, event, payload)

            # Console output for your dashboard logs (matches your example)
            # Example:
            # 12:01 Motion detected
            # 12:10 Temp = 31°C
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
# MQTT callbacks (FAST ONLY)
# -----------------------------
def on_connect(client, userdata, flags, rc):
    print(f"[EX23] MQTT connected rc={rc}", flush=True)
    if rc == 0:
        client.subscribe(TOPIC_TELEMETRY)
        print(f"[EX23] Subscribed: {TOPIC_TELEMETRY}", flush=True)


def on_message(client, userdata, msg):
    # Do not block here
    raw = msg.payload.decode("utf-8", errors="replace")
    payload = safe_json_loads(raw) or {}

    item = {
        "timestamp": now_iso(),
        "topic": msg.topic,
        "payload": payload,
    }

    try:
        q.put_nowait(item)
    except queue.Full:
        print("[EX23] Queue full, dropping message", flush=True)


def handle_exit(*_):
    global running
    running = False


def main():
    global running

    print("[EX23] Exercise 23: Local Data Storage running...", flush=True)
    print(f"[EX23] Broker: {MQTT_HOST}:{MQTT_PORT}", flush=True)
    print(f"[EX23] Topic : {TOPIC_TELEMETRY}", flush=True)
    print(f"[EX23] CSV   : {CSV_PATH}", flush=True)
    print(f"[EX23] JSONL : {JSONL_PATH}", flush=True)
    print("[EX23] Stop  : Ctrl+C or dashboard Stop", flush=True)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Start worker thread
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # MQTT client
    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as e:
        print("[EX23] MQTT connect failed:", e, flush=True)
        running = False
        return

    client.loop_start()

    try:
        while running:
            time.sleep(0.25)
    finally:
        running = False
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        print("[EX23] Stopped cleanly.", flush=True)


if __name__ == "__main__":
    main()