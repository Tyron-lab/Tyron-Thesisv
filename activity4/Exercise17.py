# Exercise17.py (board / digitalio) - WARNING LED + RELAY RESPONSE
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

# ===== EDIT PINS =====
WARNING_LED_PIN = board.D13
RELAY_PINS = [board.D27, board.D10, board.D25, board.D24]  # 4 relays
LED_ACTIVE_HIGH = True
RELAY_ACTIVE_HIGH = True   # set False if your relay board is active-low
# =====================

_led = None
_relays = []
_stop_event = threading.Event()
_thread = None


def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = initial
    return io


def set_out(dev, on: bool, active_high: bool = True):
    dev.value = (on if active_high else (not on))


def _ensure_outputs():
    global _led, _relays
    if not GPIO_OK:
        return

    if _led is None:
        _led = make_out(WARNING_LED_PIN, (not LED_ACTIVE_HIGH))  # start OFF

    if not _relays:
        for p in RELAY_PINS:
            _relays.append(make_out(p, (not RELAY_ACTIVE_HIGH)))  # start OFF


def _all_relays(off=True):
    for r in _relays:
        set_out(r, (not off), RELAY_ACTIVE_HIGH)


def _relay_alarm_pattern(step_sec=0.2):
    """
    Abnormal alarm pattern:
    chase relays 1->2->3->4 repeatedly until stop() or back to normal.
    """
    n = len(_relays)
    while not _stop_event.is_set():
        for i in range(n):
            if _stop_event.is_set():
                break
            # all off then one on
            for r in _relays:
                set_out(r, False, RELAY_ACTIVE_HIGH)
            set_out(_relays[i], True, RELAY_ACTIVE_HIGH)
            time.sleep(max(0.05, float(step_sec)))

    # ensure off when stopping
    for r in _relays:
        set_out(r, False, RELAY_ACTIVE_HIGH)


def run(abnormal: bool = True, pattern_step_sec: float = 0.2):
    """
    Exercise 17: Warning Indicator (+ relay response)
    • Input: abnormal reading (bool)
    • Normal: LED OFF + relays OFF
    • Abnormal: LED ON + relays run alarm sequence
    """
    global _thread

    if not GPIO_OK:
        print("[EX17] board/digitalio not available. Simulating.")
        print(f"[EX17] import error: {_import_err}")
        return {"ok": True, "simulated": True, "abnormal": abnormal}

    _ensure_outputs()

    # stop any previous alarm thread
    stop(sequence_only=True)

    if abnormal:
        set_out(_led, True, LED_ACTIVE_HIGH)
        _stop_event.clear()
        _thread = threading.Thread(target=_relay_alarm_pattern, args=(pattern_step_sec,), daemon=True)
        _thread.start()
        msg = "ABNORMAL -> Warning LED ON + relay alarm sequence running"
    else:
        set_out(_led, False, LED_ACTIVE_HIGH)
        for r in _relays:
            set_out(r, False, RELAY_ACTIVE_HIGH)
        msg = "NORMAL -> Warning LED OFF + relays OFF"

    print(f"[EX17] {msg}")
    return {"ok": True, "abnormal": abnormal, "message": msg}


def stop(sequence_only: bool = False):
    """
    Stops alarm pattern thread.
    If sequence_only=False, also deinit everything.
    """
    global _thread, _led, _relays

    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=1.0)
    _thread = None

    # force OFF
    if GPIO_OK and _led:
        set_out(_led, False, LED_ACTIVE_HIGH)
    for r in _relays:
        try:
            set_out(r, False, RELAY_ACTIVE_HIGH)
        except Exception:
            pass

    if not sequence_only:
        # cleanup
        if GPIO_OK and _led:
            try:
                _led.deinit()
            except Exception:
                pass
            _led = None

        for r in _relays:
            try:
                r.deinit()
            except Exception:
                pass
        _relays = []

    print("[EX17] stopped")
    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo
    run(True, pattern_step_sec=0.2)   # abnormal for 3 sec
    time.sleep(3)
    run(False)                        # back to normal
    time.sleep(1)
    stop()