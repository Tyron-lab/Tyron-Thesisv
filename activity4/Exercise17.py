import os
import json
import time
import signal
import sys
import queue

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

import board
import digitalio

# ----------------------------
# CONFIG
# ----------------------------
RED_LED_PIN = board.D5          # Red LED pin (matches your server mapping)
SAMPLE_RATE = 16000             # Vosk works best at 16000
BLOCK_MS = 50                   # audio block size
BLOCK_SIZE = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))

# Put your Vosk model folder here:
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "models", "vosk-model-small-en-us-0.15")

# Only detect these words (improves accuracy + speed)
GRAMMAR = '["open", "close"]'

# Debounce so it won’t spam ON/OFF if it repeats the word
COMMAND_COOLDOWN_SEC = 0.8

_should_exit = False


def main():
    global _should_exit

    # --- LED setup ---
    led = digitalio.DigitalInOut(RED_LED_PIN)
    led.direction = digitalio.Direction.OUTPUT
    led.value = False  # start OFF

    def led_on():
        led.value = True
        print("✅ OPEN -> Red LED ON")

    def led_off():
        led.value = False
        print("✅ CLOSE -> Red LED OFF")

    # --- Stop / cleanup ---
    def cleanup(*_):
        global _should_exit
        _should_exit = True
        try:
            led.value = False
        except Exception:
            pass
        try:
            led.deinit()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # --- Check model ---
    model_path = os.path.abspath(MODEL_PATH)
    if not os.path.isdir(model_path):
        print("\n❌ Vosk model not found at:")
        print(model_path)
        print("\nFix: download a Vosk English model and place it there.")
        print("Example folder name: vosk-model-small-en-us-0.15")
        cleanup()

    print("Exercise 17: Voice Command LED Control running...")
    print("Say: OPEN  -> Red LED ON")
    print("Say: CLOSE -> Red LED OFF")
    print("Ctrl+C to stop.\n")

    # --- Vosk init ---
    model = Model(model_path)
    rec = KaldiRecognizer(model, SAMPLE_RATE, GRAMMAR)
    rec.SetWords(False)

    audio_q = queue.Queue()
    last_cmd_time = 0.0

    def audio_callback(indata, frames, time_info, status):
        if status:
            # don’t crash on minor glitches
            pass
        # indata is float32 [-1..1], convert to int16 bytes
        pcm16 = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        audio_q.put(pcm16)

    # --- Audio stream ---
    with sd.InputStream(
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="float32",
        callback=audio_callback,
    ):
        while not _should_exit:
            try:
                data = audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result() or "{}")
                text = (res.get("text") or "").strip().lower()

                if not text:
                    continue

                now = time.time()
                if now - last_cmd_time < COMMAND_COOLDOWN_SEC:
                    continue

                # Detect commands
                if "open" in text:
                    led_on()
                    last_cmd_time = now
                elif "close" in text:
                    led_off()
                    last_cmd_time = now


if __name__ == "__main__":
    main()


# pip install vosk sounddevice numpy