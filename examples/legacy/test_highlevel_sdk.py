#!/usr/bin/env python3
"""HighLevel Python SDK smoke test.

The default path never calls an action API.  It only connects, performs
read-only queries, briefly acquires/renews the control lease, and releases it.
An action is sent only when both --allow-motion and the exact confirmation
token are supplied.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from typing import Any, Optional

import robot_motion_sdk as sdk


MOTION_CONFIRMATION = "I_UNDERSTAND_THE_ROBOT_WILL_MOVE"
_stopping = False


def on_signal(_signum: int, _frame: Any) -> None:
    global _stopping
    _stopping = True


def pretty(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return repr(value)


def wait_for_state(client: sdk.MotionHighLevelClient, expected: Any, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _stopping:
        if client.get_state() == expected:
            return True
        time.sleep(0.05)
    return client.get_state() == expected


def call_after_discovery(
    client: sdk.MotionHighLevelClient,
    call: Any,
    timeout_s: float,
) -> Any:
    """Retry only while DDS has not discovered the RPC endpoint yet."""
    deadline = time.monotonic() + timeout_s
    while not _stopping:
        result = call()
        if result is not None:
            return result
        if client.get_last_error() != sdk.HighLevelError.kRpcConnectFailed:
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)
    return None


def parse_action_params(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--params must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iface", default="eth0", help="DDS network interface")
    parser.add_argument("--client-id", default="orin-highlevel-sdk-test")
    parser.add_argument("--lease-ms", type=int, default=15000)
    parser.add_argument("--discovery-timeout", type=float, default=10.0)
    parser.add_argument("--skip-control", action="store_true", help="run read-only queries only")
    parser.add_argument("--allow-motion", action="store_true", help="allow one start_action call")
    parser.add_argument("--confirm", default="", help=f"must equal {MOTION_CONFIRMATION!r}")
    parser.add_argument("--action", default="standing", help="action sent in motion mode")
    parser.add_argument("--params", help="action params as a JSON object")
    parser.add_argument("--observe-seconds", type=float, default=3.0)
    parser.add_argument(
        "--stop-action",
        action="store_true",
        help="call stop_action after observing the started action",
    )
    parser.add_argument("--stop-observe-seconds", type=float, default=2.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.allow_motion and args.confirm != MOTION_CONFIRMATION:
        print(f"Refusing motion: pass --confirm {MOTION_CONFIRMATION}", file=sys.stderr)
        return 2

    try:
        action_params = parse_action_params(args.params)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Invalid action params: {exc}", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    sdk.service.set_network_interface(args.iface)
    if not sdk.service.initial(None, args.client_id):
        print("[FAIL] sdk.service.initial")
        return 1

    client = sdk.MotionHighLevelClient()
    acquired = False
    try:
        @client.on_connect
        def on_connect(state: sdk.HighLevelState, error: sdk.HighLevelError) -> None:
            print(f"[callback] state={state} error={error}")

        if not client.connect(lease_ms=args.lease_ms):
            print(f"[FAIL] connect error={client.get_last_error()}")
            return 1
        print(f"[PASS] connected state={client.get_state()} sdk={sdk.version()}")

        checks = (
            ("get_motion_capabilities", client.get_motion_capabilities),
            ("query_motion_state", client.query_motion_state),
            ("query_system_status", client.query_system_status),
        )
        for name, call in checks:
            result = call_after_discovery(client, call, args.discovery_timeout)
            if result is None:
                print(f"[FAIL] {name} error={client.get_last_error()}")
                return 1
            summary = list(result.keys()) if isinstance(result, dict) else result
            print(f"[PASS] {name}: {pretty(summary)}")

        layout = client.get_motor_layout()
        print(f"[{'PASS' if layout is not None else 'WARN'}] get_motor_layout: {layout}")

        if args.skip_control:
            print("[PASS] read-only SDK test complete; control lease was not acquired")
            return 0

        if not client.start_control(timeout_ms=10000):
            print(f"[FAIL] start_control request error={client.get_last_error()}")
            return 1
        if not wait_for_state(client, sdk.HighLevelState.kControlled, 10.0):
            print(f"[FAIL] control not acquired state={client.get_state()} error={client.get_last_error()}")
            return 1
        acquired = True
        print("[PASS] control acquired with SDK default cmdMode=true; no action sent")

        state = client.query_motion_state()
        if state is None:
            print(f"[FAIL] query_motion_state while controlled error={client.get_last_error()}")
            return 1
        print(f"[PASS] controlled query_motion_state: {pretty(state)}")

        if args.allow_motion:
            print(f"[MOTION] start_action action={args.action!r} params={pretty(action_params)}")
            if not client.start_action(args.action, action_params):
                print(f"[FAIL] start_action error={client.get_last_error()}")
                return 1
            deadline = time.monotonic() + max(0.0, args.observe_seconds)
            while time.monotonic() < deadline and not _stopping:
                time.sleep(0.1)
            if args.action == "walking":
                zero = {"lineVelocityX": 0.0, "lineVelocityY": 0.0, "velocity": 0.0}
                if not client.set_action_params(zero):
                    print(f"[FAIL] walking zero command error={client.get_last_error()}")
                    return 1
                print("[PASS] walking zero command sent")
                time.sleep(1.0)
            print(f"[PASS] action accepted; state={pretty(client.query_motion_state())}")
            if args.stop_action:
                print("[MOTION] stop_action")
                if not client.stop_action():
                    print(f"[FAIL] stop_action error={client.get_last_error()}")
                    return 1
                deadline = time.monotonic() + max(0.0, args.stop_observe_seconds)
                while time.monotonic() < deadline and not _stopping:
                    time.sleep(0.1)
                print(f"[PASS] stop_action accepted; state={pretty(client.query_motion_state())}")

        if not client.release_control():
            print(f"[FAIL] release_control error={client.get_last_error()}")
            return 1
        acquired = False
        if not wait_for_state(client, sdk.HighLevelState.kConnected, 3.0):
            print(f"[WARN] release callback pending, state={client.get_state()}")
        print("[PASS] SDK HighLevel smoke test complete")
        return 0
    finally:
        if acquired:
            try:
                client.release_control()
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] release during cleanup: {exc}")
        try:
            client.disconnect()
        finally:
            sdk.service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
