# Exercise19.py (board / digitalio version)
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
RELAY_PIN = [board.D27, board.D10, board.D26, board.D25]         # change to your relay pin (ex: "D23", "D24", "D17")
ACTIVE_HIGH = True         # True = HIGH turns relay ON, False = LOW turns relay ON
# ============================

_running = False
_relay = None


def _get_pin(pin_name: str):
    """Convert 'D24' -> board.D24 safely."""
    if not GPIO_OK:
        return None
    try:
        return getattr(board, pin_name)
    except AttributeError:
        raise ValueError(f"Invalid board pin name: {pin_name} (example: 'D24')")


def _ensure_relay():
    global _relay
    if _relay is not None or not GPIO_OK:
        return
    pin = _get_pin(RELAY_PIN)
    _relay = digitalio.DigitalInOut(pin)
    _relay.direction = digitalio.Direction.OUTPUT
    # start OFF (depends on active logic)
    _relay.value = (not ACTIVE_HIGH)


def _set_relay(on: bool):
    """Turn relay on/off respecting ACTIVE_HIGH."""
    if on:
        _relay.value = True if ACTIVE_HIGH else False
    else:
        _relay.value = False if ACTIVE_HIGH else True


def _relay_is_on() -> bool:
    """Return True if relay is currently ON respecting ACTIVE_HIGH."""
    if ACTIVE_HIGH:
        return bool(_relay.value)
    return not bool(_relay.value)


def run(command: str = "on"):
    """
    Exercise 19: Device Control
    • Input: Control command
    • What happens: Relay switches
    • Output: External device turns ON/OFF
    """
    global _running
    _running = True

    cmd = (command or "").strip().lower()

    if not GPIO_OK:
        print("[EX19] board/digitalio not available. Simulating.")
        print(f"[EX19] import error: {_import_err}")
        print(f"[EX19] command={cmd} (relay would change state)")
        return {"ok": True, "simulated": True, "command": cmd}

    _ensure_relay()

    if cmd == "on":
        _set_relay(True)
        msg = "Relay ON"
    elif cmd == "off":
        _set_relay(False)
        msg = "Relay OFF"
    elif cmd == "toggle":
        _set_relay(not _relay_is_on())
        msg = f"Relay TOGGLED → {'ON' if _relay_is_on() else 'OFF'}"
    else:
        msg = "Invalid command (use: on / off / toggle)"
        print(f"[EX19] {msg}")
        return {"ok": False, "error": msg}

    print(f"[EX19] {msg}")
    return {"ok": True, "command": cmd, "state": _relay_is_on(), "message": msg}


def stop():
    """Stop and force relay OFF."""
    global _running, _relay
    _running = False

    if GPIO_OK and _relay:
        _set_relay(False)
        _relay.deinit()
        _relay = None

    print("[EX19] stopped")
    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo
    run("on")
    time.sleep(1)
    run("off")
    time.sleep(1)
    run("toggle")
    time.sleep(1)
    stop()