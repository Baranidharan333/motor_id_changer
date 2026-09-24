# from machine import Pin
# import neopixel
# import time
# 
# # On boards like Adafruit/LILYGO, GPIO 11, 3, or 4 controls power to onboard peripherals
# # Example for Adafruit Feather (NEOPIXEL_POWER pin):
# power_pin = Pin(11, Pin.OUT)
# power_pin.value(1) # Turn on power to NeoPixel
# 
# RGB_PIN = 48 # Change to your board's pin
# np = neopixel.NeoPixel(Pin(RGB_PIN), 1)
# 
# np[0] = (255, 0, 0)
# np.write()


from machine import Pin
import neopixel
import time

# NeoPixel power
power_pin = Pin(11, Pin.OUT)
power_pin.value(1)

# NeoPixel
RGB_PIN = 48
np = neopixel.NeoPixel(Pin(RGB_PIN), 1)


def set_color(r, g, b):
    np[0] = (r, g, b)
    np.write()


# List of colors
colors = [
    ("RED",         (255, 0, 0)),
    ("GREEN",       (0, 255, 0)),
    ("BLUE",        (0, 0, 255)),
    ("YELLOW",      (255, 255, 0)),
    ("CYAN",        (0, 255, 255)),
    ("MAGENTA",     (255, 0, 255)),
    ("WHITE",       (255, 255, 255)),
    ("ORANGE",      (255, 80, 0)),
    ("PURPLE",      (128, 0, 255)),
    ("PINK",        (255, 20, 100)),
    ("LIME",        (100, 255, 0)),
    ("SKY BLUE",    (0, 150, 255)),
    ("WARM WHITE",  (255, 150, 80)),
]

while True:

    for name, color in colors:
        print(name)

        set_color(*color)
        time.sleep(1)

    # OFF
    set_color(0, 0, 0)
    time.sleep(1)