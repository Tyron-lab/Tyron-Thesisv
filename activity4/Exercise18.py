import time
import signal
import sys
import queue
import threading

import numpy as np
import sounddevice as sd

import board
import digitalio

# ----------------------------
# RELAY PINS (same as your server)
# CH1=D27, CH2=D10, CH3=D26, CH4=D25  (active-low)
# ----------------------------
RELAY_PINS = [board.D27, board.D10, board.D26, board.D25]
RELAY_ACTIVE_LOW = True

# ----------------------------
# CLAP DETECTION
# ----------------------------
CLAP_PEAK_THRESHOLD = 0.35   # raise if too sensitive, lower if not detecting
MIN_CLAP_GAP_SEC = 0.35      # debounce for one clap
TOGGLE_COOLDOWN_SEC = 0.60   # prevents double toggles

# ----------------------------
# PATTERN SETTINGS
# ----------------------------
STEP_ON_SEC = 0.25           # how long each relay stays ON
STEP_OFF_SEC = 0.08          # gap between relays
PATTERN_LOOP_DELAY = 0.05

# Audio chunking
BLOCK_MS = 30

_should_exit = False


def relay_write(io: digitalio.DigitalInOut, on: bool):
    # Active-low relay: ON=False, OFF=True
    if RELAY_ACTIVE_LOW:
        io.value = (not on)
    else:
        io.value = bool(on)


def all_relays(relays, on: bool):
    for r in relays:
        relay_write(r, on)


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

    # --- Relay GPIO init ---
    relays = []
    for pin in RELAY_PINS:
        io = digitalio.DigitalInOut(pin)
        io.direction = digitalio.Direction.OUTPUT
        relays.append(io)

    # Start safe OFF
    all_relays(relays, False)

    # --- Pattern control ---
    pattern_running = False
    pattern_flag = {"run": False}
    pattern_lock = threading.Lock()

    def pattern_worker():
        idx = 0
        while not _should_exit:
            with pattern_lock:
                running = pattern_flag["run"]
            if not running:
                time.sleep(PATTERN_LOOP_DELAY)
                continue

            # turn all OFF first (clean step)
            all_relays(relays, False)

            # turn one ON
            relay_write(relays[idx], True)
            time.sleep(STEP_ON_SEC)

            # turn it OFF
            relay_write(relays[idx], False)
            time.sleep(STEP_OFF_SEC)

            idx = (idx + 1) % len(relays)

    t = threading.Thread(target=pattern_worker, daemon=True)
    t.start()

    def set_pattern(on: bool):
        nonlocal pattern_running
        with pattern_lock:
            pattern_flag["run"] = bool(on)
        pattern_running = bool(on)
        if not on:
            all_relays(relays, False)

    # --- Cleanup ---
    def cleanup(*_):
        global _should_exit
        _should_exit = True
        try:
            set_pattern(False)
        except Exception:
            pass
        try:
            all_relays(relays, False)
        except Exception:
            pass
        for r in relays:
            try:
                r.deinit()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("Exercise 18: Clap / Loud Sound Relay Pattern (ALL channels)")
    print("Clap once  -> START pattern (CH1->CH2->CH3->CH4->repeat)")
    print("Clap again -> STOP pattern + ALL OFF")
    print("Ctrl+C to stop.\n")
    print("Relay pins:", ["D27(CH1)", "D10(CH2)", "D26(CH3)", "D25(CH4)"])
    print("Threshold:", CLAP_PEAK_THRESHOLD)
    print("Pattern speed:", f"ON {STEP_ON_SEC}s, OFF {STEP_OFF_SEC}s\n")

    # --- Audio setup ---
    audio_q = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            pass
        audio_q.put(indata[:, 0].copy())

    dev = sd.default.device[0]
    candidate_rates = [48000, 44100, 32000, 24000, 16000, 8000]
    stream = None
    chosen_rate = None

    for r in candidate_rates:
        blocksize = int(r * (BLOCK_MS / 1000.0))
        stream = try_open_input_stream(dev, r, blocksize, audio_callback)
        if stream is not None:
            chosen_rate = r
            break

    if stream is None:
        print("❌ Could not open microphone. Run:")
        print('python -c "import sounddevice as sd; print(sd.query_devices())"')
        cleanup()

    print(f"✅ Mic opened at {chosen_rate} Hz\n")

    last_clap_time = 0.0
    last_toggle_time = 0.0

    try:
        while not _should_exit:
            try:
                chunk = audio_q.get(timeout=0.25)
            except queue.Empty:
                continue

            peak = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
            now = time.time()

            if peak >= CLAP_PEAK_THRESHOLD:
                # debounce for single clap
                if (now - last_clap_time) < MIN_CLAP_GAP_SEC:
                    continue
                last_clap_time = now

                # cooldown to avoid double toggles
                if (now - last_toggle_time) < TOGGLE_COOLDOWN_SEC:
                    continue
                last_toggle_time = now

                # toggle pattern
                pattern_running = not pattern_running
                set_pattern(pattern_running)

                print(f"👏 CLAP! peak={peak:.2f} -> Pattern {'START' if pattern_running else 'STOP (ALL OFF)'}")

    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        cleanup()


if __name__ == "__main__":
    main()