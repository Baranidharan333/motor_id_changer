#!/usr/bin/env python3
"""
Flask app for the DM-J4340-2EC motor scanner / CAN id (ESC_ID) and
feedback id (MST_ID) configurator web UI.

This is a LOCAL tool: it must run on the same machine that has the
SocketCAN interface, because a browser cannot talk to CAN hardware
directly. It drives the bus once (opened by main.py) and serves a small
page that operates it over HTTP. There is no authentication -- do not
expose --host beyond 127.0.0.1 on an untrusted network.

Run via main.py; this module only defines the Flask app and routes.
"""

import logging
import threading

from flask import Flask, jsonify, request

import can

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

logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__, static_folder="static", static_url_path="")
bus_lock = threading.Lock()
state = {"bus": None, "channel": "can0"}


@app.errorhandler(can.CanOperationError)
def handle_can_error(e):
    return jsonify({
        "ok": False,
        "log": [f"CAN send failed: {e}",
                "Bus may be error-passive/bus-off -- check termination, wiring, and bitrate "
                "(run `ip -details -statistics link show <channel>` to inspect error counters)."],
    }), 503


def motor_info_json(motor_id: int, info):
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


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/status")
def api_status():
    return jsonify({"channel": state["channel"]})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    body = request.get_json(force=True) or {}
    start = int(body.get("start", 1))
    end = int(body.get("end", 16))
    timeout = float(body.get("timeout", 0.5))
    with bus_lock:
        found = scan_for_motors(state["bus"], start, end, timeout)
    motors = [
        {"id": motor_id, "info": motor_info_json(motor_id, info)}
        for motor_id, info in sorted(found.items())
    ]
    return jsonify({"motors": motors})


@app.route("/api/probe", methods=["POST"])
def api_probe():
    body = request.get_json(force=True) or {}
    motor_id = int(body["id"])
    timeout = float(body.get("timeout", 0.3))
    with bus_lock:
        info = probe_motor(state["bus"], motor_id, timeout)
    return jsonify({"id": motor_id, "info": motor_info_json(motor_id, info)})


@app.route("/api/set_id", methods=["POST"])
def api_set_id():
    body = request.get_json(force=True) or {}
    current_id = int(body["current_id"])
    new_can_id = body.get("new_can_id")
    new_feedback_id = body.get("new_feedback_id")
    new_can_id = int(new_can_id) if new_can_id not in (None, "") else None
    new_feedback_id = int(new_feedback_id) if new_feedback_id not in (None, "") else None
    retries = int(body.get("retries", 10))
    reg_timeout = float(body.get("reg_timeout", 0.1))

    if new_can_id is None and new_feedback_id is None:
        return jsonify({"ok": False, "log": ["Nothing to do -- no new ids given."]}), 400

    log = []
    with bus_lock:
        bus = state["bus"]
        flush_bus(bus)
        disable(bus, current_id)
        active_id = current_id
        ok = True

        if new_feedback_id is not None:
            log.append(f"Writing feedback id = {new_feedback_id} ...")
            success = write_register(bus, active_id, REG_MST_ID, new_feedback_id, retries=retries, timeout=reg_timeout)
            log.append("  verified." if success else "  FAILED to verify -- aborting before save.")
            ok = ok and success

        if ok and new_can_id is not None:
            log.append(f"Writing CAN id = {new_can_id} ...")
            success = write_register(bus, active_id, REG_ESC_ID, new_can_id, retries=retries, timeout=reg_timeout)
            log.append("  verified." if success else "  FAILED to verify -- aborting before save.")
            ok = ok and success
            if success:
                active_id = new_can_id

        if ok:
            log.append(f"Saving to flash (addressing motor at CAN id {active_id}) ...")
            save_to_flash(bus, active_id)
            log.append("Done. Power-cycle the motor to confirm the new id(s) stick.")
        else:
            log.append("Nothing persisted -- power-cycle the motor if unsure of its state.")

    return jsonify({"ok": ok, "active_id": active_id, "log": log})


@app.route("/api/zero", methods=["POST"])
def api_zero():
    body = request.get_json(force=True) or {}
    motor_id = int(body["id"])
    with bus_lock:
        set_zero_position(state["bus"], motor_id)
    return jsonify({"ok": True, "log": [f"CAN id {motor_id}: zero position set."]})


@app.route("/api/zero_all", methods=["POST"])
def api_zero_all():
    body = request.get_json(force=True) or {}
    ids = [int(i) for i in body.get("ids", [])]
    log = []
    with bus_lock:
        bus = state["bus"]
        for motor_id in ids:
            set_zero_position(bus, motor_id)
            log.append(f"CAN id {motor_id}: zero position set.")
    log.append(f"Done -- zeroed {len(ids)} motor(s).")
    return jsonify({"ok": True, "log": log})
