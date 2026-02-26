import time
import signal
import sys

import board
import digitalio
import pwmio

# ----------------------------
# PINS (TrainerKit)
# ----------------------------
TRIG_PIN = board.D23
ECHO_PIN = board.D24

SERVO_PIN = board.D12
ORANGE_LED_PIN = board.D6

# Your working buzzer wiring (from your ultrasonic exercise)
BUZZER_PIN = board.D21
BUZZER_ACTIVE_LOW = True

# ----------------------------
# SETTINGS
# ----------------------------
DIST_THRESHOLD_CM = 20.0   # object near if <= this distance
READ_INTERVAL_SEC = 0.12

# Servo PWM
FREQUENCY = 50
MIN_PULSE_US = 500
MAX_PULSE_US = 2500
ANGLE_FAR = 0
ANGLE_NEAR = 90

# Buzzer beep pattern (when object is near)
BEEP_ON_SEC = 0.10
BEEP_OFF_SEC = 0.10

_should_exit = False


def buzzer_gpio_value(on: bool) -> bool:
    return (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)


def angle_to_duty_u16(angle: int) -> int:
    angle = max(0, min(180, int(angle)))
    pulse_us = MIN_PULSE_US + (MAX_PULSE_US - MIN_PULSE_US) * (angle / 180.0)
    return max(0, min(65535, int((pulse_us / 20000.0) * 65535.0)))  # 20ms period @ 50Hz


def measure_distance_cm(trig: digitalio.DigitalInOut, echo: digitalio.DigitalInOut) -> float | None:
    """
    HC-SR04 timing with DigitalInOut (Blinka).
    Returns distance in cm or None on timeout.
    """
    # Trigger pulse
    trig.value = False
    time.sleep(0.0002)
    trig.value = True
    time.sleep(0.00001)
    trig.value = False

    timeout = time.time() + 0.08

    # Wait for echo to go HIGH
    start = time.time()
    while not echo.value:
        start = time.time()
        if start > timeout:
            return None

    # Wait for echo to go LOW
    end = time.time()
    while echo.value:
        end = time.time()
        if end > timeout:
            return None

    duration = end - start
    if duration <= 0:
        return None

    # Speed of sound: distance = duration * 17150 (cm)
    return round(duration * 17150.0, 1)


def main():
    global _should_exit

    # Ultrasonic
    trig = digitalio.DigitalInOut(TRIG_PIN)
    echo = digitalio.DigitalInOut(ECHO_PIN)
    trig.direction = digitalio.Direction.OUTPUT
    echo.direction = digitalio.Direction.INPUT
    trig.value = False

    # Orange LED
    led = digitalio.DigitalInOut(ORANGE_LED_PIN)
    led.direction = digitalio.Direction.OUTPUT
    led.value = False

    # Buzzer
    buz = digitalio.DigitalInOut(BUZZER_PIN)
    buz.direction = digitalio.Direction.OUTPUT
    buz.value = buzzer_gpio_value(False)  # OFF

    # Servo
    servo = pwmio.PWMOut(SERVO_PIN, duty_cycle=0, frequency=FREQUENCY)

    def set_servo(angle: int):
        servo.duty_cycle = angle_to_duty_u16(angle)

    def servo_off():
        # stop pulses (optional); keeps it “relaxed”
        servo.duty_cycle = 0

    def all_off():
        try:
            led.value = False
        except Exception:
            pass
        try:
            buz.value = buzzer_gpio_value(False)
        except Exception:
            pass
        try:
            set_servo(ANGLE_FAR)
            time.sleep(0.12)
            servo_off()
        except Exception:
            pass

    def cleanup(*_):
        global _should_exit
        _should_exit = True
        all_off()
        for io in (trig, echo, led, buz):
            try:
                io.deinit()
            except Exception:
                pass
        try:
            servo.deinit()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("Exercise 20: Smart Object Detection Response running...")
    print(f"Near threshold: <= {DIST_THRESHOLD_CM} cm")
    print("Near -> Servo 90°, Orange ON, Buzzer beep")
    print("Far  -> Servo 0° (off), Orange OFF, Buzzer OFF")
    print("Ctrl+C to stop.\n")

    # Start safe
    all_off()

    near_state = False
    last_beep_toggle = time.time()
    beep_on = False

    while not _should_exit:
        dist = measure_distance_cm(trig, echo)
        is_near = (dist is not None and dist <= DIST_THRESHOLD_CM)

        if is_near != near_state:
            near_state = is_near

            if near_state:
                print(f"Object NEAR ({dist} cm) -> ACTIVE")
                led.value = True
                set_servo(ANGLE_NEAR)   # hold position by keeping PWM on
                # start beep cycle
                beep_on = False
                last_beep_toggle = time.time()
            else:
                print(f"Object FAR ({dist} cm) -> IDLE")
                led.value = False
                buz.value = buzzer_gpio_value(False)
                set_servo(ANGLE_FAR)
                time.sleep(0.12)
                servo_off()

        # Beep while near
        if near_state:
            now = time.time()
            if beep_on:
                if (now - last_beep_toggle) >= BEEP_ON_SEC:
                    buz.value = buzzer_gpio_value(False)
                    beep_on = False
                    last_beep_toggle = now
            else:
                if (now - last_beep_toggle) >= BEEP_OFF_SEC:
                    buz.value = buzzer_gpio_value(True)
                    beep_on = True
                    last_beep_toggle = now

        time.sleep(READ_INTERVAL_SEC)


if __name__ == "__main__":
    main()