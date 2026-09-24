#!/usr/bin/env python3
"""
Launch the DM-J4340-2EC motor web UI.

This is a LOCAL tool: it must run on the same machine that has the
SocketCAN interface, because a browser cannot talk to CAN hardware
directly. It opens the bus once and serves motor_web's Flask app over
HTTP. There is no authentication -- do not expose --host beyond
127.0.0.1 on an untrusted network.

Usage:
    python3 main.py --channel can0 --port 8000
    # then open http://127.0.0.1:8000 in a browser on this machine
"""

import argparse

import can

from motor_web import app, state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", default="can0", help="SocketCAN interface name (default: can0)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1, local-only)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    args = parser.parse_args()

    state["channel"] = args.channel
    state["bus"] = can.interface.Bus(channel=args.channel, interface="socketcan")
    try:
        print(f"Motor web UI: http://{args.host}:{args.port}  (channel={args.channel})")
        app.run(host=args.host, port=args.port, debug=False)
    finally:
        state["bus"].shutdown()


if __name__ == "__main__":
    main()
