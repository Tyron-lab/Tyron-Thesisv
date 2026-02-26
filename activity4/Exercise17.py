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
# LED PINS (TrainerKit mapping)
# ----------------------------
RED_LED_PIN    = board.D5
ORANGE_LED_PIN = board.D6
GREEN_LED_PIN  = board.D13

# ----------------------------
# VOSK MODEL
# ----------------------------
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "models", "vosk-model-small-en-us-0.15"
)

VOSK_RATE = 16000

# Expanded grammar for better accuracy
GRAMMAR = '["open", "close", "red", "orange", "green"]'
COMMAND_COOLDOWN_SEC = 0.6

_should_exit = False


def downsample_to_16k(x_float32: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate == VOSK_RATE:
        return x_float32

    if src_rate % VOSK_RATE == 0:
        step = src_rate // VOSK_RATE
        return x_float32[::step]

    n_src = len(x_float32)
    n_dst = int(round(n_src * (VOSK_RATE / src_rate)))
    if n_dst <= 0:
        return np.empty((0,), dtype=np.float32)

    src_idx = np.linspace(0, n_src - 1, num=n_dst, dtype=np.float32)
    lo = np.floor(src_idx).astype(np.int32)
    hi = np.minimum(lo + 1, n_src - 1)
    frac = src_idx - lo
    return (x_float32[lo] * (1.0 - frac) + x_float32[hi] * frac).astype(np.float32)


def try_open_input_stream(device, samplerate, blocksize, callback):
    try:
        stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="float32",
            callback=callback,
        )
        stream.start()
        return stream
    except Exception:
        return None


def main():
    global _should_exit

    # --- LED setup ---
    led_red = digitalio.DigitalInOut(RED_LED_PIN)
    led_orange = digitalio.DigitalInOut(ORANGE_LED_PIN)
    led_green = digitalio.DigitalInOut(GREEN_LED_PIN)

    for led in (led_red, led_orange, led_green):
        led.direction = digitalio.Direction.OUTPUT
        led.value = False

    def set_led(color: str, on: bool):
        color = (color or "").lower()
        led = {"red": led_red, "orange": led_orange, "green": led_green}.get(color)
        if led is None:
            return
        led.value = bool(on)
        state = "ON" if on else "OFF"
        print(f"✅ {color.upper()} -> {state}")

    def cleanup(*_):
        global _should_exit
        _should_exit = True
        try:
            for led in (led_red, led_orange, led_green):
                try:
                    led.value = False
                except Exception:
                    pass
        finally:
            for led in (led_red, led_orange, led_green):
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
        cleanup()

    print("Exercise 17: Voice Command LED Control running...")
    print("Commands:")
    print("  OPEN / CLOSE            -> RED on/off")
    print("  RED OPEN / RED CLOSE    -> RED on/off")
    print("  ORANGE OPEN/CLOSE       -> ORANGE on/off")
    print("  GREEN OPEN/CLOSE        -> GREEN on/off")
    print("Ctrl+C to stop.\n")

    # --- Vosk init ---
    model = Model(model_path)
    rec = KaldiRecognizer(model, VOSK_RATE, GRAMMAR)
    rec.SetWords(False)

    audio_q = queue.Queue()
    last_cmd_time = 0.0
    chosen_rate = None

    def audio_callback(indata, frames, time_info, status):
        if status:
            pass
        audio_q.put(indata[:, 0].copy())

    # Default input device
    dev = sd.default.device[0]
    print("Default input device:", dev)

    # Try sample rates
    candidate_rates = [48000, 44100, 32000, 24000, 16000, 8000]
    stream = None
    for r in candidate_rates:
        blocksize = int(r * 0.05)
        stream = try_open_input_stream(dev, r, blocksize, audio_callback)
        if stream is not None:
            chosen_rate = r
            break

    if stream is None:
        print("\n❌ Could not open microphone at any common sample rate.")
        print('Run: python -c "import sounddevice as sd; print(sd.query_devices())"')
        cleanup()

    print(f"✅ Mic stream opened at {chosen_rate} Hz")

    def parse_command(text: str):
        """
        Returns (color, action) where:
          color in {"red","orange","green"} or None
          action in {"open","close"} or None
        """
        t = (text or "").strip().lower()
        if not t:
            return (None, None)

        words = t.split()

        action = None
        if "open" in words:
            action = "open"
        elif "close" in words:
            action = "close"

        color = None
        if "red" in words:
            color = "red"
        elif "orange" in words:
            color = "orange"
        elif "green" in words:
            color = "green"

        # Backward compatible: plain OPEN/CLOSE controls RED
        if action and color is None:
            color = "red"

        return (color, action)

    try:
        while not _should_exit:
            try:
                chunk = audio_q.get(timeout=0.25)
            except queue.Empty:
                continue

            chunk16 = downsample_to_16k(chunk, chosen_rate)
            if len(chunk16) == 0:
                continue

            pcm16 = (chunk16 * 32767.0).astype(np.int16).tobytes()

            if rec.AcceptWaveform(pcm16):
                res = json.loads(rec.Result() or "{}")
                text = (res.get("text") or "").strip().lower()
                if not text:
                    continue

                color, action = parse_command(text)
                if not action or not color:
                    continue

                now = time.time()
                if now - last_cmd_time < COMMAND_COOLDOWN_SEC:
                    continue

                if action == "open":
                    set_led(color, True)
                    last_cmd_time = now
                elif action == "close":
                    set_led(color, False)
                    last_cmd_time = now

    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        cleanup()


if __name__ == "__main__":
    main()