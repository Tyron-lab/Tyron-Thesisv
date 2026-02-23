# Exercise20.py (board / digitalio)
# Exercise 20: Status Feedback
# • Input: System state change
# • What happens: Pattern updated
# • Output: LED blinking pattern changes (AND relay sequence follows same pattern)

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
LED_PINS   = [board.D5, board.D6, board.D13]           # 3 LEDs (change to your pins)
RELAY_PINS = [board.D27, board.D10, board.D25, board.D24]  # 4 relays (change to your pins)

LED_ACTIVE_HIGH   = True
RELAY_ACTIVE_HIGH = True
# =====================

_leds = []
_relays = []
_stop_event = threading.Event()
_thread = None
_current_state = "off"


def _ensure_outputs():
    global _leds, _relays
    if not GPIO_OK:
        return

    if not _leds:
        for p in LED_PINS:
            d = digitalio.DigitalInOut(p)
            d.direction = digitalio.Direction.OUTPUT
            d.value = (not LED_ACTIVE_HIGH)
            _leds.append(d)

    if not _relays:
        for p in RELAY_PINS:
            r = digitalio.DigitalInOut(p)
            r.direction = digitalio.Direction.OUTPUT
            r.value = (not RELAY_ACTIVE_HIGH)
            _relays.append(r)


def _set_out(device, on: bool, active_high: bool):
    if on:
        device.value = True if active_high else False
    else:
        device.value = False if active_high else True


def _all_off():
    for d in _leds:
        _set_out(d, False, LED_ACTIVE_HIGH)
    for r in _relays:
        _set_out(r, False, RELAY_ACTIVE_HIGH)


def _apply_step(step_index: int, led_mode: str = "hold_last"):
    """
    step_index: 0..3 for relays
    led_mode:
      - 'hold_last' : step 4 uses LED3 ON
      - 'all_off'   : step 4 turns all LEDs OFF
      - 'mirror'    : step 4 turns all LEDs OFF (same as all_off)
    """
    # turn everything off first
    _all_off()

    # relay ON for this step
    _set_out(_relays[step_index], True, RELAY_ACTIVE_HIGH)

    # LED mapping:
    # step 0 -> LED0
    # step 1 -> LED1
    # step 2 -> LED2
    # step 3 -> no LED3 (because only 3 LEDs)
    if step_index < len(_leds):
        _set_out(_leds[step_index], True, LED_ACTIVE_HIGH)
    else:
        if led_mode == "hold_last" and len(_leds) > 0:
            _set_out(_leds[-1], True, LED_ACTIVE_HIGH)
        # else all LEDs remain OFF


def _runner(step_sec: float, loops: int, led_mode: str):
    """
    Runs the synchronized LED+relay sequence.
    loops=0 => infinite until stop()
    """
    n = len(_relays)
    count = 0

    while not _stop_event.is_set():
        for i in range(n):
            if _stop_event.is_set():
                break
            _apply_step(i, led_mode=led_mode)
            time.sleep(max(0.05, float(step_sec)))

        count += 1
        if loops > 0 and count >= loops:
            break

    _all_off()


def run(state: str = "normal", step_sec: float = 0.6, loops: int = 0, led_mode: str = "hold_last"):
    """
    States (suggested):
      - 'normal'  : slow sequence
      - 'warning' : faster sequence
      - 'unsafe'  : very fast sequence
      - 'off'     : stop and all off

    step_sec: base speed if you call run('normal', step_sec=0.6)
    loops: 0=infinite
    led_mode: 'hold_last' (recommended) or 'all_off' for step 4 LED behavior
    """
    global _thread, _current_state

    if not GPIO_OK:
        print("[EX20] board/digitalio not available. Simulating.")
        print(f"[EX20] import error: {_import_err}")
        print(f"[EX20] state={state} step_sec={step_sec} loops={loops}")
        return {"ok": True, "simulated": True, "state": state}

    _ensure_outputs()
    stop(sequence_only=True)

    st = (state or "").strip().lower()
    _current_state = st

    if st == "off":
        _all_off()
        return {"ok": True, "state": "off", "message": "All OFF"}

    # map state to speed
    if st == "normal":
        speed = step_sec
    elif st == "warning":
        speed = max(0.05, step_sec * 0.5)
    elif st == "unsafe":
        speed = max(0.05, step_sec * 0.25)
    else:
        # default behavior
        speed = step_sec
        st = "normal"
        _current_state = "normal"

    _stop_event.clear()
    _thread = threading.Thread(target=_runner, args=(speed, loops, led_mode), daemon=True)
    _thread.start()

    msg = f"Synchronized LED+Relay sequence running ({_current_state}, step={speed}s)"
    print(f"[EX20] {msg}")
    return {"ok": True, "state": _current_state, "step_sec": speed, "loops": loops, "message": msg}


def stop(sequence_only: bool = False):
    """
    Stops sequence. If sequence_only=False, also deinit outputs.
    """
    global _thread, _leds, _relays

    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=1.0)
    _thread = None

    if GPIO_OK and (_leds or _relays):
        _all_off()
        if not sequence_only:
            for d in _leds:
                d.deinit()
            for r in _relays:
                r.deinit()
            _leds = []
            _relays = []

    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo
    run("normal", step_sec=0.6, loops=2, led_mode="hold_last")
    time.sleep(6)
    run("warning", step_sec=0.6, loops=2, led_mode="hold_last")
    time.sleep(4)
    run("unsafe", step_sec=0.6, loops=2, led_mode="hold_last")
    time.sleep(3)
    stop()