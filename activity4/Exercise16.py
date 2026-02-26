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

# ✅ LOWER = faster response (too low may not reach the angle)
SPEED_T = 0.15   # try 0.12, 0.15, 0.18, 0.20


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
        servo.duty_cycle = angle_to_duty_u16(angle)
        time.sleep(SPEED_T)   # ✅ faster move/response

    def servo_off():
        servo.duty_cycle = 0

    def cleanup(*_):
        try:
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
    print("SPEED_T =", SPEED_T)

    servo_on(ANGLE_IDLE)
    servo_off()

    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> Servo 90° (ON)")
                servo_on(ANGLE_ACTIVE)
                # keep PWM on to hold at 90°
            else:
                print("No motion -> Servo 0° then OFF")
                servo_on(ANGLE_IDLE)
                servo_off()

            last_state = motion

        time.sleep(0.02)  # ✅ tighter loop responsiveness


if __name__ == "__main__":
    main()