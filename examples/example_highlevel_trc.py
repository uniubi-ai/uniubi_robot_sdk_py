"""Read High-level TRC observations without acquiring control.
Usage: python3 example_highlevel_trc.py [IFACE] [DEVICE_ID|-] [SECONDS]
"""
import argparse
import signal
import sys
import time

import robot_motion_sdk as sdk

BUTTONS = ("Back", "Start", "LB", "RB", "F1", "F2", "A", "B",
           "X", "Y", "Up", "Down", "Left", "Right", "LS", "RS")
AXES = ("LX", "LY", "RX", "RY", "LT", "RT")
stopping = False


def stop(_signum, _frame):
    global stopping
    stopping = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iface", nargs="?", default="eth0.100")
    parser.add_argument("device_id", nargs="?", default="-")
    parser.add_argument("seconds", nargs="?", type=int, default=60)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("SECONDS must be positive")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    sdk.service.set_network_interface(args.iface)
    if not sdk.service.initial(None, "highlevel-trc-example"):
        return 1
    client = None
    attempted = False
    previous = None
    count = 0
    status = 0

    def on_motion(obs):
        nonlocal previous, count
        count += 1
        trc = obs.trc
        now = (bool(trc.valid), list(trc.buttons), list(trc.axes))
        if not now[0]:
            if previous is None or previous[0]:
                print("TRC invalid; waiting for valid input", flush=True)
            previous = now
            return
        if previous is None or not previous[0]:
            # First valid sample is a baseline, not a newly pressed key.
            print("TRC baseline: buttons=%s axes=%s" % (now[1], now[2]), flush=True)
            previous = now
            return
        for i, name in enumerate(BUTTONS):
            if bool(now[1][i]) != bool(previous[1][i]):
                print("%s %s" % (name, "pressed" if now[1][i] else "released"), flush=True)
        for i, name in enumerate(AXES):
            if abs(now[2][i] - previous[2][i]) >= 0.02:
                print("%s %.3f" % (name, now[2][i]), flush=True)
                previous[2][i] = now[2][i]
        previous = (True, now[1], previous[2])

    try:
        if sdk.service.is_multi_device() and args.device_id == "-":
            raise RuntimeError("External hosts require DEVICE_ID (robot SN)")
        client = sdk.MotionHighLevelClient(device_id="" if args.device_id == "-" else args.device_id)
        client.set_motion_observed_callback(on_motion)
        if not client.connect(lease_ms=60000):
            raise RuntimeError("connect failed")
        deadline = time.monotonic() + 15
        while not stopping:
            if client.get_motion_capabilities() is not None:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("device discovery timed out")
            time.sleep(0.1)
        if not stopping:
            attempted = True
            if client.set_observed_enable({"motionEnable": True, "trcEnable": True}) is None:
                raise RuntimeError("enable observations failed")
            print("Ready: observing for %d seconds; Ctrl+C to exit" % args.seconds, flush=True)
            deadline = time.monotonic() + args.seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(0.1)
    except Exception as error:
        print(error, file=sys.stderr)
        status = 1
    finally:
        try:
            if client is not None:
                try:
                    if attempted and client.set_observed_enable({"motionEnable": False, "trcEnable": False}) is None:
                        print("Failed to disable observations", file=sys.stderr)
                        status = 1
                finally:
                    client.disconnect()
        finally:
            sdk.service.shutdown()
    print("Observation callbacks:", count)
    if attempted and count == 0:
        print("No observations received", file=sys.stderr)
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
