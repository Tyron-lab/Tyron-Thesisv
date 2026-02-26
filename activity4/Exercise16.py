import time
import signal
import sys

import board
import digitalio
import pwmio

# ----------------------------
# Pins (as you requested)
# ----------------------------
PIR_PIN = board.D22
SERVO_PIN = board.D12

# ----------------------------
# Servo PWM settings
# ----------------------------
FREQUENCY = 50          # 50Hz typical servo
MIN_PULSE_US = 500      # 0° pulse width (tweak if needed)
MAX_PULSE_US = 2500     # 180° pulse width (tweak if needed)

# Angles for this exercise
ANGLE_IDLE = 0
ANGLE_ACTIVE = 90


def angle_to_duty_u16(angle: int) -> int:
    """Convert servo angle (0-180) to 16-bit PWM duty cycle for 50Hz."""
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    # 50Hz period = 20,000 us
    duty = int((pulse_us / 20000.0) * 65535.0)
    return max(0, min(65535, duty))


def main():
    # PIR input
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT

    # Some PIR modules work fine without pull.
    # If your PIR output is "floating" without motion, you can try enabling pull-down.
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    # Servo PWM output
    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def set_servo(angle: int):
        servo.duty_cycle = angle_to_duty_u16(angle)

    def cleanup(*_):
        try:
            # Return to 0°
            try:
                set_servo(ANGLE_IDLE)
                time.sleep(0.25)
            except Exception:
                pass

            # Stop PWM (optional: keep holding position by NOT zeroing)
            try:
                servo.duty_cycle = 0
            except Exception:
                pass
        finally:
            try:
                pir.deinit()
            except Exception:
                pass
            try:
                servo.deinit()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("Exercise 16: PIR Motion-Activated Servo running...")
    print("PIR: D22 | SERVO: D12 | Ctrl+C to stop")

    # Start idle
    set_servo(ANGLE_IDLE)
    last_state = None

    while True:
        motion = bool(pir.value)

        # only move when state changes
        if motion != last_state:
            if motion:
                print("Motion detected -> Servo 90°")
                set_servo(ANGLE_ACTIVE)
            else:
                print("No motion -> Servo 0°")
                set_servo(ANGLE_IDLE)

            last_state = motion

        time.sleep(0.05)


if __name__ == "__main__":
    main()