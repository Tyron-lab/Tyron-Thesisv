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

# Motion move speed (time we keep pulses on after changing angle)
MOVE_T = 0.15

# ✅ Make return-to-0 “fast”
FAST_RETURN_T = 0.06   # try 0.04–0.10


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

    def set_angle(angle: int, hold_s: float):
        servo.duty_cycle = angle_to_duty_u16(angle)
        time.sleep(max(0.0, hold_s))

    def servo_off():
        servo.duty_cycle = 0

    def cleanup(*_):
        try:
            try:
                set_angle(ANGLE_IDLE, FAST_RETURN_T)
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

    print("Exercise 16 running...")
    print("Motion -> 90° hold | No motion -> 0° fast then OFF")
    print("MOVE_T =", MOVE_T, "FAST_RETURN_T =", FAST_RETURN_T)

    # start at 0 then off
    set_angle(ANGLE_IDLE, FAST_RETURN_T)
    servo_off()

    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> 90°")
                set_angle(ANGLE_ACTIVE, MOVE_T)
                # keep PWM on to hold at 90°
            else:
                print("Motion ended -> 0° FAST then OFF")
                set_angle(ANGLE_IDLE, FAST_RETURN_T)
                servo_off()

            last_state = motion

        time.sleep(0.02)


if __name__ == "__main__":
    main()