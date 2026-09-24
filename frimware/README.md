# ESP32-S3 DM-J4340-2EC Motor Configurator

MicroPython firmware that turns an ESP32-S3 board into a stand-alone
configurator for DM-J4340-2EC motors. The board talks to the motors over
CAN through its built-in TWAI controller, starts its own WiFi access
point, and serves a web page. No PC-side CAN adapter, python-can or
SocketCAN is needed.

From the web page you can:

- scan the bus for motors and see their state, feedback id and position
- watch live position / velocity / torque / temperatures of a selected motor
- change a motor's CAN id (ESC_ID) and/or feedback id (MST_ID) and save to flash
- set the current shaft position as zero, for one motor or all scanned motors

## Hardware

- ESP32-S3 board running MicroPython (with the built-in `neopixel` module)
- 3.3 V CAN transceiver, e.g. SN65HVD230 or TJA1051 (3.3 V variant)
- DM-J4340-2EC motor(s) at 1 Mbps

### Wiring

| ESP32-S3 | Transceiver |
|---|---|
| GPIO4 (TX) | TXD / CTX |
| GPIO5 (RX) | RXD / CRX |
| 3V3 | VCC |
| GND | GND |

Connect the transceiver's CANH/CANL to the motor bus, with a 120 Ω
terminating resistor at each end of the bus. The ESP32 ground must be
shared with the motor supply ground.

Reserved pins, keep them free:

| GPIO | Used for |
|---|---|
| 4, 5 | CAN TX / RX |
| 48 | built-in WS2812 RGB status LED |
| 11 | power switch for the RGB LED (driven high at boot) |

All of these can be changed at the top of `main.py`.

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point: starts the status LED, WiFi AP, CAN bus and web server. Pin, WiFi and bitrate settings live here. |
| `twai.py` | Register-level driver for the ESP32-S3 TWAI (CAN 2.0) controller. |
| `motor_driver.py` | DM-J4340-2EC CAN protocol: scan, probe, register read/write, save to flash, set zero. |
| `motor_web.py` | Small single-threaded HTTP server with the JSON API used by the page. |
| `status_led.py` | Drives the onboard RGB LED status colours. |
| `static/index.html` | The web UI. |
| `led_scan.py` | Optional LED colour test; not needed at runtime. |

## Installation

1. Flash MicroPython for ESP32-S3 onto the board.
2. Copy these files to the board's flash with Thonny (*File → Save copy… →
   MicroPython device*) or `mpremote`:

   ```
   mpremote cp twai.py motor_driver.py motor_web.py status_led.py main.py :
   mpremote mkdir :static
   mpremote cp static/index.html :static/index.html
   ```

3. Reset the board. `main.py` runs automatically on power-up.

## Usage

1. Connect a phone or laptop to the WiFi network:
   - SSID: `Motor_Configurator`
   - Password: `gen2_123`
2. Open **http://192.168.4.1/** in a browser.
3. Click **Scan** to find motors (default ids 1–16), then **Select** a
   motor to see its live data.
4. To change ids, enter a new CAN id and/or feedback id and click
   **Set & save to flash**. Only one motor at the selected id should be on
   the bus while doing this. Power-cycle the motor afterwards to confirm.
5. **Set zero position** stores the current shaft position as zero.

Before saving to flash or setting zero, the firmware automatically sends a
disable command to the motor as a safety step.

## Status LED

| Colour | Meaning |
|---|---|
| Blinking white | Booted, no web page connected (also after the page is closed, about 6 s) |
| Green | Web page open in a browser |
| Yellow | Scanning for motors |
| Blue | Changing CAN id / feedback id |
| Orange | Setting zero position |

The page sends a heartbeat every 2 s. If the browser tab is in the
background, browsers slow that down, so the LED may fall back to blinking
white until you return to the page. Brightness is set by `BRIGHTNESS` in
`status_led.py`.

## Configuration (`main.py`)

| Setting | Default |
|---|---|
| `TWAI_TX_PIN` / `TWAI_RX_PIN` | 4 / 5 |
| `TWAI_BAUDRATE` | 1 000 000 |
| `RGB_LED_PIN` / `RGB_LED_POWER_PIN` | 48 / 11 |
| `WIFI_AP_SSID` / `WIFI_AP_PASSWORD` | `Motor_Configurator` / `gen2_123` (min. 8 characters) |
| `HTTP_PORT` | 80 |

## Troubleshooting

- **No motors found / "CAN send failed" in the log**: no node is
  acknowledging frames. Check that TX/RX aren't swapped, the transceiver
  has 3.3 V, the bus is terminated with 120 Ω at both ends, grounds are
  shared, and the motors are at 1 Mbps.
- **LED never lights**: make sure GPIO11 isn't used for anything else;
  it powers the LED on this board.
- **Page doesn't load**: confirm you're on the `Motor_Configurator` WiFi
  and check the IP address printed in the Thonny shell at boot.

## Security

There is no authentication. Anyone who joins the board's WiFi can
reprogram connected motors, so change the WiFi password in `main.py`
before using it anywhere shared.
