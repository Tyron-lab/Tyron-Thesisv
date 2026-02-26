import json
import time
import random
import paho.mqtt.client as mqtt

# ==========================================
# Exercise 21: Send Sensor Data (MQTT)
# Topic must match server.py subscriber
# ==========================================

MQTT_HOST = "192.168.4.1"     # change to "localhost" if broker is on the Pi
MQTT_PORT = 1883
TOPIC = "trainerkit/a5/telemetry"

# publish rate (seconds)
INTERVAL = 1.0

def make_payload():
    """
    Replace this with real sensors later.
    For now it simulates:
      Temperature (°C), Motion (YES/NO), Noise (LOW/MEDIUM/HIGH)
    """
    temperature = random.randint(24, 35)
    motion = random.choice(["YES", "NO"])
    noise = random.choice(["LOW", "MEDIUM", "HIGH"])
    return {
        "temperature": temperature,
        "motion": motion,
        "noise": noise,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S")
    }

def main():
    client = mqtt.Client(client_id="trainerkit_ex21_sender")

    # If you later add username/pass on broker:
    # client.username_pw_set("user", "pass")

    print("Exercise 21: Send Sensor Data (MQTT)")
    print(f"Broker: {MQTT_HOST}:{MQTT_PORT}")
    print(f"Topic : {TOPIC}")
    print("Stop  : Ctrl+C\n")

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    try:
        while True:
            payload = make_payload()
            msg = json.dumps(payload)

            client.publish(TOPIC, msg, qos=0, retain=False)
            print("Sent:", msg)

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\nStopping Exercise 21...")

    finally:
        client.loop_stop()
        client.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    main()