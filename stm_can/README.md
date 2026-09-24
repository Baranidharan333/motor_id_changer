# MicroPython port for Nucleo-F207ZG

This workspace builds MicroPython for the ST Nucleo-F207ZG (STM32F207ZGT6).

Upstream MicroPython's STM32 port doesn't support the F2 family (only F0, F4,
F7, G0, G4, H5, H7, L0, L1, L4, N6, U5, WB, WL), so this adds it locally:

- STM32F2 CMSIS device files and HAL driver, vendored from
  [`STMicroelectronics/cmsis_device_f2`](https://github.com/STMicroelectronics/cmsis_device_f2)
  and
  [`STMicroelectronics/stm32f2xx_hal_driver`](https://github.com/STMicroelectronics/stm32f2xx_hal_driver),
  into `micropython/lib/stm32lib/` (this directory is normally a git
  submodule pointing at `micropython/stm32lib`, which has no F2 support; here
  it's populated directly instead — see `micropython/lib/stm32lib/README.md`).
- `MCU_SERIES=f2` wiring in `ports/stm32/stm32.mk` and `ports/stm32/Makefile`
  (Cortex-M3, no hardware FPU, classic bxCAN, USB OTG FS via TinyUSB).
- Small patches across `ports/stm32/*.c/.h` (clock config, DMA, ADC, UART,
  timers, flash) adding STM32F2 alongside the STM32F4/F7 branches whose
  register layout it shares.
- A compatibility shim in `ports/stm32/boards/stm32f2xx_hal_conf_base.h` for
  `can.c`/`pyb_can.c`/`machine_can.c`: those files are written against ST's
  older bxCAN HAL API (`CanTxMsgTypeDef`, `CAN_FilterConfTypeDef`, etc.),
  which is what the F0/F4/F7 HAL versions pinned by MicroPython's `stm32lib`
  still expose, but the current STM32F2 HAL has migrated to the newer
  `CAN_TxHeaderTypeDef`/`CAN_FilterTypeDef` API. The shim aliases the
  renamed types/macros back (bxCAN's register layout is identical between F2
  and F4, so this is safe).

Hardware mapping (from the
[Zephyr board doc](https://docs.zephyrproject.org/latest/boards/st/nucleo_f207zg/doc/index.html)):

- REPL UART: USART3, `PD8` TX and `PD9` RX, 115200 8N1
- CAN1: `PD1` TX and `PD0` RX
- CAN2: `PB6` TX and `PB5` RX
- I2C1: `PB8` SCL and `PB9` SDA
- SPI1: `PA5` SCK, `PA6` MISO, `PA7` MOSI
- User button: `PC13`
- LEDs: `PB0`, `PB7`, and `PB14`
- USB FS: `PA11` DM and `PA12` DP
- HSE: 8 MHz; system clock: 120 MHz

Board files are in `micropython/ports/stm32/boards/NUCLEO_F207ZG/`.

## Known limitations

- **`pyb.ADC`/`pyb.ADCAll` are disabled** (`MICROPY_HW_ENABLE_ADC (0)` in
  `mpconfigboard.h`). `pins.csv`/`stm32f207_af.csv` only cover the pins
  above, so no pin is marked ADC-capable yet; `machine.ADC` still builds but
  will raise at runtime for any pin until the AF table is extended to cover
  the Arduino/Morpho analog headers.
- **Ethernet/lwIP/SSL are disabled** (`MICROPY_PY_LWIP = 0` in
  `mpconfigboard.mk`). The Nucleo-144 board has an RMII PHY, but its pins
  aren't wired up in `mpconfigboard.h` yet.
- **`machine.freq()` can't change the clock at runtime** — F2 isn't in
  `powerctrl_set_sysclk`'s series list (it needs a `pllvalues.py`-generated
  table this port doesn't have for F2 yet). The clock is fixed at 120 MHz.
- **`pyb.RTC().calibration()` raises `NotImplementedError`**, and
  `datetime()`/`time.time()` only have whole-second resolution. STM32F2's
  RTC predates the sub-second shadow register (`RTC_SSR`) and smooth
  calibration register (`RTC_CALR`) that F4 added.
- Only 53 pins are defined (the ones listed above), not the full GPIO
  breakout the physical Nucleo-144 board exposes via its Morpho/Zio headers.

None of these block CAN, I2C, SPI, USB, RNG, or the REPL.

## Building

Install `arm-none-eabi-gcc` (e.g. `apt install gcc-arm-none-eabi`, or a
portable [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads)
tarball on `PATH`), then from `micropython/`:

```sh
make -C mpy-cross
cd ports/stm32
# lib/stm32lib is populated locally, not a real submodule -- see its README.
# Everything else still needs fetching:
git submodule update --init ../../lib/CMSIS_6 ../../lib/libhydrogen ../../lib/tinyusb ../../lib/micropython-lib
make BOARD=NUCLEO_F207ZG
```

Output is `ports/stm32/build-NUCLEO_F207ZG/firmware.{bin,hex,dfu}` — this has
been built successfully (~320 KB text, well within the 944 KB code region;
~27 KB static data, well within the 112 KB RAM budget after the 16 KB
filesystem cache).

## Flashing

The Nucleo board's on-board ST-LINK exposes a USB mass-storage drive — the
standard/simplest option is to copy `firmware.bin` onto that drive. From
this checkout, `make BOARD=NUCLEO_F207ZG deploy-stlink` (needs `st-flash`
from the `stlink-tools` package) or `deploy` (needs OpenOCD) both work too.
This hasn't been tested against real hardware here — only the build itself
has been verified.
