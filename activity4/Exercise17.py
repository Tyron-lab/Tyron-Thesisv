# Exercise17.py (board / digitalio version)
import time

try:
    import board
    import digitalio
    GPIO_OK = True
except Exception as e:
    board = None
    digitalio = None
    GPIO_OK = False
    _import_err = e

# ===== EDIT PIN (board) =====
WARNING_LED_PIN = "D13"   # e.g. "D13", "D17", etc.
# ============================

_running = False
_led = None


def _get_pin(pin_name: str):
    """Convert 'D13' -> board.D13 safely."""
    if not GPIO_OK:
        return None
    try:
        return getattr(board, pin_name)
    except AttributeError:
        raise ValueError(f"Invalid board pin name: {pin_name} (example: 'D13')")


def _ensure_led():
    global _led
    if _led is not None or not GPIO_OK:
        return
    pin = _get_pin(WARNING_LED_PIN)
    _led = digitalio.DigitalInOut(pin)
    _led.direction = digitalio.Direction.OUTPUT
    _led.value = False  # start OFF


def run(abnormal: bool = True):
    """
    Input: abnormal (bool)
    Output: warning LED lights up if abnormal
    """
    global _running
    _running = True

    if not GPIO_OK:
        print("[EX17] board/digitalio not available. Simulating.")
        print(f"[EX17] import error: {_import_err}")
        print(f"[EX17] abnormal={abnormal} => LED {'ON' if abnormal else 'OFF'}")
        return {"ok": True, "simulated": True, "abnormal": abnormal}

    _ensure_led()

    if abnormal:
        _led.value = True
        msg = "WARNING: Abnormal reading → LED ON"
    else:
        _led.value = False
        msg = "Normal reading → LED OFF"

    print(f"[EX17] {msg}")
    return {"ok": True, "abnormal": abnormal, "message": msg}


def stop():
    global _running, _led
    _running = False

    if GPIO_OK and _led:
        _led.value = False
        _led.deinit()
        _led = None

    print("[EX17] stopped")
    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    run(True)
    time.sleep(2)
    run(False)
    time.sleep(1)
    stop()