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
# LED PIN (TrainerKit mapping)
# ----------------------------
RED_LED_PIN = board.D5  # change if your red LED is on a different pin

# ----------------------------
# VOSK MODEL
# ----------------------------
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "models", "vosk-model-small-en-us-0.15"
)

# Vosk wants 16000 Hz
VOSK_RATE = 16000
GRAMMAR = '["open", "close"]'
COMMAND_COOLDOWN_SEC = 0.8

_should_exit = False


def downsample_to_16k(x_float32: np.ndarray, src_rate: int) -> np.ndarray:
    """
    Very simple resampler: decimate by integer factor if possible,
    else linear interpolation. Good enough for command words.
    """
    if src_rate == VOSK_RATE:
        return x_float32

    # If divisible, do integer decimation (fast + stable)
    if src_rate % VOSK_RATE == 0:
        step = src_rate // VOSK_RATE
        return x_float32[::step]

    # Otherwise, linear resample
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
    """Try to open an InputStream; return stream if OK else None."""
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
    led = digitalio.DigitalInOut(RED_LED_PIN)
    led.direction = digitalio.Direction.OUTPUT
    led.value = False

    def led_on():
        led.value = True
        print("✅ OPEN -> Red LED ON")

    def led_off():
        led.value = False
        print("✅ CLOSE -> Red LED OFF")

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
        cleanup()

    print("Exercise 17: Voice Command LED Control running...")
    print("Say: OPEN  -> Red LED ON")
    print("Say: CLOSE -> Red LED OFF")
    print("Ctrl+C to stop.\n")

    # --- Vosk init ---
    model = Model(model_path)
    rec = KaldiRecognizer(model, VOSK_RATE, GRAMMAR)
    rec.SetWords(False)

    # --- Audio queue ---
    audio_q = queue.Queue()
    last_cmd_time = 0.0

    # We'll fill these after opening stream
    chosen_rate = None

    def audio_callback(indata, frames, time_info, status):
        # Push raw float32 samples
        if status:
            # ignore minor status warnings
            pass
        audio_q.put(indata[:, 0].copy())

    # --- Pick input device ---
    dev = sd.default.device[0]  # default input device id (may be None)
    print("Default input device:", dev)

    # --- Try sample rates until one works ---
    # Most mics support 48000 or 44100; some support 16000; few support 8000.
    candidate_rates = [48000, 44100, 32000, 24000, 16000, 8000]
    stream = None

    for r in candidate_rates:
        blocksize = int(r * 0.05)  # 50ms
        stream = try_open_input_stream(dev, r, blocksize, audio_callback)
        if stream is not None:
            chosen_rate = r
            break

    if stream is None:
        print("\n❌ Could not open microphone at any common sample rate.")
        print("Next step: run device list and pick a device index manually.")
        print('Command: python -c "import sounddevice as sd; print(sd.query_devices())"')
        cleanup()

    print(f"✅ Mic stream opened at {chosen_rate} Hz")

    try:
        while not _should_exit:
            try:
                chunk = audio_q.get(timeout=0.25)
            except queue.Empty:
                continue

            # Resample to 16k for Vosk
            chunk16 = downsample_to_16k(chunk, chosen_rate)
            if len(chunk16) == 0:
                continue

            pcm16 = (chunk16 * 32767.0).astype(np.int16).tobytes()

            if rec.AcceptWaveform(pcm16):
                res = json.loads(rec.Result() or "{}")
                text = (res.get("text") or "").strip().lower()
                if not text:
                    continue

                now = time.time()
                if now - last_cmd_time < COMMAND_COOLDOWN_SEC:
                    continue

                if "open" in text:
                    led_on()
                    last_cmd_time = now
                elif "close" in text:
                    led_off()
                    last_cmd_time = now

    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        try:
            led.value = False
        except Exception:
            pass
        try:
            led.deinit()
        except Exception:
            pass


if __name__ == "__main__":
    main()