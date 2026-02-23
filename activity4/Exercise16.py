# Activity 4 - Exercise 16: Power Indicator
# Input: System turned ON (script starts)
# Output: LED turns ON (GREEN LED)

import time
import board
import digitalio

POWER_LED_PIN = board.D5  # uses your GREEN LED from Exercise 1

def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = initial
    return io

def main():
    power_led = make_out(POWER_LED_PIN, False)

    try:
        power_led.value = True
        print("Exercise 16: System ON -> Power LED ON (D27). Ctrl+C to stop.")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        try:
            power_led.value = False
        except Exception:
            pass
        try:
            power_led.deinit()
        except Exception:
            pass
        print("Power LED OFF. Done.")

if __name__ == "__main__":
    main()
