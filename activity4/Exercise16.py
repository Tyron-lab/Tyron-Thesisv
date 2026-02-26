import time
import signal
import sys

import board
import digitalio
import pwmio

# Pins
PIR_PIN = board.D22
SERVO_PIN = board.D12

# Servo PWM
FREQUENCY = 50

# Continuous-rotation servo pulse widths (microseconds)
# Typical:
#   STOP      ~ 1500us
#   FAST FWD  ~ 2000us
#   FAST REV  ~ 1000us
STOP_US = 1500
FAST_FWD_US = 2000   # change to 1000 if your direction is reversed

def us_to_duty_u16(pulse_us: int) -> int:
    pulse_us = max(500, min(2500, int(pulse_us)))
    return int((pulse_us / 20000.0) * 65535.0)  # 20ms period @ 50Hz

def main():
    # PIR input
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    # Servo output
    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def servo_write_us(pulse_us: int):
        servo.duty_cycle = us_to_duty_u16(pulse_us)

    def servo_stop():
        servo_write_us(STOP_US)

    def cleanup(*_):
        try:
            try:
                servo_stop()
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
    print("Motion: spin FAST | No motion: STOP | Ctrl+C to stop")

    # Start stopped
    servo_stop()

    last_state = None

    while True:
        motion = bool(pir.value)

        if motion != last_state:
            if motion:
                print("Motion detected -> SPIN FAST")
                servo_write_us(FAST_FWD_US)
            else:
                print("No motion -> STOP")
                servo_stop()

            last_state = motion

        time.sleep(0.02)

if __name__ == "__main__":
    main()