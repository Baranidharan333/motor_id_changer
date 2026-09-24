"""
Status indicator on the ESP32-S3's built-in WS2812 RGB LED.

  blinking white -- booted, no web page connected yet
  green          -- web page open (browser heartbeat seen recently)
  yellow         -- scanning for motors
  blue           -- changing CAN id / feedback id
  orange         -- setting zero position

Operation colours are held for HOLD_MS after the operation finishes so even
quick operations are visible.
"""

import time

import machine
import neopixel

BRIGHTNESS = 120  # 0-255 per channel; raise/lower to taste

OFF = (0, 0, 0)
WHITE = (BRIGHTNESS, BRIGHTNESS, BRIGHTNESS)
GREEN = (0, BRIGHTNESS, 0)
YELLOW = (BRIGHTNESS, BRIGHTNESS, 0)
BLUE = (0, 0, BRIGHTNESS)
ORANGE = (BRIGHTNESS, BRIGHTNESS * 80 // 255, 0)  # same mix as (255, 80, 0)

BLINK_MS = 500           # white blink half-period
CLIENT_TIMEOUT_MS = 6000  # page counts as disconnected after this much silence
HOLD_MS = 1000           # keep an operation colour this long after it ends


class _Activity:
    def __init__(self, led, color):
        self._led = led
        self._color = color

    def __enter__(self):
        self._led._busy = self._color
        self._led.update()

    def __exit__(self, *exc):
        led = self._led
        led._busy = None
        led._hold = self._color
        led._hold_until = time.ticks_add(time.ticks_ms(), HOLD_MS)
        led.update()
        return False


class StatusLed:
    def __init__(self, pins, power_pin=None):
        """`pins` is one GPIO number or a tuple of them; every pin gets the
        same colour. `power_pin`, if given, is driven high first -- some
        boards only power the onboard LED when that GPIO is on."""
        if power_pin is not None:
            self._power = machine.Pin(power_pin, machine.Pin.OUT, value=1)
            time.sleep_ms(10)  # let the LED's supply come up before the first write
        if isinstance(pins, int):
            pins = (pins,)
        self._nps = [neopixel.NeoPixel(machine.Pin(p, machine.Pin.OUT), 1) for p in pins]
        self._color = None
        self._busy = None
        self._hold = None
        self._hold_until = 0
        self._last_seen = None
        self.update()

    def _set(self, color):
        if color != self._color:  # only rewrite the LED when the colour changes
            for np in self._nps:
                np[0] = color
                np.write()
            self._color = color

    def web_activity(self):
        """Call on every HTTP request from the page."""
        self._last_seen = time.ticks_ms()

    def client_connected(self):
        return (self._last_seen is not None and
                time.ticks_diff(time.ticks_ms(), self._last_seen) < CLIENT_TIMEOUT_MS)

    def activity(self, color):
        """`with led.activity(BLUE): ...` shows `color` for the duration."""
        return _Activity(self, color)

    def update(self):
        now = time.ticks_ms()
        if self._busy is not None:
            self._set(self._busy)
        elif self._hold is not None and time.ticks_diff(self._hold_until, now) > 0:
            self._set(self._hold)
        elif self.client_connected():
            self._hold = None
            self._set(GREEN)
        else:
            self._hold = None
            self._set(WHITE if (now // BLINK_MS) % 2 == 0 else OFF)

    def off(self):
        self._set(OFF)
