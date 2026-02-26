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
    return max(0, min(65535, int((pulse_us / 20000.0) * 65535.0)))


def main():
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def set_servo(angle: int):
        servo.duty_cycle = angle_to_duty_u16(angle)

    def servo_off():
        servo.duty_cycle = 0

    def cleanup(*_):
        try:
            # immediate 0°
            try:
                set_servo(ANGLE_IDLE)
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
    print("Motion -> 90° hold | No motion -> 0° immediately then OFF | Ctrl+C to stop")

    # Start at 0° and OFF
    set_servo(ANGLE_IDLE)
    servo_off()

    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> Servo 90°")
                set_servo(ANGLE_ACTIVE)   # keep PWM on to hold 90°
            else:
                print("No motion -> Servo 0° (immediate) then OFF")
                set_servo(ANGLE_IDLE)
                servo_off()

            last_state = motion

        time.sleep(0.02)


if __name__ == "__main__":
    main()