# Exercise7.py
# Activity 1 - Exercise 7: Sound Detection Indicator
# Input: INMP441 digital mic (I2S -> ALSA)
# What happens: measure sound level (RMS)
# Output:
#   LED ON when loud
#   LED OFF when quiet
#
# LED pin: board.D13 (Blinka / digitalio)

import time
import threading
import numpy as np
import sounddevice as sd

import board
import digitalio


class Exercise7:
    def __init__(
        self,
        led_pin=board.D13,    # <-- you said you're using board.D13
        threshold=0.03,       # Tune: lower = more sensitive
        sample_rate=16000,
        block_ms=50,
        device=None,          # ALSA device index if needed
    ):
        self.led_pin = led_pin
        self.threshold = float(threshold)
        self.sample_rate = int(sample_rate)
        self.block_ms = int(block_ms)
        self.device = device

        self._stop = threading.Event()
        self._thread = None
        self._stream = None

        self.last_rms = 0.0
        self.led_on = False

        self._led = None  # digitalio object

    # -------------------------
    # Public API
    # -------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

        # Stop audio stream safely
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

        # LED OFF + release pin
        try:
            if self._led is not None:
                self._led.value = False
                self._led.deinit()
        except Exception:
            pass
        self._led = None

        self.led_on = False

    def status(self):
        running = bool(self._thread and self._thread.is_alive())
        return {
            "running": running,
            "rms": round(float(self.last_rms), 6),
            "threshold": self.threshold,
            "led": "ON" if self.led_on else "OFF",
            "pin": "board.D13",
        }

    # -------------------------
    # Internal runner
    # -------------------------
    def _run(self):
        # Setup LED pin (digitalio)
        self._led = digitalio.DigitalInOut(self.led_pin)
        self._led.direction = digitalio.Direction.OUTPUT
        self._led.value = False

        blocksize = max(1, int(self.sample_rate * (self.block_ms / 1000.0)))

        def callback(indata, frames, time_info, status):
            try:
                x = indata
                # flatten to mono
                if x.ndim == 2 and x.shape[1] > 1:
                    x = np.mean(x, axis=1)
                else:
                    x = x.reshape(-1)

                rms = float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))
                self.last_rms = rms

                loud = rms >= self.threshold
                self.led_on = loud
                if self._led is not None:
                    self._led.value = bool(loud)
            except Exception:
                pass

        # Start audio input stream
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=blocksize,
            device=self.device,
        )
        self._stream.start()

        while not self._stop.is_set():
            time.sleep(0.05)

        # stop() handles cleanup