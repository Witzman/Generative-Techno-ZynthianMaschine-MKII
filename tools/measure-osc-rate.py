#!/usr/bin/env python3
"""Count the driver's OSC writes to the daemon, on the Pi, with nobody at the rig.

Run this ON the Pi. It needs root, because it reads raw frames off `lo`.

    tools/measure-osc-rate.py 6            # six seconds of idle
    tools/measure-osc-rate.py 14 --json    # machine-readable

Why a sniffer at all: **the daemon is write-only for LEDs and has no readback**,
so the only way to see what the driver paints is to watch the wire. Everything
the driver sends the surface - every pad, every button LED, every screen packet -
goes to 127.0.0.1:42434 as OSC over UDP, so counting those packets measures the
surface traffic exactly. Per `notes/traps/TESTING.md`.

Two numbers come out, and the SECOND one is usually the interesting one:

  total/s    the sustained rate. The write budget measured 2026-08-22 is ~50/s
             free, ~110/s about double the stall rate, ~160/s fatal - and the
             driver's own idle is ~11-13/s.
  peak       the busiest single second. A full-surface repaint is a BURST, not
             a rate: on 2026-08-30 a replug produced 248 in one second against
             an idle peak of 34, then settled straight back. That shape - one
             spike, then the old baseline - is what distinguishes a heal that
             fires once from a periodic writer that will wedge the controller.

Worked example, the replug heal (`_check_device`). In one shell:

    tools/measure-osc-rate.py 14

and in another, while it runs, move the device node:

    echo 0 > /sys/bus/usb/devices/1-1.4/authorized
    sleep 2
    echo 1 > /sys/bus/usb/devices/1-1.4/authorized

Expect one peak second in the low hundreds and a return to the idle rate.

**A forced re-enumeration is NOT a replug.** It moves the device node, which is
all this particular heal keys on, so it is a fair test of the repaint - but it
does NOT clear a wedged endpoint, measured twice on 2026-08-30. Do not run it
unattended expecting to recover a dead controller; only hands do that.
"""

import argparse
import json
import socket
import struct
import time

OSC_PORT = 42434
ETH_HEADER = 14
ETH_P_IPV4 = 0x0800
IPPROTO_UDP = 17


def count(seconds, port=OSC_PORT, iface="lo"):
    """Frames to `port` on `iface`, bucketed by whole second."""

    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    sock.bind((iface, 0))
    # Short, so the deadline is honoured even on a completely silent wire.
    sock.settimeout(0.2)

    buckets = {}
    total = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            frame = sock.recv(65535)
        except socket.timeout:
            continue
        # Shortest frame that could carry a UDP header: eth + minimal IP + UDP.
        if len(frame) < ETH_HEADER + 20 + 8:
            continue
        if struct.unpack("!H", frame[12:14])[0] != ETH_P_IPV4:
            continue
        ihl = (frame[ETH_HEADER] & 0x0F) * 4
        if frame[ETH_HEADER + 9] != IPPROTO_UDP:
            continue
        udp = ETH_HEADER + ihl
        if struct.unpack("!H", frame[udp + 2:udp + 4])[0] != port:
            continue
        total += 1
        second = int(time.monotonic())
        buckets[second] = buckets.get(second, 0) + 1

    return total, buckets


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seconds", nargs="?", type=float, default=6.0,
                    help="how long to watch (default 6)")
    ap.add_argument("--port", type=int, default=OSC_PORT,
                    help=f"UDP port to count (default {OSC_PORT})")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    total, buckets = count(args.seconds, args.port)
    peak = max(buckets.values()) if buckets else 0
    rate = total / args.seconds if args.seconds else 0.0

    if args.json:
        print(json.dumps({"total": total, "seconds": args.seconds,
                          "rate": round(rate, 2), "peak": peak}))
        return
    print(f"total={total} over {args.seconds}s = {rate:.1f}/s")
    print(f"peak second={peak}")


if __name__ == "__main__":
    main()
