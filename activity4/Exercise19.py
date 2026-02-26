import time
import signal
import sys

import board
import digitalio

# Optional LCD (TCA9548A + RPLCD)
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    LCD_AVAILABLE = True
except Exception:
    LCD_AVAILABLE = False

# ─────────────────────────────
# PINS (TrainerKit)
# ─────────────────────────────
PIR_PIN     = board.D22
RED_LED_PIN = board.D5
BUZZER_PIN  = board.D16

BUZZER_ACTIVE_LOW = False

# ─────────────────────────────
# LCD + MUX SETTINGS
# ─────────────────────────────
USE_MUX = True
MUX_ADDR = 0x70
LCD_MUX_CH = 0

LCD_I2C_BUS = 1
LCD_ADDRS = [0x27, 0x3F]
LCD_COLS = 16
LCD_ROWS = 2

_should_exit = False


def _safe_deinit(io):
    try:
        if io is not None:
            io.deinit()
    except Exception:
        pass


def buzzer_gpio_value(on: bool) -> bool:
    return (not bool(on)) if BUZZER_ACTIVE_LOW else bool(on)


def mux_select_for_lcd():
    if not LCD_AVAILABLE:
        return False
    if not USE_MUX:
        return True
    try:
        with SMBus(LCD_I2C_BUS) as bus:
            bus.write_byte(MUX_ADDR, 1 << LCD_MUX_CH)
        return True
    except Exception:
        return False


_lcd = None


def lcd_get():
    global _lcd
    if not LCD_AVAILABLE:
        return None
    if _lcd is not None:
        return _lcd
    if not mux_select_for_lcd():
        return None

    for addr in LCD_ADDRS:
        try:
            _lcd = CharLCD(
                "PCF8574",
                address=addr,
                port=LCD_I2C_BUS,
                cols=LCD_COLS,
                rows=LCD_ROWS,
                charmap="A00",
            )
            _lcd.clear()
            return _lcd
        except Exception:
            _lcd = None
    return None


def lcd_write(line1="", line2=""):
    lcd = lcd_get()
    if lcd is None:
        return False
    if not mux_select_for_lcd():
        return False
    try:
        lcd.clear()
        lcd.write_string((line1 or "")[:LCD_COLS])
        lcd.cursor_pos = (1, 0)
        lcd.write_string((line2 or "")[:LCD_COLS])
        return True
    except Exception:
        return False


def lcd_release():
    global _lcd
    try:
        if _lcd is not None:
            if mux_select_for_lcd():
                _lcd.clear()
            _lcd = None
    except Exception:
        _lcd = None


def try_claim_output(pin):
    """
    Try to claim a DigitalInOut output pin.
    Returns (io, error_message_or_None)
    """
    try:
        io = digitalio.DigitalInOut(pin)
        io.direction = digitalio.Direction.OUTPUT
        return io, None
    except Exception as e:
        return None, str(e)


def main():
    global _should_exit

    # PIR input
    pir = digitalio.DigitalInOut(PIR_PIN)
    pir.direction = digitalio.Direction.INPUT
    try:
        pir.pull = digitalio.Pull.DOWN
    except Exception:
        pass

    # Red LED
    red = digitalio.DigitalInOut(RED_LED_PIN)
    red.direction = digitalio.Direction.OUTPUT
    red.value = False

    # Buzzer (may be busy)
    buz, buz_err = try_claim_output(BUZZER_PIN)
    buzzer_ok = buz is not None
    if buzzer_ok:
        buz.value = buzzer_gpio_value(False)
    else:
        print(f"⚠️ BUZZER GPIO busy/unavailable ({BUZZER_PIN}). Running without buzzer.")
        print("   Reason:", buz_err)

    # LCD initial
    lcd_write("SECURITY MODE", "SECURE")

    def buzzer_set(on: bool):
        if not buzzer_ok:
            return
        buz.value = buzzer_gpio_value(on)

    def all_safe_off():
        try:
            red.value = False
        except Exception:
            pass
        try:
            buzzer_set(False)
        except Exception:
            pass
        lcd_write("SECURITY MODE", "SECURE")

    def cleanup(*_):
        global _should_exit
        _should_exit = True
        all_safe_off()
        _safe_deinit(pir)
        _safe_deinit(red)
        _safe_deinit(buz)
        lcd_release()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("Exercise 19: Intrusion Alert System running...")
    print("PIR motion -> RED ON + BUZZER (if available) + LCD INTRUDER ALERT")
    print("No motion  -> all OFF / SECURE")
    print("Ctrl+C to stop.\n")

    alarm_on = False
    last_toggle = time.time()
    beep_on = False

    # beep pattern
    BEEP_ON_SEC = 0.15
    BEEP_OFF_SEC = 0.12

    while not _should_exit:
        motion = bool(pir.value)

        if motion and not alarm_on:
            alarm_on = True
            red.value = True
            lcd_write("INTRUDER ALERT", "MOTION DETECTED")
            # start beep cycle
            beep_on = False
            last_toggle = time.time()

        if (not motion) and alarm_on:
            alarm_on = False
            red.value = False
            buzzer_set(False)
            lcd_write("SECURITY MODE", "SECURE")

        # beep while alarm_on
        if alarm_on and buzzer_ok:
            now = time.time()
            if beep_on:
                if (now - last_toggle) >= BEEP_ON_SEC:
                    buzzer_set(False)
                    beep_on = False
                    last_toggle = now
            else:
                if (now - last_toggle) >= BEEP_OFF_SEC:
                    buzzer_set(True)
                    beep_on = True
                    last_toggle = now

        time.sleep(0.02)


if __name__ == "__main__":
    main()