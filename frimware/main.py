"""
MicroPython entry point for the ESP32-S3 DM-J4340-2EC motor configurator.

Runs entirely on-device: brings up the ESP32-S3's built-in TWAI controller
(via twai.py) as the CAN bus, starts a WiFi access point, and serves the
motor_web UI directly from the board -- no PC, python-can, or SocketCAN
needed.

Setup:
  1. Wire a 3.3V CAN transceiver (e.g. SN65HVD230 / TJA1051) between the
     bus and TWAI_TX_PIN/TWAI_RX_PIN below:
       ESP32-S3 GPIO4 (TWAI_TX_PIN) -> transceiver TXD / CTX
       ESP32-S3 GPIO5 (TWAI_RX_PIN) <- transceiver RXD / CRX
       3V3 -> VCC, GND -> GND (common ground with the motor supply)
       CANH/CANL -> motor bus, with 120 ohm termination at each end.
  2. Copy twai.py, motor_driver.py, motor_web.py, status_led.py, main.py, and the static/
     folder onto the board's flash (e.g. with Thonny or
     `mpremote cp ... :`).
  3. Run this file (or save it as the board's main.py so it starts on
     power-up).
  4. Connect a laptop/phone to the WIFI_AP_SSID network below, then browse
     to http://<ip printed on boot>/ (typically http://192.168.4.1/).
"""

import network

from twai import TWAI
from status_led import StatusLed
import motor_web

# --- configure for your wiring/network ----------------------------------
TWAI_TX_PIN = 4
TWAI_RX_PIN = 5
TWAI_BAUDRATE = 1_000_000

# Built-in WS2812 RGB LED on GPIO48; this board only powers it while GPIO11
# is driven high, so keep GPIO11 free for that. Blinking white = waiting
# for the web page, green = page connected, yellow = scanning, blue =
# changing id, orange = setting zero position.
RGB_LED_PIN = 48
RGB_LED_POWER_PIN = 11

WIFI_AP_SSID = "Motor_Configurator"  # visible SSID of the WiFi AP
WIFI_AP_PASSWORD = "gen2_123"  # WPA2-PSK requires at least 8 characters

HTTP_PORT = 80
# -------------------------------------------------------------------------


def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=WIFI_AP_SSID, password=WIFI_AP_PASSWORD, authmode=network.AUTH_WPA2_PSK)
    while not ap.active():
        pass
    return ap


def main():
    led = StatusLed(RGB_LED_PIN, power_pin=RGB_LED_POWER_PIN)  # blinks white from boot
    ap = start_ap()
    ip = ap.ifconfig()[0]
    print("WiFi AP '%s' up (password: %s)" % (WIFI_AP_SSID, WIFI_AP_PASSWORD))
    print("Connect to it, then browse to http://%s/" % ip)

    bus = TWAI(tx=TWAI_TX_PIN, rx=TWAI_RX_PIN, baudrate=TWAI_BAUDRATE)
    info = "TWAI tx=%d rx=%d @ %d bps" % (TWAI_TX_PIN, TWAI_RX_PIN, TWAI_BAUDRATE)
    try:
        motor_web.run(bus, host="0.0.0.0", port=HTTP_PORT, info=info, led=led)
    finally:
        led.off()
        bus.deinit()


if __name__ == "__main__":
    main()
