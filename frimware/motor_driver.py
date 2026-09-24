"""
DM-J4340-2EC motor driver: CAN protocol layer (MicroPython / ESP32-S3).

Runs on the ESP32-S3's built-in TWAI controller through twai.py, wired to
the bus via an external 3.3V CAN transceiver (SN65HVD230 / TJA1051 ...).

Covers two protocols used by this motor family:

1. MIT-mode probe/feedback (documented in the manual's "Control Frame in
   MIT Mode" / "Feedback Frame" tables) -- used to scan for motors and read
   back position/velocity/torque/temperature.

2. A community-sourced register read/write protocol (NOT in the manual
   shipped with this motor) used to change ESC_ID (CAN id) / MST_ID
   (feedback id), save to flash, and set zero position:

     Register read:  arbitration_id=0x7FF, data = [id_lo, id_hi, 0x33, RID, 0,0,0,0]
     Register write: arbitration_id=0x7FF, data = [id_lo, id_hi, 0x55, RID, v0,v1,v2,v3]
     Save to flash:  arbitration_id=0x7FF, data = [id_lo, id_hi, 0xAA, 0,   0,0,0,0]
     Disable:        arbitration_id=<motor CAN id>, data = [0xFF]*7 + [0xFD]
     Set zero:       arbitration_id=<motor CAN id>, data = [0xFF]*7 + [0xFE]

   "id_lo/id_hi" select which motor on the bus should act, using that
   motor's *current* CAN id (ESC_ID) -- this is a payload field, not the
   arbitration id, since register commands are always sent to the
   broadcast id 0x7FF. RID 7 = MST_ID (feedback id), RID 8 = ESC_ID (CAN
   id), both little-endian uint32. The device echoes back the new value on
   a reply frame carrying cmd byte 0x33 or 0x55, which is used here to
   verify each write.

   Register writes take effect in RAM immediately but are lost on
   power-cycle until "save to flash" (0xAA) is sent. If a write is
   interrupted before the save step, power-cycling the motor reverts it to
   its last-saved IDs -- so an aborted write is safe to recover from.

   Disable is only sent internally, as a safety step before saving to
   flash or setting zero -- there is no user-facing enable/disable.
"""

import struct
import time

from twai import CANMessage, TWAIError

# Default MIT-mode mapping ranges used by DM-series motors for decoding
# position/velocity/torque out of the fixed-point feedback fields. These are
# read back precisely via the debugging assistant (PMAX/VMAX/TMAX registers);
# these are just the common defaults used when no register readout has been
# done yet.
P_MAX = 12.5
V_MAX = 30.0
T_MAX = 10.0

ERR_NAMES = {
    0x0: "Disabled",
    0x1: "Enabled",
    0x8: "Overvoltage",
    0x9: "Undervoltage",
    0xA: "Overcurrent",
    0xB: "MOS Overtemperature",
    0xC: "Motor Coil Overtemperature",
    0xD: "Communication Loss",
    0xE: "Overload",
}

REG_MST_ID = 7  # feedback id
REG_ESC_ID = 8  # CAN (receive) id

CMD_READ = 0x33
CMD_WRITE = 0x55
CMD_SAVE = 0xAA
CMD_DISABLE = 0xFD
CMD_SET_ZERO = 0xFE

REG_BROADCAST_ID = 0x7FF

# How long send() may wait for a free TX buffer. With no other node on the
# bus to ACK, the controller retransmits forever and the buffer never frees.
SEND_TIMEOUT = 0.05


def _ms_left(deadline):
    return time.ticks_diff(deadline, time.ticks_ms())


def _deadline(timeout):
    return time.ticks_add(time.ticks_ms(), int(timeout * 1000))


def uint_to_float(x, x_min, x_max, bits):
    span = (1 << bits) - 1
    return x / span * (x_max - x_min) + x_min


def u32_to_le_bytes(value):
    return struct.pack("<I", value & 0xFFFFFFFF)


def le_bytes_to_u32(data):
    return struct.unpack("<I", bytes(data))[0]


def build_zero_command_frame(motor_id):
    """MIT-mode command frame with p_des=0, v_des=0, Kp=0, Kd=0, t_ff=0.

    All-zero data is a harmless zero-torque/zero-gain probe that still makes
    the motor emit a feedback frame.
    """
    return CANMessage(motor_id, bytes(8))


def build_reg_frame(current_id, cmd, rid, value=0):
    data = bytes([current_id & 0xFF, (current_id >> 8) & 0xFF, cmd, rid]) + u32_to_le_bytes(value)
    return CANMessage(REG_BROADCAST_ID, data)


def build_control_frame(current_id, cmd_byte):
    return CANMessage(current_id, bytes([0xFF] * 7 + [cmd_byte]))


def decode_feedback(frame):
    """Decode a feedback frame per the manual's "Feedback Frame" table.

    D0 = ID | ERR<<4
    D1,D2 = POS[15:8], POS[7:0]      (16-bit)
    D3,D4 = VEL[11:4], VEL[3:0]|T[11:8]   (12-bit)
    D5 = T[7:0]
    D6 = T_MOS (deg C)
    D7 = T_Rotor (deg C)
    """
    if len(frame.data) < 8:
        return None

    d = frame.data
    motor_id = d[0] & 0x0F
    err = (d[0] >> 4) & 0x0F

    pos_raw = (d[1] << 8) | d[2]
    vel_raw = (d[3] << 4) | (d[4] >> 4)
    trq_raw = ((d[4] & 0x0F) << 8) | d[5]

    return {
        "id": motor_id,
        "err": err,
        "state": ERR_NAMES.get(err, "Unknown(0x%X)" % err),
        "position": uint_to_float(pos_raw, -P_MAX, P_MAX, 16),
        "velocity": uint_to_float(vel_raw, -V_MAX, V_MAX, 12),
        "torque": uint_to_float(trq_raw, -T_MAX, T_MAX, 12),
        "t_mos": d[6],
        "t_rotor": d[7],
        "arb_id": frame.arbitration_id,
    }


def flush_bus(bus):
    bus.flush_rx()


def safe_send(bus, frame):
    """bus.send() that survives a flaky/error-passive bus instead of raising.

    Repeated failures usually mean no motor is ACKing: check the transceiver
    wiring (TX/RX not swapped, 3.3V supply), the 120 ohm termination and
    that the bitrate matches the motors -- a hardware problem this can't fix,
    but it shouldn't crash the whole scan/request either.
    """
    try:
        bus.send(frame, timeout=SEND_TIMEOUT)
        return True
    except TWAIError as e:
        print("  CAN send failed (%s) state=%s -- check transceiver wiring, "
              "termination and bitrate." % (e, bus.state()))
        if bus.state()["bus_off"]:
            bus.restart()
        return False


def send_and_await_reply(bus, frame, rid, retries, timeout):
    """Send a register frame, wait for the matching echo, return its (id, value) or None."""
    for _ in range(retries):
        if not safe_send(bus, frame):
            time.sleep_ms(50)
            continue
        deadline = _deadline(timeout)
        while _ms_left(deadline) > 0:
            reply = bus.recv(timeout=max(0, _ms_left(deadline)) / 1000)
            if reply is None:
                break
            if len(reply.data) != 8 or reply.data[3] != rid:
                continue
            if reply.data[2] not in (CMD_READ, CMD_WRITE):
                continue
            echoed_id = reply.data[0] | (reply.data[1] << 8)
            value = le_bytes_to_u32(reply.data[4:8])
            return echoed_id, value
    return None


def read_register(bus, current_id, rid, retries=10, timeout=0.1):
    frame = build_reg_frame(current_id, CMD_READ, rid)
    result = send_and_await_reply(bus, frame, rid, retries, timeout)
    return result[1] if result else None


def write_register(bus, current_id, rid, value, retries=10, timeout=0.1):
    frame = build_reg_frame(current_id, CMD_WRITE, rid, value)
    result = send_and_await_reply(bus, frame, rid, retries, timeout)
    return result is not None and result[1] == value


def disable(bus, current_id):
    """Safety step before flash/zero writes -- not exposed in the UI."""
    safe_send(bus, build_control_frame(current_id, CMD_DISABLE))
    time.sleep_ms(100)
    flush_bus(bus)


def save_to_flash(bus, current_id):
    disable(bus, current_id)
    frame = CANMessage(
        REG_BROADCAST_ID,
        bytes([current_id & 0xFF, (current_id >> 8) & 0xFF, CMD_SAVE, 0, 0, 0, 0, 0]),
    )
    safe_send(bus, frame)
    time.sleep_ms(200)


def set_zero_position(bus, current_id):
    """Save the motor's current shaft position as its new zero. Disables first for safety."""
    disable(bus, current_id)
    safe_send(bus, build_control_frame(current_id, CMD_SET_ZERO))
    time.sleep_ms(100)
    flush_bus(bus)


def _collect_feedback(bus, found, candidate_ids, timeout):
    """Drain feedback frames into `found` for up to `timeout` seconds."""
    deadline = _deadline(timeout)
    while True:
        frame = bus.recv(timeout=max(0, _ms_left(deadline)) / 1000)
        if frame is None:
            return
        info = decode_feedback(frame)
        if info is not None and info["id"] in candidate_ids:
            found[info["id"]] = info


def scan_for_motors(bus, id_start, id_end, listen_timeout):
    flush_bus(bus)
    candidate_ids = list(range(id_start, id_end + 1))
    found = {}
    # The TWAI RX FIFO only holds ~5 frames, so drain replies between sends
    # instead of firing every probe first and reading afterwards.
    for motor_id in candidate_ids:
        safe_send(bus, build_zero_command_frame(motor_id))
        _collect_feedback(bus, found, candidate_ids, 0.003)
    _collect_feedback(bus, found, candidate_ids, listen_timeout)
    return found


def probe_motor(bus, motor_id, timeout=0.3):
    """Ping a single CAN id and return its decoded feedback info, or None if silent."""
    flush_bus(bus)
    safe_send(bus, build_zero_command_frame(motor_id))
    deadline = _deadline(timeout)
    while _ms_left(deadline) > 0:
        frame = bus.recv(timeout=max(0, _ms_left(deadline)) / 1000)
        if frame is None:
            break
        info = decode_feedback(frame)
        if info is not None and info["id"] == (motor_id & 0x0F):
            return info
    return None
