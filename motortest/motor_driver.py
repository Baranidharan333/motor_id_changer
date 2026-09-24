#!/usr/bin/env python3
"""
DM-J4340-2EC motor driver: CAN protocol layer.

Covers two protocols used by this motor family:

1. MIT-mode probe/feedback (documented in the manual's "Control Frame in
   MIT Mode" / "Feedback Frame" tables) -- used to scan for motors and read
   back position/velocity/torque/temperature.

2. A community-sourced register read/write protocol (NOT in the manual
   shipped with this motor) used to change ESC_ID (CAN id) / MST_ID
   (feedback id), enable/disable, save to flash, and set zero position:

     Register read:  arbitration_id=0x7FF, data = [id_lo, id_hi, 0x33, RID, 0,0,0,0]
     Register write: arbitration_id=0x7FF, data = [id_lo, id_hi, 0x55, RID, v0,v1,v2,v3]
     Save to flash:  arbitration_id=0x7FF, data = [id_lo, id_hi, 0xAA, 0,   0,0,0,0]
     Enable/disable: arbitration_id=<motor CAN id>, data = [0xFF]*7 + [0xFC|0xFD]

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

Requires: python-can, a SocketCAN interface already up at 1 Mbps
(e.g. `sudo ip link set can0 up type can bitrate 1000000`).
"""

import struct
import time

import can

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
CMD_ENABLE = 0xFC
CMD_DISABLE = 0xFD
CMD_SET_ZERO = 0xFE

REG_BROADCAST_ID = 0x7FF


def uint_to_float(x: int, x_min: float, x_max: float, bits: int) -> float:
    span = (1 << bits) - 1
    return x / span * (x_max - x_min) + x_min


def u32_to_le_bytes(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def le_bytes_to_u32(data: bytes) -> int:
    return struct.unpack("<I", bytes(data))[0]


def build_zero_command_frame(motor_id: int) -> can.Message:
    """MIT-mode command frame with p_des=0, v_des=0, Kp=0, Kd=0, t_ff=0.

    All-zero data is a harmless zero-torque/zero-gain probe that still makes
    the motor emit a feedback frame.
    """
    return can.Message(arbitration_id=motor_id, is_extended_id=False, data=bytes(8))


def build_reg_frame(current_id: int, cmd: int, rid: int, value: int = 0) -> can.Message:
    data = bytes([current_id & 0xFF, (current_id >> 8) & 0xFF, cmd, rid]) + u32_to_le_bytes(value)
    return can.Message(arbitration_id=REG_BROADCAST_ID, is_extended_id=False, data=data)


def build_control_frame(current_id: int, cmd_byte: int) -> can.Message:
    data = bytes([0xFF] * 7 + [cmd_byte])
    return can.Message(arbitration_id=current_id, is_extended_id=False, data=data)


def decode_feedback(frame: can.Message):
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

    position = uint_to_float(pos_raw, -P_MAX, P_MAX, 16)
    velocity = uint_to_float(vel_raw, -V_MAX, V_MAX, 12)
    torque = uint_to_float(trq_raw, -T_MAX, T_MAX, 12)

    return {
        "id": motor_id,
        "err": err,
        "state": ERR_NAMES.get(err, f"Unknown(0x{err:X})"),
        "position": position,
        "velocity": velocity,
        "torque": torque,
        "t_mos": d[6],
        "t_rotor": d[7],
        "arb_id": frame.arbitration_id,
    }


def flush_bus(bus: can.BusABC):
    while bus.recv(timeout=0.0) is not None:
        pass


def safe_send(bus: can.BusABC, frame: can.Message) -> bool:
    """bus.send() that survives a flaky/error-passive bus instead of raising.

    A large accumulated error count on `ip -details -statistics link show <chan>`
    (state ERROR-PASSIVE or BUS-OFF) usually means bad termination, wiring, or a
    bitrate mismatch on the bus -- that's a hardware problem this can't fix, but
    it shouldn't crash the whole scan/request either.
    """
    try:
        bus.send(frame)
        return True
    except can.CanOperationError as e:
        print(f"  CAN send failed ({e}) -- bus may be error-passive/bus-off. "
              f"Check termination/wiring/bitrate (`ip -details -statistics link show <chan>`).")
        return False


def send_and_await_reply(bus: can.BusABC, frame: can.Message, rid: int, retries: int, timeout: float):
    """Send a register frame, wait for the matching echo, return its (id, value) or None."""
    for _ in range(retries):
        if not safe_send(bus, frame):
            time.sleep(0.05)
            continue
        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = bus.recv(timeout=max(0.0, deadline - time.time()))
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


def read_register(bus: can.BusABC, current_id: int, rid: int, retries=10, timeout=0.1):
    frame = build_reg_frame(current_id, CMD_READ, rid)
    result = send_and_await_reply(bus, frame, rid, retries, timeout)
    return result[1] if result else None


def write_register(bus: can.BusABC, current_id: int, rid: int, value: int, retries=10, timeout=0.1) -> bool:
    frame = build_reg_frame(current_id, CMD_WRITE, rid, value)
    result = send_and_await_reply(bus, frame, rid, retries, timeout)
    return result is not None and result[1] == value


def disable(bus: can.BusABC, current_id: int):
    safe_send(bus, build_control_frame(current_id, CMD_DISABLE))
    time.sleep(0.1)
    flush_bus(bus)


def enable(bus: can.BusABC, current_id: int):
    safe_send(bus, build_control_frame(current_id, CMD_ENABLE))
    time.sleep(0.1)
    flush_bus(bus)


def save_to_flash(bus: can.BusABC, current_id: int):
    disable(bus, current_id)
    frame = can.Message(
        arbitration_id=REG_BROADCAST_ID,
        is_extended_id=False,
        data=bytes([current_id & 0xFF, (current_id >> 8) & 0xFF, CMD_SAVE, 0, 0, 0, 0, 0]),
    )
    safe_send(bus, frame)
    time.sleep(0.2)


def set_zero_position(bus: can.BusABC, current_id: int):
    """Save the motor's current shaft position as its new zero. Disables first for safety."""
    disable(bus, current_id)
    safe_send(bus, build_control_frame(current_id, CMD_SET_ZERO))
    time.sleep(0.1)
    flush_bus(bus)


def scan_for_motors(bus: can.BusABC, id_start: int, id_end: int, listen_timeout: float):
    flush_bus(bus)
    candidate_ids = list(range(id_start, id_end + 1))
    for motor_id in candidate_ids:
        safe_send(bus, build_zero_command_frame(motor_id))
        time.sleep(0.003)  # pace sends so a struggling bus doesn't ENOBUFS

    found = {}
    deadline = time.time() + listen_timeout
    while time.time() < deadline:
        frame = bus.recv(timeout=max(0.0, deadline - time.time()))
        if frame is None:
            break
        info = decode_feedback(frame)
        if info is not None and info["id"] in candidate_ids:
            found[info["id"]] = info
    return found


def probe_motor(bus: can.BusABC, motor_id: int, timeout: float = 0.3):
    """Ping a single CAN id and return its decoded feedback info, or None if silent."""
    flush_bus(bus)
    safe_send(bus, build_zero_command_frame(motor_id))
    deadline = time.time() + timeout
    while time.time() < deadline:
        frame = bus.recv(timeout=max(0.0, deadline - time.time()))
        if frame is None:
            break
        info = decode_feedback(frame)
        if info is not None and info["id"] == (motor_id & 0x0F):
            return info
    return None
