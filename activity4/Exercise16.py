# Exercise 16: Motion-Activated Servo Movement (PIR -> Servo)
# Pins (CircuitPython style -> BCM):
#   PIR   = board.D22 -> GPIO22 (physical pin 15)
#   SERVO = board.D12 -> GPIO12 (physical pin 32) PWM-capable
#
# Behavior:
#   - No motion  -> servo at 0°
#   - Motion     -> servo at 90° while motion detected
#   - Motion end -> servo returns to 0°
#
# Notes:
# - PIR OUT must be safe 3.3V logic to Pi GPIO.
# - Servo should use external 5V power; share GND with Pi.

import time
import signal
import sys
import RPi.GPIO as GPIO

# =========================
# PIN CONFIG (UPDATED)
# =========================
PIR_PIN = 22        # board.D22
SERVO_PIN = 12      # board.D12 (PWM)

# =========================
# SERVO CONFIG
# =========================
PWM_FREQ = 50       # servo frequency

# Typical duty cycles (tweak if needed)
DUTY_0 = 2.5
DUTY_90 = 7.5


def set_servo(pwm, duty):
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.35)      # let servo reach position
    pwm.ChangeDutyCycle(0)  # reduce jitter (optional)


def cleanup(pwm=None):
    try:
        if pwm is not None:
            try:
                pwm.ChangeDutyCycle(DUTY_0)
                time.sleep(0.35)
                pwm.ChangeDutyCycle(0)
            except Exception:
                pass
            pwm.stop()
    finally:
        GPIO.cleanup()


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # PIR input
    GPIO.setup(PIR_PIN, GPIO.IN)

    # Servo PWM output
    GPIO.setup(SERVO_PIN, GPIO.OUT)
    pwm = GPIO.PWM(SERVO_PIN, PWM_FREQ)
    pwm.start(0)

    # start at 0°
    set_servo(pwm, DUTY_0)

    # clean exit
    def handle_exit(sig, frame):
        cleanup(pwm)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    print("Exercise 16: PIR Motion-Activated Servo running...")
    print(f"PIR: GPIO{PIR_PIN} (board.D22) | Servo: GPIO{SERVO_PIN} (board.D12)")
    print("Ctrl+C to stop.\n")

    last_motion = None

    while True:
        motion = GPIO.input(PIR_PIN) == GPIO.HIGH

        # only react on changes
        if motion != last_motion:
            if motion:
                print("Motion detected -> Servo to 90°")
                set_servo(pwm, DUTY_90)
            else:
                print("No motion -> Servo to 0°")
                set_servo(pwm, DUTY_0)

            last_motion = motion

        time.sleep(0.1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        GPIO.cleanup()