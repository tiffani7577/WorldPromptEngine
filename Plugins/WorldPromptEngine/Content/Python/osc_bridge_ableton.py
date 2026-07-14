#!/usr/bin/env python3
"""
osc_bridge_ableton.py — Ableton -> Unreal OSC translator.

Runs OUTSIDE Unreal, on the machine running Ableton Live (or a second
machine on the same LAN). Listens on port 9000 for a Max for Live /
LiveOSC device sending analysis data, translates addresses, and forwards
to Unreal's WorldPromptEngine performance receiver on port 8000.

Incoming (port 9000)        Outgoing (port 8000, host --unreal-host)
/ableton/energy  f 0-1  ->  /music/energy
/ableton/bass    f 0-1  ->  /music/bass
/ableton/mids    f 0-1  ->  /music/mids
/ableton/highs   f 0-1  ->  /music/highs
/ableton/kick    f 0|1  ->  /music/kick
/ableton/vocal   f 0-1  ->  /music/vocal
/ableton/scene   i n    ->  /scene/{n}   (n == -1 -> /scene/next)

Requires: pip install python-osc
Usage:    python3 osc_bridge_ableton.py [--unreal-host 127.0.0.1]
"""

import argparse
import sys
import threading
import time

try:
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import ThreadingOSCUDPServer
    from pythonosc.udp_client import SimpleUDPClient
except ImportError:
    print("python-osc is required:  pip install python-osc")
    sys.exit(1)

LISTEN_PORT = 9000
UNREAL_PORT = 8000

PARAM_MAP = {
    "/ableton/energy": "/music/energy",
    "/ableton/bass": "/music/bass",
    "/ableton/mids": "/music/mids",
    "/ableton/highs": "/music/highs",
    "/ableton/kick": "/music/kick",
    "/ableton/vocal": "/music/vocal",
}

STATUS = {
    "received": {},     # in-address -> last value
    "forwarded": {},    # out-address -> last value
    "count_in": 0,
    "count_out": 0,
    "errors": 0,
    "last_error": "",
}
_LOCK = threading.Lock()


class ReconnectingClient(object):
    """UDP client with lazy (re)creation on send failure."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.client = None

    def _ensure(self):
        if self.client is None:
            self.client = SimpleUDPClient(self.host, self.port)

    def send(self, address, value):
        for attempt in range(2):
            try:
                self._ensure()
                self.client.send_message(address, value)
                return True
            except Exception as e:
                self.client = None
                with _LOCK:
                    STATUS["errors"] += 1
                    STATUS["last_error"] = "{}: {}".format(address, e)
                if attempt == 0:
                    time.sleep(0.05)
        return False


def make_handler(client):
    def handler(address, *args):
        try:
            value = float(args[0]) if args else 1.0
        except (TypeError, ValueError):
            value = 1.0
        with _LOCK:
            STATUS["count_in"] += 1
            STATUS["received"][address] = value

        out_addr = None
        out_val = value
        if address in PARAM_MAP:
            out_addr = PARAM_MAP[address]
            out_val = max(0.0, min(1.0, value))
        elif address == "/ableton/scene":
            n = int(value)
            out_addr = "/scene/next" if n < 0 else "/scene/{}".format(n)
            out_val = 1.0

        if out_addr is not None and client.send(out_addr, out_val):
            with _LOCK:
                STATUS["count_out"] += 1
                STATUS["forwarded"][out_addr] = out_val
    return handler


def status_loop():
    while True:
        time.sleep(1.0)
        try:
            with _LOCK:
                rec = " ".join("{}={:.2f}".format(k.split("/")[-1], v)
                               for k, v in sorted(STATUS["received"].items()))
                line = "in:{:>6}  out:{:>6}  err:{:>3}  {}".format(
                    STATUS["count_in"], STATUS["count_out"], STATUS["errors"], rec)
                if STATUS["last_error"]:
                    line += "  last_err: " + STATUS["last_error"][:60]
            sys.stdout.write("\r" + line[:140].ljust(140))
            sys.stdout.flush()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Ableton -> Unreal OSC bridge")
    parser.add_argument("--unreal-host", default="127.0.0.1")
    parser.add_argument("--unreal-port", type=int, default=UNREAL_PORT)
    parser.add_argument("--listen-port", type=int, default=LISTEN_PORT)
    args = parser.parse_args()

    client = ReconnectingClient(args.unreal_host, args.unreal_port)
    dispatcher = Dispatcher()
    dispatcher.set_default_handler(make_handler(client))

    while True:
        try:
            server = ThreadingOSCUDPServer(("0.0.0.0", args.listen_port), dispatcher)
            print("WorldPromptEngine OSC bridge")
            print("  listening : 0.0.0.0:{}".format(args.listen_port))
            print("  forwarding: {}:{}".format(args.unreal_host, args.unreal_port))
            threading.Thread(target=status_loop, daemon=True).start()
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")
            return
        except Exception as e:
            print("\nserver error: {} — retrying in 2s".format(e))
            time.sleep(2.0)


if __name__ == "__main__":
    main()
