# Activity 4 - Exercise 16: Power Indicator (LOADING SEQUENCE)
# Input: System turned ON (script starts)
# Output: LED boot blink + relay loading sequence, then steady ON

import time
import board
import digitalio

# ===== EDIT PINS =====
POWER_LED_PIN = board.D5  # GREEN LED
RELAY_PINS = [board.D27, board.D10, board.D25, board.D24]  # 4 relays

LED_ACTIVE_HIGH = True
RELAY_ACTIVE_HIGH = True   # set False if your relay board is active-low

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


def relay_loading(relays, step_sec=0.25, loops=2):
    """
    Loading sequence:
      - LED blink + relay chase 1->2->3->4
      - Then fill up 1+2+3+4 briefly
    """
    for _ in range(max(1, int(loops))):
        # chase
        for i in range(len(relays)):
            all_relays(relays, False)
            set_out(relays[i], True, RELAY_ACTIVE_HIGH)
            time.sleep(step_sec)

        # fill
        all_relays(relays, True)
        time.sleep(step_sec * 2)

        # clear
        all_relays(relays, False)
        time.sleep(step_sec)


def main():
    power_led = None
    relays = []

    try:
        power_led = make_out(POWER_LED_PIN, (not LED_ACTIVE_HIGH))  # OFF
        for p in RELAY_PINS:
            relays.append(make_out(p, (not RELAY_ACTIVE_HIGH)))     # OFF

        print("Exercise 16: System starting... (loading sequence)")

        # ---- BOOT ANIMATION ----
        for _ in range(max(1, int(BOOT_LOOPS))):
            # LED blink + relay chase once per loop
            set_out(power_led, True, LED_ACTIVE_HIGH)
            relay_loading(relays, step_sec=BOOT_STEP_SEC, loops=1)
            set_out(power_led, False, LED_ACTIVE_HIGH)
            time.sleep(BOOT_STEP_SEC)

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

        for r in relays:
            try:
                r.deinit()
            except Exception:
                pass

        print("Power LED OFF + relays OFF. Done.")


if __name__ == "__main__":
    main()