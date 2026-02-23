# Exercise18.py (board / digitalio) - Unsafe Alert using RELAY + LED + LCD countdown
import time

# ===== GPIO (board/digitalio) =====
try:
    import board
    import digitalio
    GPIO_OK = True
except Exception as e:
    board = None
    digitalio = None
    GPIO_OK = False
    _import_err = e

# ===== OPTIONAL LCD (RPLCD) =====
LCD_OK = False
_lcd = None
try:
    from RPLCD.i2c import CharLCD  # pip install RPLCD
    LCD_OK = True
except Exception:
    CharLCD = None
    LCD_OK = False

# ===== EDIT PINS =====
RELAY_PIN = board.D27       # change to your relay (or use relay1)
ALERT_LED_PIN = board.D13   # change to your alert LED (red/orange)

RELAY_ACTIVE_HIGH = True    # True=HIGH turns relay ON; False=LOW turns relay ON
LED_ACTIVE_HIGH = True

# LCD settings (only if you have RPLCD)
I2C_PORT = 1
LCD_ADDR = 0x27            # common: 0x27 or 0x3F
LCD_COLS = 16
LCD_ROWS = 2

# Countdown config
COUNTDOWN_SEC = 10.0

# Speed curve: start slow -> end fast
OFF_START = 0.35   # seconds between clicks at start
OFF_END   = 0.06   # seconds between clicks near the end
ON_PULSE  = 0.03   # relay ON time per click (short "tick")
# =====================

_relay = None
_led = None


def make_out(pin, initial=False):
    io = digitalio.DigitalInOut(pin)
    io.direction = digitalio.Direction.OUTPUT
    io.value = initial
    return io


def set_out(dev, on: bool, active_high: bool = True):
    dev.value = (on if active_high else (not on))


def lcd_init():
    """Init LCD if available. Safe no-op if not installed."""
    global _lcd
    if not LCD_OK or _lcd is not None:
        return _lcd
    try:
        _lcd = CharLCD("PCF8574", LCD_ADDR, port=I2C_PORT, cols=LCD_COLS, rows=LCD_ROWS)
        _lcd.clear()
    except Exception:
        _lcd = None
    return _lcd


def lcd_write(line1: str, line2: str = ""):
    """Write to LCD if available; otherwise print."""
    line1 = (line1 or "")[:16].ljust(16)
    line2 = (line2 or "")[:16].ljust(16)

    lcd = lcd_init()
    if lcd:
        try:
            lcd.clear()
            lcd.cursor_pos = (0, 0)
            lcd.write_string(line1)
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2)
            return
        except Exception:
            pass

    # fallback
    print(f"[LCD]\n{line1}\n{line2}")


def relay_click(off_sec: float):
    """
    One 'click': relay pulse + LED flash.
    off_sec controls how long to wait after the pulse.
    """
    # pulse ON
    set_out(_relay, True, RELAY_ACTIVE_HIGH)
    set_out(_led, True, LED_ACTIVE_HIGH)
    time.sleep(max(0.01, float(ON_PULSE)))

    # back OFF
    set_out(_relay, False, RELAY_ACTIVE_HIGH)
    set_out(_led, False, LED_ACTIVE_HIGH)
    time.sleep(max(0.01, float(off_sec)))


def run(unsafe: bool = True):
    """
    Exercise 18: Sound Alert (but using RELAY clicking + LED + LCD)
    Input: unsafe condition (bool)
    Output: relay 'click' pattern gets faster for 10 seconds + LED flash + LCD countdown
    """
    global _relay, _led

    if not GPIO_OK:
        print("[EX18] board/digitalio not available. Simulating.")
        print(f"[EX18] import error: {_import_err}")
        return {"ok": True, "simulated": True, "unsafe": unsafe}

    # init outputs (start OFF)
    if _relay is None:
        _relay = make_out(RELAY_PIN, (not RELAY_ACTIVE_HIGH))
    if _led is None:
        _led = make_out(ALERT_LED_PIN, (not LED_ACTIVE_HIGH))

    if not unsafe:
        lcd_write("SAFE", "No alert")
        set_out(_relay, False, RELAY_ACTIVE_HIGH)
        set_out(_led, False, LED_ACTIVE_HIGH)
        return {"ok": True, "unsafe": False, "message": "Safe: relay/LED OFF"}

    # UNSAFE countdown
    t_end = time.time() + float(COUNTDOWN_SEC)
    lcd_write("UNSAFE!", "T-minus 10s")

    while True:
        now = time.time()
        remain = t_end - now
        if remain <= 0:
            break

        # progress 0..1 (0=start, 1=end)
        prog = 1.0 - (remain / float(COUNTDOWN_SEC))
        # interpolate off time slow -> fast
        off_sec = OFF_START + (OFF_END - OFF_START) * prog

        # update LCD once per second (stable display)
        remain_int = int(remain + 0.999)  # ceil-ish
        lcd_write("UNSAFE ALERT!", f"T-minus: {remain_int:02d}s")

        # do a few clicks within this second using current off_sec
        # (makes it feel like "faster and faster")
        # keep it responsive without sleeping a full second
        relay_click(off_sec)

    # end signal: 3 fast clicks
    lcd_write("STATUS", "ALERT DONE")
    for _ in range(3):
        relay_click(0.05)

    # keep outputs OFF after
    set_out(_relay, False, RELAY_ACTIVE_HIGH)
    set_out(_led, False, LED_ACTIVE_HIGH)

    return {"ok": True, "unsafe": True, "message": "Unsafe countdown relay pattern completed"}


def stop():
    """Force OFF and cleanup."""
    global _relay, _led, _lcd

    try:
        if _relay:
            set_out(_relay, False, RELAY_ACTIVE_HIGH)
    except Exception:
        pass
    try:
        if _led:
            set_out(_led, False, LED_ACTIVE_HIGH)
    except Exception:
        pass

    try:
        if _relay:
            _relay.deinit()
            _relay = None
    except Exception:
        pass
    try:
        if _led:
            _led.deinit()
            _led = None
    except Exception:
        pass
    try:
        if _lcd:
            _lcd.clear()
            _lcd.close(clear=True)
            _lcd = None
    except Exception:
        pass

    return {"ok": True, "stopped": True}


if __name__ == "__main__":
    # demo
    run(True)
    time.sleep(1)
    stop()