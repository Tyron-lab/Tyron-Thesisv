import board
import digitalio
import time

# ---- Buzzer pin ----
BUZZER_PIN = board.D21

# If your buzzer is wired as active-low (beeps when pin is LOW), set True.
# If it beeps when pin is HIGH, set False.
BUZZER_ACTIVE_LOW = True

# ✅ Set True to keep buzzer completely silent always
MUTE = False

# Setup buzzer GPIO
buzzer = digitalio.DigitalInOut(BUZZER_PIN)
buzzer.direction = digitalio.Direction.OUTPUT

def buzzer_off_hard():
    """Force buzzer OFF immediately, no matter what."""
    # For active-low: OFF = HIGH (True)
    # For active-high: OFF = LOW (False)
    buzzer.value = BUZZER_ACTIVE_LOW
    time.sleep(0.02)  # Let module settle

def buzzer_set(on: bool):
    """Turn buzzer ON or OFF with correct polarity."""
    if MUTE:
        buzzer.value = BUZZER_ACTIVE_LOW  # Force silent
        return

    if BUZZER_ACTIVE_LOW:
        buzzer.value = not on  # ON=LOW, OFF=HIGH
    else:
        buzzer.value = bool(on)  # ON=HIGH, OFF=LOW

def buzzer_silence():
    """Silence the buzzer completely (call this on startup or shutdown)."""
    buzzer_off_hard()
    buzzer_set(False)

# ✅ Silence buzzer immediately on import/startup
buzzer_silence()