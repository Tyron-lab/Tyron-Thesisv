import time
import signal
import sys

import board
import digitalio
import pwmio

PIR_PIN = board.D22
SERVO_PIN = board.D12

FREQUENCY = 50

# Continuous-rotation servo pulse widths (µs)
STOP_US = 1500
FAST_US = 2000   # change to 1000 if direction is reversed

def us_to_duty_u16(pulse_us: int) -> int:
    pulse_us = max(500, min(2500, int(pulse_us)))
    return int((pulse_us / 20000.0) * 65535.0)

def main():
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def servo_write_us(pulse_us: int):
        servo.duty_cycle = us_to_duty_u16(pulse_us)

    def servo_spin_fast():
        servo_write_us(FAST_US)

    def servo_total_stop():
        # 1) command stop
        servo_write_us(STOP_US)
        time.sleep(0.08)      # tiny settle (keeps stop reliable)
        # 2) turn pulses OFF (total stop / no holding)
        servo.duty_cycle = 0

    def cleanup(*_):
        try:
            try:
                servo_total_stop()
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

    print("Exercise 16: PIR -> Continuous Rotation Servo")
    print("Motion: SPIN FAST | No motion: TOTAL STOP (OFF) | Ctrl+C to stop")

    servo_total_stop()
    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> SPIN FAST")
                servo_spin_fast()
            else:
                print("No motion -> TOTAL STOP")
                servo_total_stop()
            last_state = motion

        time.sleep(0.02)

if __name__ == "__main__":
    main()