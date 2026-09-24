"""
Tiny HTTP server for the DM-J4340-2EC motor scanner / CAN id (ESC_ID) and
feedback id (MST_ID) configurator web UI -- MicroPython / ESP32-S3.

Runs on the board itself: main.py opens the TWAI bus and the WiFi access
point, then calls run(), which serves static/index.html and the JSON API
the page uses. Single-threaded, one request at a time, so the CAN bus
never needs locking. There is no authentication -- anyone who joins the
board's WiFi can reprogram motors.
"""

import json
import socket

from twai import TWAIError
from status_led import YELLOW, BLUE, ORANGE
from motor_driver import (
    REG_MST_ID,
    REG_ESC_ID,
    flush_bus,
    probe_motor,
    scan_for_motors,
    write_register,
    disable,
    save_to_flash,
    set_zero_position,
)

INDEX_PATH = "static/index.html"
CLIENT_TIMEOUT = 3  # seconds; stops an idle browser connection stalling the loop

_STATUS_TEXT = {200: "OK", 400: "Bad Request", 404: "Not Found",
                500: "Internal Server Error", 503: "Service Unavailable"}

ACCEPT_TIMEOUT = 0.05  # seconds; how often the status LED is refreshed while idle

state = {"bus": None, "info": "", "led": None}


class _NoActivity:
    def __enter__(self):
        pass

    def __exit__(self, *exc):
        return False


def _led_activity(color):
    """Show `color` on the status LED for the duration of a `with` block."""
    led = state["led"]
    return led.activity(color) if led else _NoActivity()


class HTTPError(Exception):
    def __init__(self, code, payload):
        self.code = code
        self.payload = payload


def motor_info_json(info):
    if info is None:
        return None
    return {
        "state": info["state"],
        "position": round(info["position"], 4),
        "velocity": round(info["velocity"], 4),
        "torque": round(info["torque"], 4),
        "t_mos": info["t_mos"],
        "t_rotor": info["t_rotor"],
        "feedback_id": info["arb_id"],
    }


# ------------------------------------------------------------------ routes
def api_status(body):
    return {"channel": state["info"]}


def api_scan(body):
    start = int(body.get("start", 1))
    end = int(body.get("end", 16))
    timeout = float(body.get("timeout", 0.5))
    with _led_activity(YELLOW):
        found = scan_for_motors(state["bus"], start, end, timeout)
    motors = [
        {"id": motor_id, "info": motor_info_json(found[motor_id])}
        for motor_id in sorted(found)
    ]
    return {"motors": motors}


def api_probe(body):
    motor_id = int(body["id"])
    timeout = float(body.get("timeout", 0.3))
    info = probe_motor(state["bus"], motor_id, timeout)
    return {"id": motor_id, "info": motor_info_json(info)}


def api_set_id(body):
    current_id = int(body["current_id"])
    new_can_id = body.get("new_can_id")
    new_feedback_id = body.get("new_feedback_id")
    new_can_id = int(new_can_id) if new_can_id not in (None, "") else None
    new_feedback_id = int(new_feedback_id) if new_feedback_id not in (None, "") else None
    retries = int(body.get("retries", 10))
    reg_timeout = float(body.get("reg_timeout", 0.1))

    if new_can_id is None and new_feedback_id is None:
        raise HTTPError(400, {"ok": False, "log": ["Nothing to do -- no new ids given."]})

    with _led_activity(BLUE):
        return _set_id(current_id, new_can_id, new_feedback_id, retries, reg_timeout)


def _set_id(current_id, new_can_id, new_feedback_id, retries, reg_timeout):
    log = []
    bus = state["bus"]
    flush_bus(bus)
    disable(bus, current_id)
    active_id = current_id
    ok = True

    if new_feedback_id is not None:
        log.append("Writing feedback id = %d ..." % new_feedback_id)
        success = write_register(bus, active_id, REG_MST_ID, new_feedback_id, retries=retries, timeout=reg_timeout)
        log.append("  verified." if success else "  FAILED to verify -- aborting before save.")
        ok = ok and success

    if ok and new_can_id is not None:
        log.append("Writing CAN id = %d ..." % new_can_id)
        success = write_register(bus, active_id, REG_ESC_ID, new_can_id, retries=retries, timeout=reg_timeout)
        log.append("  verified." if success else "  FAILED to verify -- aborting before save.")
        ok = ok and success
        if success:
            active_id = new_can_id

    if ok:
        log.append("Saving to flash (addressing motor at CAN id %d) ..." % active_id)
        save_to_flash(bus, active_id)
        log.append("Done. Power-cycle the motor to confirm the new id(s) stick.")
    else:
        log.append("Nothing persisted -- power-cycle the motor if unsure of its state.")

    return {"ok": ok, "active_id": active_id, "log": log}


def api_zero(body):
    motor_id = int(body["id"])
    with _led_activity(ORANGE):
        set_zero_position(state["bus"], motor_id)
    return {"ok": True, "log": ["CAN id %d: zero position set." % motor_id]}


def api_zero_all(body):
    ids = [int(i) for i in body.get("ids", [])]
    log = []
    with _led_activity(ORANGE):
        for motor_id in ids:
            set_zero_position(state["bus"], motor_id)
            log.append("CAN id %d: zero position set." % motor_id)
    log.append("Done -- zeroed %d motor(s)." % len(ids))
    return {"ok": True, "log": log}


ROUTES = {
    ("GET", "/api/status"): api_status,
    ("POST", "/api/scan"): api_scan,
    ("POST", "/api/probe"): api_probe,
    ("POST", "/api/set_id"): api_set_id,
    ("POST", "/api/zero"): api_zero,
    ("POST", "/api/zero_all"): api_zero_all,
}


# -------------------------------------------------------------------- HTTP
def _send_head(cl, code, content_type, length):
    head = ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
            "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
            % (code, _STATUS_TEXT.get(code, ""), content_type, length))
    cl.sendall(head.encode())


def _send_json(cl, code, obj):
    data = json.dumps(obj).encode()
    _send_head(cl, code, "application/json", len(data))
    cl.sendall(data)


def _send_index(cl):
    with open(INDEX_PATH, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        _send_head(cl, 200, "text/html; charset=utf-8", size)
        buf = bytearray(1024)
        while True:
            n = f.readinto(buf)
            if not n:
                break
            cl.sendall(buf if n == len(buf) else buf[:n])


def _read_request(cl):
    """Return (method, path, body_dict) or None if the client sent nothing."""
    line = cl.readline()
    if not line:
        return None
    parts = line.decode().split()
    if len(parts) < 2:
        return None
    method, path = parts[0], parts[1].split("?", 1)[0]

    length = 0
    while True:
        header = cl.readline()
        if not header or header == b"\r\n":
            break
        name, _, value = header.decode().partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())

    raw = b""
    while len(raw) < length:
        chunk = cl.read(length - len(raw))
        if not chunk:
            break
        raw += chunk
    try:
        body = json.loads(raw.decode()) if raw else {}
    except ValueError:
        body = {}
    return method, path, body or {}


def _handle(cl):
    req = _read_request(cl)
    if req is None:
        return
    method, path, body = req
    if state["led"]:
        state["led"].web_activity()

    if method == "GET" and path in ("/", "/index.html"):
        _send_index(cl)
        return

    handler = ROUTES.get((method, path))
    if handler is None:
        _send_json(cl, 404, {"ok": False, "log": ["Not found: %s %s" % (method, path)]})
        return

    try:
        _send_json(cl, 200, handler(body))
    except HTTPError as e:
        _send_json(cl, e.code, e.payload)
    except TWAIError as e:
        _send_json(cl, 503, {
            "ok": False,
            "log": ["CAN send failed: %s" % e,
                    "Bus may be error-passive/bus-off -- check the transceiver wiring, "
                    "120 ohm termination and bitrate. Bus state: %s" % state["bus"].state()],
        })
    except (KeyError, ValueError, TypeError) as e:
        _send_json(cl, 400, {"ok": False, "log": ["Bad request: %r" % e]})


def run(bus, host="0.0.0.0", port=80, info="", led=None):
    state["bus"] = bus
    state["info"] = info
    state["led"] = led

    addr = socket.getaddrinfo(host, port)[0][-1]
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(addr)
    srv.listen(4)
    # Time out accept() periodically so the status LED keeps blinking and
    # notices the page going away even when no HTTP requests arrive.
    srv.settimeout(ACCEPT_TIMEOUT)
    print("HTTP server listening on %s:%d (%s)" % (host, port, info))

    try:
        while True:
            if led:
                led.update()
            try:
                cl, remote = srv.accept()
            except OSError:
                continue  # accept timed out -- loop round to refresh the LED
            cl.settimeout(CLIENT_TIMEOUT)
            try:
                _handle(cl)
            except OSError as e:
                # client went away / timed out -- just drop it
                print("client %s: %r" % (remote[0], e))
            except Exception as e:
                print("request error: %r" % e)
                try:
                    _send_json(cl, 500, {"ok": False, "log": ["Internal error: %r" % e]})
                except OSError:
                    pass
            finally:
                cl.close()
    finally:
        srv.close()
