# Exercise19.py (board / digitalio) - 4 RELAY SEQUENCE
import time
import threading

try:
    import board
    import digitalio
    GPIO_OK = True
except Exception as e:
    board = None
    digitalio = None
    GPIO_OK = False
    _import_err = e

# ===== EDIT PINS (board) =====
RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]  # 4-channel relay
ACTIVE_HIGH = True   # True = HIGH turns relay ON, False = LOW turns relay ON
# ============================

_relays = []          # list[digitalio.DigitalInOut]
_stop_event = threading.Event()
_thread = None


def _ensure_relays():
    global _relays
    if not GPIO_OK:
        return
    if _relays:
        return

    for pin in RELAY_PINS:
        r = digitalio.DigitalInOut(pin)
        r.direction = digitalio.Direction.OUTPUT
        # start OFF
        r.value = (not ACTIVE_HIGH)
        _relays.append(r)


def _set_relay(idx: int, on: bool):
    """idx is 0-based"""
    r = _relays[idx]
    if on:
        r.value = True if ACTIVE_HIGH else False
    else:
        r.value = False if ACTIVE_HIGH else True


def _relay_is_on(idx: int) -> bool:
    r = _relays[idx]
    return bool(r.value) if ACTIVE_HIGH else (not bool(r.value))


def _all_off():
    for i in range(len(_relays)):
        _set_relay(i, False)


def _all_on():
    for i in range(len(_relays)):
        _set_relay(i, True)


def _sequence_worker(step_sec: float, loops: int):
    """
    Turn ON one relay at a time, then OFF, moving to the next.
    loops=0 means infinite until stop()
    """
    n = len(_relays)
    count = 0

    while not _stop_event.is_set():
        for i in range(n):
            if _stop_event.is_set():
                break

            _all_off()
            _set_relay(i, True)
            print(f"[EX19] SEQ relay {i+1} ON")
            time.sleep(max(0.05, float(step_sec)))

        count += 1
        if loops > 0 and count >= loops:
            break

    _all_off()
    print("[EX19] SEQ done")


def run(command: str = "sequence", step_sec: float = 0.6, loops: int = 1):
    """
    Exercise 19: Device Control (4-relay)
    Commands:
      - 'seq'/'sequence' : run sequence (relay1->relay4). step_sec controls speed. loops repeats.
      - 'all_on' / 'all_off'
      - 'toggle' : toggle all relays
      - 'on:1' 'off:3' 'toggle:4' : per relay (1-4)
    """
    global _thread

    cmd = (command or "").strip().lower()

    if not GPIO_OK:
        print("[EX19] board/digitalio not available. Simulating.")
        print(f"[EX19] import error: {_import_err}")
        print(f"[EX19] command={cmd}")
        return {"ok": True, "simulated": True, "command": cmd}

    _ensure_relays()

    # stop any previous sequence thread
    stop(sequence_only=True)

    # ---- sequence ----
    if cmd in ("seq", "sequence"):
        _stop_event.clear()
        _thread = threading.Thread(target=_sequence_worker, args=(step_sec, loops), daemon=True)
        _thread.start()
        msg = f"Sequence started (step={step_sec}s, loops={loops})"
        print(f"[EX19] {msg}")
        return {"ok": True, "command": cmd, "message": msg}

    # ---- all on/off ----
    if cmd == "all_on":
        _all_on()
        return {"ok": True, "command": cmd, "states": [_relay_is_on(i) for i in range(len(_relays))]}
    if cmd == "all_off":
        _all_off()
        return {"ok": True, "command": cmd, "states": [_relay_is_on(i) for i in range(len(_relays))]}

    # ---- toggle all ----
    if cmd == "toggle":
        for i in range(len(_relays)):
            _set_relay(i, not _relay_is_on(i))
        return {"ok": True, "command": cmd, "states": [_relay_is_on(i) for i in range(len(_relays))]}

    # ---- per relay: on:1 off:2 toggle:4 ----
    if ":" in cmd:
        action, num = cmd.split(":", 1)
        action = action.strip()
        try:
            ch = int(num.strip()) - 1  # user 1-4
        except ValueError:
            return {"ok": False, "error": "Bad channel. Use on:1, off:2, toggle:4"}

        if not (0 <= ch < len(_relays)):
            return {"ok": False, "error": f"Channel out of range. Use 1-{len(_relays)}"}

        if action == "on":
            _set_relay(ch, True)
        elif action == "off":
            _set_relay(ch, False)
        elif action == "toggle":
            _set_relay(ch, not _relay_is_on(ch))
        else:
            return {"ok": False, "error": "Bad action. Use on/off/toggle"}

        return {"ok": True, "command": cmd, "states": [_relay_is_on(i) for i in range(len(_relays))]}

    return {"ok": False, "error": "Invalid command. Try: sequence, all_on, all_off, toggle, on:1, off:2, toggle:4"}


def stop(sequence_only: bool = False):
    """
    Stops sequence thread (if running).
    If sequence_only=False, also turns all relays OFF and deinit.
    """
    global _thread, _relays

    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=1.0)
    _thread = None

    if GPIO_OK and _relays:
        _all_off()

        if not sequence_only:
            for r in _relays:
                r.deinit()
            _relays = []

    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo: run sequence once
    run("sequence", step_sec=0.5, loops=2)
    time.sleep(5)
    stop()