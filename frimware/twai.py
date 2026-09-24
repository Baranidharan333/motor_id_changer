"""
Pure-MicroPython, register-level driver for the ESP32-S3's built-in TWAI
(Two-Wire Automotive Interface -- i.e. classic CAN 2.0) controller.

Mainline MicroPython does not expose a CAN/TWAI class on the ESP32 port, so
this talks to the TWAI peripheral's memory-mapped registers directly via
`machine.mem32`, the way esp-idf's driver does internally. No firmware
rebuild is needed -- copy this file onto the board (e.g. with Thonny or
`mpremote cp twai.py :twai.py`) next to your other scripts.

All register addresses, bit layouts and bus-timing values below were taken
from Espressif's esp-idf source for the esp32s3 target (release/v5.4):
  components/soc/esp32s3/register/soc/twai_struct.h   (register layout)
  components/soc/esp32s3/register/soc/reg_base.h      (peripheral base addrs)
  components/hal/esp32s3/include/hal/twai_ll.h        (bus timing math)
  components/hal/include/hal/twai_types.h             (timing config table)
  components/soc/esp32s3/register/soc/{gpio_reg,io_mux_reg}.h (GPIO matrix)
  components/driver/twai/twai.c                        (GPIO routing sequence)

Wiring: this only drives TWAI's TX/RX signals to two GPIOs of your choice via
the GPIO matrix -- you still need an external 3.3V CAN transceiver (e.g.
SN65HVD230 / TJA1051) between those pins and the physical CAN_H/CAN_L bus.

Example:
    from twai import TWAI, CANMessage

    bus = TWAI(tx=4, rx=5, baudrate=1_000_000)
    bus.send(CANMessage(0x01, bytes(8)))
    msg = bus.recv(timeout=0.5)
    if msg is not None:
        print(hex(msg.arbitration_id), msg.data)
    bus.deinit()
"""

from machine import mem32
import time

# ---------------------------------------------------------------- SoC bases
_SYSTEM_BASE = 0x600C0000
_GPIO_BASE = 0x60004000
_IO_MUX_BASE = 0x60009000
_TWAI_BASE = 0x6002B000

_APB_CLK_FREQ = 80_000_000

# ------------------------------------------------------- SYSTEM (clock/rst)
_SYSTEM_PERIP_CLK_EN0 = _SYSTEM_BASE + 0x18
_SYSTEM_PERIP_RST_EN0 = _SYSTEM_BASE + 0x20
_CAN_CLK_EN_BIT = 1 << 19  # SYSTEM_PERIP_CLK_EN0.can_clk_en
_CAN_RST_BIT = 1 << 19     # SYSTEM_PERIP_RST_EN0.can_rst

# -------------------------------------------------------------- GPIO matrix
_GPIO_ENABLE_W1TS = _GPIO_BASE + 0x24
_GPIO_ENABLE_W1TC = _GPIO_BASE + 0x28
_GPIO_ENABLE1_W1TS = _GPIO_BASE + 0x30
_GPIO_ENABLE1_W1TC = _GPIO_BASE + 0x34
_GPIO_FUNC_OUT_SEL_CFG = _GPIO_BASE + 0x554  # + 4 * gpio_num
_GPIO_FUNC_IN_SEL_CFG = _GPIO_BASE + 0x154   # + 4 * signal_idx

_TWAI_TX_IDX = 116
_TWAI_RX_IDX = 116

_IO_MUX_GPIO0 = _IO_MUX_BASE + 0x04  # + 4 * gpio_num
_MCU_SEL_S = 12
_MCU_SEL_M = 0x7 << _MCU_SEL_S
_PIN_FUNC_GPIO = 1
_FUN_IE = 1 << 9

# --------------------------------------------------------- TWAI registers
# (offsets from _TWAI_BASE; layout per soc/twai_struct.h)
_MODE = 0x00
_CMD = 0x04
_STATUS = 0x08
_IR = 0x0C
_IER = 0x10
_BTR0 = 0x18
_BTR1 = 0x1C
_ALC = 0x2C
_ECC = 0x30
_EWL = 0x34
_RXERR = 0x38
_TXERR = 0x3C
_BUF0 = 0x40      # 13 shared registers, 0x40 .. 0x70
_RMC = 0x74
_CDR = 0x7C

_MOD_RM = 1 << 0
_MOD_LOM = 1 << 1
_MOD_STM = 1 << 2
_MOD_AFM = 1 << 3

_CMD_TR = 1 << 0
_CMD_AT = 1 << 1
_CMD_RRB = 1 << 2
_CMD_CDO = 1 << 3
_CMD_SRR = 1 << 4

_ST_RBS = 1 << 0
_ST_DOS = 1 << 1
_ST_TBS = 1 << 2
_ST_TCS = 1 << 3
_ST_RS = 1 << 4
_ST_TS = 1 << 5
_ST_ES = 1 << 6
_ST_BS = 1 << 7

# esp-idf twai_mode_t ordering
NORMAL = 0
NO_ACK = 1
LISTEN_ONLY = 2

# Verified bus-timing table for APB_CLK_FREQ = 80MHz (matches esp-idf's
# TWAI_TIMING_CONFIG_*BITS() macros for esp32s3 -- see hal/twai_types.h).
# {baudrate: (brp, tseg1, tseg2, sjw)}
_BAUD_TABLE = {
    1_000_000: (4, 15, 4, 3),
    800_000: (4, 16, 8, 3),
    500_000: (8, 15, 4, 3),
    250_000: (16, 15, 4, 3),
    125_000: (32, 15, 4, 3),
    100_000: (40, 15, 4, 3),
    50_000: (80, 15, 4, 3),
    25_000: (128, 16, 8, 3),
}


def _rd(off):
    return mem32[_TWAI_BASE + off]


def _wr(off, val):
    mem32[_TWAI_BASE + off] = val


def _compute_timing(baudrate):
    if baudrate in _BAUD_TABLE:
        return _BAUD_TABLE[baudrate]
    # Fallback: 20 time quanta/bit, 80% sample point (tseg1=15, tseg2=4).
    tseg1, tseg2, sjw = 15, 4, 3
    tq = 1 + tseg1 + tseg2
    brp = round(_APB_CLK_FREQ / (baudrate * tq))
    brp -= brp % 2
    if brp < 2:
        brp = 2
    elif brp > 16384:
        brp = 16384
    return (brp, tseg1, tseg2, sjw)


class TWAIError(Exception):
    """Raised for a send timeout or an active bus error/bus-off condition."""


class TWAIBusOff(TWAIError):
    """The controller is in the bus-off state; call TWAI.restart() to recover."""


class CANMessage:
    def __init__(self, arbitration_id, data=b"", is_extended_id=False,
                 is_remote_frame=False, dlc=None):
        if not is_remote_frame and len(data) > 8:
            raise ValueError("data must be at most 8 bytes")
        self.arbitration_id = arbitration_id
        self.data = bytes(data)
        self.is_extended_id = bool(is_extended_id)
        self.is_remote_frame = bool(is_remote_frame)
        self.dlc = len(self.data) if dlc is None else dlc

    def __repr__(self):
        return "CANMessage(id=0x%X, extended=%s, rtr=%s, data=%s)" % (
            self.arbitration_id, self.is_extended_id, self.is_remote_frame,
            bytes(self.data).hex(),
        )


def _gpio_output_enable(pin):
    if pin < 32:
        mem32[_GPIO_ENABLE_W1TS] = 1 << pin
    else:
        mem32[_GPIO_ENABLE1_W1TS] = 1 << (pin - 32)


def _gpio_output_disable(pin):
    if pin < 32:
        mem32[_GPIO_ENABLE_W1TC] = 1 << pin
    else:
        mem32[_GPIO_ENABLE1_W1TC] = 1 << (pin - 32)


def _io_mux_set_gpio_func(pin, input_enable):
    addr = _IO_MUX_GPIO0 + 4 * pin
    val = mem32[addr]
    val &= ~_MCU_SEL_M
    val |= _PIN_FUNC_GPIO << _MCU_SEL_S
    if input_enable:
        val |= _FUN_IE
    else:
        val &= ~_FUN_IE
    mem32[addr] = val


def _connect_out_signal(pin, signal_idx):
    _io_mux_set_gpio_func(pin, input_enable=False)
    mem32[_GPIO_FUNC_OUT_SEL_CFG + 4 * pin] = signal_idx & 0x1FF
    _gpio_output_enable(pin)


def _connect_in_signal(pin, signal_idx):
    _io_mux_set_gpio_func(pin, input_enable=True)
    _gpio_output_disable(pin)  # in case this pin was left as an output by earlier code
    mem32[_GPIO_FUNC_IN_SEL_CFG + 4 * signal_idx] = (pin & 0x3F) | (1 << 7)


class TWAI:
    def __init__(self, tx, rx, baudrate=1_000_000, mode=NORMAL, timing=None):
        """tx/rx are plain GPIO pin numbers. `timing`, if given, overrides
        the baudrate lookup/formula with an explicit (brp, tseg1, tseg2, sjw)
        tuple -- see the register offset math in _compute_timing()."""
        self._mode = mode

        # 1. Power on the TWAI peripheral (clock enable + reset pulse).
        mem32[_SYSTEM_PERIP_CLK_EN0] = mem32[_SYSTEM_PERIP_CLK_EN0] | _CAN_CLK_EN_BIT
        mem32[_SYSTEM_PERIP_RST_EN0] = mem32[_SYSTEM_PERIP_RST_EN0] | _CAN_RST_BIT
        mem32[_SYSTEM_PERIP_RST_EN0] = mem32[_SYSTEM_PERIP_RST_EN0] & ~_CAN_RST_BIT

        # 2. Route TX/RX through the GPIO matrix to the chosen pins.
        _connect_out_signal(tx, _TWAI_TX_IDX)
        _connect_in_signal(rx, _TWAI_RX_IDX)

        # 3. Enter reset mode -- required to touch config registers.
        _wr(_MODE, _MOD_RM)
        if not (_rd(_MODE) & _MOD_RM):
            raise RuntimeError(
                "TWAI did not enter reset mode -- peripheral clock/reset "
                "not applied correctly")
        _wr(_TXERR, 0)
        _wr(_RXERR, 0)
        _wr(_EWL, 96)

        # 4. Bus timing.
        brp, tseg1, tseg2, sjw = timing if timing else _compute_timing(baudrate)
        brp_field = (brp // 2) - 1
        sjw_field = sjw - 1
        _wr(_BTR0, (brp_field & 0x1FFF) | ((sjw_field & 0x3) << 14))
        _wr(_BTR1, ((tseg1 - 1) & 0xF) | (((tseg2 - 1) & 0x7) << 4))

        # 5. Accept-all acceptance filter (single filter mode).
        for i in range(4):
            _wr(_BUF0 + 4 * i, 0x00)        # acceptance code bytes
            _wr(_BUF0 + 4 * (i + 4), 0xFF)  # acceptance mask bytes ("don't care")
        _wr(_MODE, _rd(_MODE) | _MOD_AFM)

        # 6. No CLKOUT pin, no interrupts (this driver polls).
        _wr(_CDR, 0x100)
        _wr(_IER, 0)
        _rd(_IR)  # reading clears any latched interrupt bits

        # 7. Exit reset mode with the requested operating mode -- now live.
        self._set_mode(mode)
        _wr(_TXERR, 0)
        _wr(_RXERR, 128 if mode == LISTEN_ONLY else 0)
        _rd(_IR)
        _wr(_MODE, _rd(_MODE) & ~_MOD_RM)

    def _set_mode(self, mode):
        val = _rd(_MODE) & ~(_MOD_LOM | _MOD_STM)
        if mode == NO_ACK:
            val |= _MOD_STM
        elif mode == LISTEN_ONLY:
            val |= _MOD_LOM
        _wr(_MODE, val)

    # ------------------------------------------------------------- framing
    @staticmethod
    def _format_frame(msg):
        buf = bytearray(13)
        dlc = min(msg.dlc, 8)
        buf[0] = (dlc & 0xF) | (0x40 if msg.is_remote_frame else 0) | \
                 (0x80 if msg.is_extended_id else 0)
        if msg.is_extended_id:
            ident = (msg.arbitration_id & 0x1FFFFFFF) << 3
            buf[1] = (ident >> 24) & 0xFF
            buf[2] = (ident >> 16) & 0xFF
            buf[3] = (ident >> 8) & 0xFF
            buf[4] = ident & 0xFF
            data_off = 5
        else:
            ident = (msg.arbitration_id & 0x7FF) << 5
            buf[1] = (ident >> 8) & 0xFF
            buf[2] = ident & 0xFF
            data_off = 3
        if not msg.is_remote_frame:
            buf[data_off:data_off + len(msg.data)] = msg.data
        return buf

    @staticmethod
    def _parse_frame(buf):
        info = buf[0]
        dlc = info & 0xF
        is_rtr = bool(info & 0x40)
        is_extd = bool(info & 0x80)
        if is_extd:
            ident = ((buf[1] << 24) | (buf[2] << 16) | (buf[3] << 8) | buf[4]) >> 3
            ident &= 0x1FFFFFFF
            data_off = 5
        else:
            ident = ((buf[1] << 8) | buf[2]) >> 5
            ident &= 0x7FF
            data_off = 3
        data = b"" if is_rtr else bytes(buf[data_off:data_off + min(dlc, 8)])
        return CANMessage(ident, data, is_extended_id=is_extd,
                           is_remote_frame=is_rtr, dlc=dlc)

    # ---------------------------------------------------------------- I/O
    def send(self, msg, timeout=0):
        """Send a CANMessage. Raises TWAIError if the TX buffer doesn't free
        up (or the bus is off) within `timeout` seconds (0 = don't wait)."""
        deadline = None if timeout is None else time.ticks_add(
            time.ticks_ms(), int(timeout * 1000))
        while True:
            status = _rd(_STATUS)
            if status & _ST_BS:
                raise TWAIBusOff("TWAI controller is bus-off")
            if status & _ST_TBS:
                break
            if deadline is None or time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise TWAIError("send timed out waiting for a free TX buffer")
            time.sleep_ms(1)

        frame = self._format_frame(msg)
        for i, b in enumerate(frame):
            _wr(_BUF0 + 4 * i, b)
        _wr(_CMD, _CMD_TR)

    def recv(self, timeout=None):
        """Return the next received CANMessage, or None if nothing arrived
        within `timeout` seconds (0 = check once and return immediately,
        None = block until a frame arrives)."""
        deadline = None if timeout is None else time.ticks_add(
            time.ticks_ms(), int(timeout * 1000))
        while True:
            status = _rd(_STATUS)
            if status & _ST_DOS:
                _wr(_CMD, _CMD_CDO)  # clear data-overrun latch
            if status & _ST_RBS:
                buf = bytes(_rd(_BUF0 + 4 * i) & 0xFF for i in range(13))
                _wr(_CMD, _CMD_RRB)  # release buffer / pop FIFO
                return self._parse_frame(buf)
            if timeout == 0:
                return None
            if deadline is not None and time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return None
            time.sleep_ms(1)

    def flush_rx(self):
        while self.recv(timeout=0) is not None:
            pass

    # -------------------------------------------------------------- status
    def state(self):
        status = _rd(_STATUS)
        return {
            "bus_off": bool(status & _ST_BS),
            "error_warning": bool(status & _ST_ES),
            "tx_error_count": _rd(_TXERR) & 0xFF,
            "rx_error_count": _rd(_RXERR) & 0xFF,
            "rx_pending": _rd(_RMC) & 0x7F,
        }

    def restart(self):
        """Recover from bus-off: hardware runs the recovery sequence once
        reset mode is exited again."""
        _wr(_MODE, _rd(_MODE) | _MOD_RM)
        self._set_mode(self._mode)
        _wr(_TXERR, 0)
        _wr(_RXERR, 0)
        _rd(_IR)
        _wr(_MODE, _rd(_MODE) & ~_MOD_RM)

    def deinit(self):
        _wr(_MODE, _rd(_MODE) | _MOD_RM)
        _wr(_IER, 0)
        _rd(_IR)
