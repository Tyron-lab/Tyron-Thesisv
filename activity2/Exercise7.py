# Exercise 7 (Activity 2): Voice Activated Relay & Servo Controller
# Uses VOSK speech recognition (INMP441 I2S microphone)
#
# Voice Commands:
#   "open relay"   → All Relays ON
#   "close relay"  → All Relays OFF
#   "open servo"   → Servo 90°
#   "close servo"  → Servo 0°
#   "stop servo"   → Servo neutral + stop
#   "open all"     → Relays ON + Servo 90°
#   "close all"    → Relays OFF + Servo 0°
#
# Relay pins: CH1=D27, CH2=D10, CH3=D26, CH4=D25 (active-low)
# Servo pin:  D12 (PWM 50Hz)
# Mic:        INMP441 I2S device=1, 48000Hz

import time
import signal
import sys
import os
import json

import board
import digitalio
import pwmio

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# ────────────────────────────────────────────────
# RELAY SETUP (active-low)
# ────────────────────────────────────────────────
RELAY_ACTIVE_LOW = True
RELAY_PIN_LIST   = [board.D27, board.D10, board.D26, board.D25]

relay_ios = []
for _pin in RELAY_PIN_LIST:
    _io = digitalio.DigitalInOut(_pin)
    _io.direction = digitalio.Direction.OUTPUT
    _io.value = True  # OFF (active-low)
    relay_ios.append(_io)

def _relay_val(on: bool) -> bool:
    return (not on) if RELAY_ACTIVE_LOW else on

def all_relays_on():
    for io in relay_ios:
        io.value = _relay_val(True)
    print("[RELAY] ALL ON")

def all_relays_off():
    for io in relay_ios:
        io.value = _relay_val(False)
    print("[RELAY] ALL OFF")

# ────────────────────────────────────────────────
# SERVO SETUP (D12, 50Hz PWM)
# ────────────────────────────────────────────────
SERVO_PIN = board.D12
FREQUENCY = 50
MIN_PULSE = 500
MAX_PULSE = 2500
servo_pwm = None

def _servo_init():
    global servo_pwm
    if servo_pwm is None:
        servo_pwm = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

def set_servo_angle(angle: int):
    global servo_pwm
    _servo_init()
    angle    = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (angle / 180.0)
    duty     = int((pulse_us / 20000.0) * 65535.0)
    servo_pwm.duty_cycle = duty
    print(f"[SERVO] angle={angle}")

def servo_stop():
    global servo_pwm
    try:
        _servo_init()
        neutral_duty = int((1500 / 20000.0) * 65535)
        servo_pwm.duty_cycle = neutral_duty
        time.sleep(0.35)
        servo_pwm.duty_cycle = 0
        time.sleep(0.05)
        servo_pwm.deinit()
    except Exception as e:
        print(f"[SERVO] stop error: {e}")
    servo_pwm = None
    print("[SERVO] STOPPED")

# ────────────────────────────────────────────────
# VOSK SETUP
# ────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "..", "models", "vosk-model-small-en-us-0.15")
if not os.path.isdir(VOSK_MODEL_PATH):
    VOSK_MODEL_PATH = os.path.join(BASE_DIR, "models", "vosk-model-small-en-us-0.15")

GRAMMAR      = '["open", "close", "stop", "fast", "relay", "servo", "all", "[unk]"]'
SAMPLE_RATE  = 48000
VOSK_SR      = 16000
BLOCK_MS     = 20
BLOCK_SIZE   = int(SAMPLE_RATE * (BLOCK_MS / 1000.0))
INPUT_DEVICE = 1

print("Loading VOSK model...")
if not os.path.isdir(VOSK_MODEL_PATH):
    print(f"ERROR: VOSK model not found at {VOSK_MODEL_PATH}")
    sys.exit(1)

model = Model(VOSK_MODEL_PATH)
rec   = KaldiRecognizer(model, VOSK_SR)
rec.SetGrammar(GRAMMAR)
print("VOSK model loaded!")

# ────────────────────────────────────────────────
# COMMAND HANDLER
# ────────────────────────────────────────────────
def handle_command(text: str):
    t = text.strip().lower()
    if not t or t == "[unk]":
        return
    print(f"[HEARD] '{t}'")
    if "open" in t and "relay" in t:
        all_relays_on()
    elif "close" in t and "relay" in t:
        all_relays_off()
    elif "fast" in t and "servo" in t:
        set_servo_angle(180)
    elif "open" in t and "servo" in t:
        set_servo_angle(90)
    elif "stop" in t and "servo" in t:
        servo_stop()
    elif "open" in t and "all" in t:
        all_relays_on()
        set_servo_angle(90)
    elif "close" in t and "all" in t:
        all_relays_off()
        servo_stop()
    else:
        print(f"[CMD] Unknown: '{t}'")

# ────────────────────────────────────────────────
# AUDIO RESAMPLER 48000 -> 16000
# ────────────────────────────────────────────────
def resample_to_16k(x: np.ndarray, src_sr: int) -> np.ndarray:
    if src_sr == VOSK_SR:
        return x
    step = src_sr // VOSK_SR
    if src_sr % VOSK_SR == 0 and step > 1:
        return x[::step].astype(np.float32)
    dst_len = int(len(x) * VOSK_SR / src_sr)
    if dst_len <= 1:
        return x[:1].astype(np.float32)
    src_idx = np.linspace(0, len(x) - 1, len(x))
    dst_idx = np.linspace(0, len(x) - 1, dst_len)
    return np.interp(dst_idx, src_idx, x).astype(np.float32)

# ────────────────────────────────────────────────
# STOP HANDLING
# ────────────────────────────────────────────────
_should_exit = False

def _handle_term(signum, frame):
    global _should_exit
    _should_exit = True

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT,  _handle_term)

def safe_exit(code=0):
    try:
        all_relays_off()
        servo_stop()
    except Exception:
        pass
    try:
        for io in relay_ios:
            io.deinit()
    except Exception:
        pass
    print("Exercise 7 exited cleanly.")
    sys.exit(code)

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
print("=" * 50)
print("Exercise 7: Voice Activated Relay & Servo")
print("  'open relay'  -> All Relays ON")
print("  'close relay' -> All Relays OFF")
print("  'fast servo'  -> Servo 180 degrees (max)")
print("  'open servo'  -> Servo 90 degrees")
print("  'stop servo'  -> Servo STOP")
print("  'open all'    -> Relays ON + Servo 90")
print("  'close all'   -> Relays OFF + Servo STOP")
print("=" * 50)
print("Listening...")

# Initial state
all_relays_off()
set_servo_angle(0)

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=BLOCK_SIZE,
        device=INPUT_DEVICE,
        dtype="float32",
    ) as stream:

        while not _should_exit:
            raw, overflowed = stream.read(BLOCK_SIZE)

            # float32 -> resample -> int16 for VOSK
            xf  = raw[:, 0].astype(np.float32)
            y   = resample_to_16k(xf, SAMPLE_RATE)
            y16 = np.clip(y * 32767.0, -32768, 32767).astype(np.int16)

            if rec.AcceptWaveform(y16.tobytes()):
                result = json.loads(rec.Result())
                text   = result.get("text", "").strip()
                if text:
                    handle_command(text)
            else:
                partial = json.loads(rec.PartialResult())
                p_text  = partial.get("partial", "").strip()
                if p_text:
                    print(f"  ... {p_text}", end="\r")

    safe_exit(0)

except Exception as e:
    print(f"\nERROR: {repr(e)}")
    print("\nAvailable audio devices:")
    try:
        print(sd.query_devices())
    except Exception as e2:
        print(f"  Could not query: {repr(e2)}")
    safe_exit(1)