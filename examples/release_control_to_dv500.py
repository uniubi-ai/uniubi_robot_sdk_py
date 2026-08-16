#!/usr/bin/env python3
"""Restore built-in/DV500 motion control from a dedicated SDK process."""

from __future__ import annotations

import argparse
import signal
import threading
import time

import robot_motion_sdk as sdk


_stopping = False


def _on_signal(signum, frame) -> None:
    del signum, frame
    global _stopping
    _stopping = True


def _enum_name(value) -> str:
    return getattr(value, "name", str(value))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release Low-level control and restore built-in/DV500 motion control.",
    )
    parser.add_argument("--client-id", default="releaseControlToDv500")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--disable-timeout", type=float, default=8.0)
    parser.add_argument("--restore-timeout-ms", type=int, default=5000)
    parser.add_argument("--observed-hz", type=int, default=50)
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    if not sdk.service.initial(None, args.client_id):
        print("[FAIL] SDK init failed", flush=True)
        return 1

    client = sdk.MotionLowLevelClient()
    state_event = threading.Event()

    @client.on_connect
    def _on_connect(state: sdk.LowLevelState, error: sdk.LowLevelError) -> None:
        print(
            f"[state] state={_enum_name(state)} error={_enum_name(error)}",
            flush=True,
        )
        state_event.set()

    def wait_for_state(targets: set[sdk.LowLevelState], timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while not _stopping and time.monotonic() < deadline:
            if client.get_state() in targets:
                return True
            state_event.clear()
            state_event.wait(max(0.05, min(0.5, deadline - time.monotonic())))
        return client.get_state() in targets

    try:
        if not client.connect(observed_hz=args.observed_hz, lease_ms=0):
            print(f"[FAIL] connect rejected: {_enum_name(client.get_last_error())}", flush=True)
            return 1

        ready = {sdk.LowLevelState.kConnected, sdk.LowLevelState.kPrepared}
        if not wait_for_state(ready, args.connect_timeout):
            print(
                f"[FAIL] connect timeout: state={_enum_name(client.get_state())} "
                f"error={_enum_name(client.get_last_error())}",
                flush=True,
            )
            return 1

        if client.get_state() == sdk.LowLevelState.kPrepared:
            if not client.set_motion_enable(False):
                print(
                    f"[FAIL] disable rejected: {_enum_name(client.get_last_error())}",
                    flush=True,
                )
                return 1
            if not wait_for_state({sdk.LowLevelState.kConnected}, args.disable_timeout):
                print(
                    f"[FAIL] disable timeout: state={_enum_name(client.get_state())} "
                    f"error={_enum_name(client.get_last_error())}",
                    flush=True,
                )
                return 1

        if _stopping:
            return 130
        if not client.restore_motion_control_mode(args.restore_timeout_ms):
            print(
                f"[FAIL] restore failed: {_enum_name(client.get_last_error())}",
                flush=True,
            )
            return 1

        print("[PASS] built-in/DV500 motion control restored", flush=True)
        return 0
    finally:
        client.disconnect()
        sdk.service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
