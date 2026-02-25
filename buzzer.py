import time
import threading
import sys
import select
import termios
import tty

import board
import digitalio

# Change to your pin (example: board.D18 for GPIO18)
BUZZER_PIN = board.D16

# Press this key to stop
STOP_KEY = "q"


class ActiveBuzzer:
    def __init__(self, pin):
        self.buzzer = digitalio.DigitalInOut(pin)
        self.buzzer.direction = digitalio.Direction.OUTPUT
        self._stop = threading.Event()
        self._thread = None

    def start_beeping(self, on_time=0.2, off_time=0.2):
        """Start beeping in a background thread."""
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                self.buzzer.value = True
                time.sleep(on_time)
                self.buzzer.value = False
                time.sleep(off_time)

            # ensure OFF when stopping
            self.buzzer.value = False

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop beeping."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.buzzer.value = False

    def deinit(self):
        self.stop()
        self.buzzer.deinit()


def read_key_nonblocking():
    """Return a single key if available, else None."""
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None


def main():
    buzzer = ActiveBuzzer(BUZZER_PIN)

    print(f"Beeping... press '{STOP_KEY}' to stop.")
    print("(Click the terminal first so it receives your keypress.)")

    # Put terminal into raw mode so keypresses are read instantly
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())

        buzzer.start_beeping(on_time=0.2, off_time=0.2)

        while True:
            k = read_key_nonblocking()
            if k:
                if k.lower() == STOP_KEY:
                    break
            time.sleep(0.02)

    finally:
        # restore terminal + cleanup buzzer
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        buzzer.deinit()

    print("Stopped.")


if __name__ == "__main__":
    main()
