# Exercise17.py
import time

try:
    from gpiozero import LED
    GPIO_OK = True
except Exception:
    LED = None
    GPIO_OK = False

# ===== EDIT PIN (BCM) =====
WARNING_LED_PIN = 13
# ==========================

_running = False
_led = LED(WARNING_LED_PIN) if GPIO_OK else None


def run(abnormal: bool = True):
    """
    Input: abnormal (bool)
    Output: warning LED lights up if abnormal
    """
    global _running
    _running = True

    if not GPIO_OK:
        print("[EX17] gpiozero not available. Simulating.")
        print(f"[EX17] abnormal={abnormal} => LED {'ON' if abnormal else 'OFF'}")
        return {"ok": True, "simulated": True, "abnormal": abnormal}

    if abnormal:
        _led.on()
        msg = "WARNING: Abnormal reading → LED ON"
    else:
        _led.off()
        msg = "Normal reading → LED OFF"

    print(f"[EX17] {msg}")
    return {"ok": True, "abnormal": abnormal, "message": msg}


def stop():
    global _running
    _running = False
    if GPIO_OK and _led:
        _led.off()
    print("[EX17] stopped")
    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo
    run(True)
    time.sleep(2)
    run(False)
    time.sleep(1)
    stop()