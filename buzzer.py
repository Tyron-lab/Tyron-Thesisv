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

# Keys
START_KEY = "b"   # press this to START beeping
STOP_KEY  = "q"   # press this to STOP beeping / exit

# Safety: auto-stop beeping after N seconds (so it won't annoy neighbors)
AUTO_STOP_SECONDS = 10

# If True, buzzer will NEVER beep (hard mute)
MUTE = False

# Some buzzer modules are active-low (beep when pin is LOW).
# If your buzzer is noisy even when "off", flip this to True.
ACTIVE_LOW = False


class ActiveBuzzer:
    def __init__(self, pin, active_low=False):
        self.active_low = bool(active_low)
        self.buzzer = digitalio.DigitalInOut(pin)
        self.buzzer.direction = digitalio.Direction.OUTPUT
        self._stop = threading.Event()
        self._thread = None
        self.off()  # ✅ force OFF immediately

    def _write(self, on: bool):
        if self.active_low:
            # ON = LOW, OFF = HIGH
            self.buzzer.value = (not on)
        else:
            # ON = HIGH, OFF = LOW
            self.buzzer.value = bool(on)

    def on(self):
        self._write(True)

    def off(self):
        self._write(False)

    def start_beeping(self, on_time=0.2, off_time=0.2, auto_stop_s=None):
        """Start beeping in a background thread (silent until called)."""
        if MUTE:
            self.off()
            return

        self.stop()  # stop any previous thread
        self._stop.clear()
        start_t = time.time()

        def loop():
            try:
                while not self._stop.is_set():
                    # ✅ failsafe auto-stop
                    if auto_stop_s is not None and (time.time() - start_t) >= auto_stop_s:
                        break

                    self.on()
                    time.sleep(on_time)
                    self.off()
                    time.sleep(off_time)
            finally:
                # ensure OFF when stopping
                self.off()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop beeping and force OFF."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self.off()

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
    buzzer = ActiveBuzzer(BUZZER_PIN, active_low=ACTIVE_LOW)

    print("✅ BUZZER SAFE MODE")
    print(f"- Starts SILENT")
    print(f"- Press '{START_KEY}' to start beeping (auto-stops in {AUTO_STOP_SECONDS}s)")
    print(f"- Press '{STOP_KEY}' to stop + exit")
    print("(Click the terminal first so it receives your keypress.)")

    # Put terminal into raw mode so keypresses are read instantly
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())

        # ✅ stays silent until you press 'b'
        while True:
            k = read_key_nonblocking()
            if k:
                k = k.lower()

                if k == START_KEY:
                    print("🔊 Beeping started (failsafe auto-stop on).")
                    buzzer.start_beeping(on_time=0.12, off_time=0.18, auto_stop_s=AUTO_STOP_SECONDS)

                elif k == STOP_KEY:
                    print("🛑 Stopping and exiting...")
                    break

            time.sleep(0.02)

    except KeyboardInterrupt:
        print("\n🛑 Ctrl+C pressed — stopping...")

    finally:
        # restore terminal + cleanup buzzer (FORCE OFF)
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
        buzzer.deinit()

    print("✅ Stopped (silent).")


if __name__ == "__main__":
    main()