import time
import signal
import sys

import board
import digitalio
import pwmio

PIR_PIN = board.D22
SERVO_PIN = board.D12

FREQUENCY = 50
MIN_PULSE_US = 500
MAX_PULSE_US = 2500

ANGLE_IDLE = 0
ANGLE_ACTIVE = 90


def angle_to_duty_u16(angle: int) -> int:
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    duty = int((pulse_us / 20000.0) * 65535.0)
    return max(0, min(65535, duty))


def main():
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def servo_on(angle: int):
        # send pulses long enough to reach the target
        servo.duty_cycle = angle_to_duty_u16(angle)
        time.sleep(0.35)

    def servo_off():
        # stop sending pulses (servo relaxes / “turns off”)
        servo.duty_cycle = 0

    def cleanup(*_):
        try:
            # Go safe idle then OFF
            try:
                servo_on(ANGLE_IDLE)
            except Exception:
                pass
            servo_off()
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
    print("No motion -> 0° then OFF | Motion -> 90° holding | Ctrl+C to stop")

    # Start at idle and OFF
    servo_on(ANGLE_IDLE)
    servo_off()

    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> Servo 90° (ON)")
                servo_on(ANGLE_ACTIVE)   # keep ON while motion continues (hold 90°)
                # NOTE: we do NOT turn OFF here because we want it to HOLD at 90°
            else:
                print("No motion -> Servo 0° then OFF")
                servo_on(ANGLE_IDLE)
                servo_off()

            last_state = motion

        # While motion is true, keep holding 90° by keeping PWM running.
        # No extra writes needed; duty stays set.
        time.sleep(0.05)


if __name__ == "__main__":
    main()