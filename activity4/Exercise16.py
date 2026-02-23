# Activity 4 - Exercise 16: Power Indicator (LOADING SEQUENCE + GAME-STYLE BEEP)
# Input: System turned ON (script starts)
# Output: LED boot blink + relay loading sequence + buzzer beeps, then steady ON

import time
import board
import digitalio

# ===== EDIT PINS =====
POWER_LED_PIN = board.D5  # GREEN LED
RELAY_PINS = [board.D27, board.D10, board.D25, board.D24]  # 4 relays
BUZZER_PIN = board.D6     # <-- SET YOUR BUZZER PIN (ACTIVE BUZZER)

LED_ACTIVE_HIGH = True
RELAY_ACTIVE_HIGH = True   # set False if your relay board is active-low
BUZZER_ACTIVE_HIGH = True  # most active buzzers: True = ON

BOOT_STEP_SEC = 0.25       # speed of loading steps
BOOT_LOOPS = 2             # how many times to repeat the loading animation
# =====================


def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = initial
    return io


def set_out(dev, on: bool, active_high: bool = True):
    dev.value = (on if active_high else (not on))


def all_relays(relays, on: bool):
    for r in relays:
        set_out(r, on, RELAY_ACTIVE_HIGH)


def relay_loading(relays, step_sec=0.25, loops=1):
    """
    Loading sequence:
      - relay chase 1->2->3->4
      - then brief fill
    """
    for _ in range(max(1, int(loops))):
        for i in range(len(relays)):
            all_relays(relays, False)
            set_out(relays[i], True, RELAY_ACTIVE_HIGH)
            time.sleep(step_sec)

        all_relays(relays, True)
        time.sleep(step_sec * 2)

        all_relays(relays, False)
        time.sleep(step_sec)


def beep(buzzer, on_sec=0.06, off_sec=0.12):
    """Single beep pulse (active buzzer: just ON/OFF)."""
    set_out(buzzer, True, BUZZER_ACTIVE_HIGH)
    time.sleep(max(0.01, float(on_sec)))
    set_out(buzzer, False, BUZZER_ACTIVE_HIGH)
    time.sleep(max(0.01, float(off_sec)))


def csgo_style_countdown_beeps(buzzer, total_sec=3.0):
    """
    Game-style escalating beeps:
    starts slower, ends faster (like a countdown feel).
    """
    t_end = time.time() + max(0.2, float(total_sec))

    # start slow → end fast
    on_sec = 0.05
    off_start = 0.22
    off_end = 0.05

    while time.time() < t_end:
        # progress 0..1
        prog = 1.0 - max(0.0, (t_end - time.time()) / total_sec)
        off_sec = off_start + (off_end - off_start) * prog
        beep(buzzer, on_sec=on_sec, off_sec=off_sec)


def main():
    power_led = None
    buzzer = None
    relays = []

    try:
        power_led = make_out(POWER_LED_PIN, (not LED_ACTIVE_HIGH))  # OFF
        buzzer = make_out(BUZZER_PIN, (not BUZZER_ACTIVE_HIGH))     # OFF
        for p in RELAY_PINS:
            relays.append(make_out(p, (not RELAY_ACTIVE_HIGH)))     # OFF

        print("Exercise 16: System starting... (loading + countdown beeps)")

        # ---- BOOT ANIMATION ----
        # for each loop: blink LED + relay loading + accelerating beeps
        for _ in range(max(1, int(BOOT_LOOPS))):
            set_out(power_led, True, LED_ACTIVE_HIGH)

            # run relay loading while beeping "countdown style"
            # (time is matched roughly to one relay_loading cycle)
            approx_cycle_time = (len(relays) * BOOT_STEP_SEC) + (BOOT_STEP_SEC * 2) + BOOT_STEP_SEC
            csgo_style_countdown_beeps(buzzer, total_sec=approx_cycle_time)
            relay_loading(relays, step_sec=BOOT_STEP_SEC, loops=1)

            set_out(power_led, False, LED_ACTIVE_HIGH)
            time.sleep(BOOT_STEP_SEC)

        # ---- READY CONFIRMATION ----
        # long beep = "system ready"
        set_out(buzzer, True, BUZZER_ACTIVE_HIGH)
        time.sleep(0.18)
        set_out(buzzer, False, BUZZER_ACTIVE_HIGH)

        # ---- RUNNING MODE ----
        set_out(power_led, True, LED_ACTIVE_HIGH)
        all_relays(relays, True)
        print("System ready -> Power LED ON + all relays ON. Ctrl+C to stop.")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        # OFF everything + cleanup
        try:
            if power_led:
                set_out(power_led, False, LED_ACTIVE_HIGH)
        except Exception:
            pass

        try:
            if buzzer:
                set_out(buzzer, False, BUZZER_ACTIVE_HIGH)
        except Exception:
            pass

        for r in relays:
            try:
                set_out(r, False, RELAY_ACTIVE_HIGH)
            except Exception:
                pass

        try:
            if power_led:
                power_led.deinit()
        except Exception:
            pass

        try:
            if buzzer:
                buzzer.deinit()
        except Exception:
            pass

        for r in relays:
            try:
                r.deinit()
            except Exception:
                pass

        print("Power LED OFF + relays OFF + buzzer OFF. Done.")


if __name__ == "__main__":
    main()