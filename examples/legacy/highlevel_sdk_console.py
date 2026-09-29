#!/usr/bin/env python3
"""Interactive HighLevel SDK console for manual action testing.

The console keeps one control lease alive, so starting an action, changing its
parameters, and stopping it are three independent operations.  No action is
started automatically.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from typing import Any, Optional

import robot_motion_sdk as sdk


_stopping = False


def on_signal(_signum: int, _frame: Any) -> None:
    global _stopping
    _stopping = True


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def wait_for_state(client: sdk.MotionHighLevelClient, expected: Any, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _stopping:
        if client.get_state() == expected:
            return True
        time.sleep(0.05)
    return client.get_state() == expected


def wait_for_rpc_discovery(client: sdk.MotionHighLevelClient, timeout_s: float) -> Optional[dict]:
    deadline = time.monotonic() + timeout_s
    while not _stopping:
        result = client.get_motion_capabilities()
        if result is not None:
            return result
        if client.get_last_error() != sdk.HighLevelError.kRpcConnectFailed:
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)
    return None


def parse_json_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("parameters must be a JSON object")
    return value


def sleep_interruptibly(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline and not _stopping:
        time.sleep(min(0.1, deadline - time.monotonic()))


def print_help() -> None:
    print(
        """commands:
  start ACTION [JSON]  start an action; params are optional
  send SECONDS JSON    set current-action params, hold for SECONDS, then clear params
  set JSON             set params and keep them until the next set/send/zero/stop
  zero                 clear all current-action params; does not stop the action
  stop                 call stop_action; only this command stops the action
  state                query current motion state
  caps                 print motion capabilities
  help                 show this help
  quit                 release control and exit

examples:
  start walking
  send 3 {"lineVelocityX":0.1,"lineVelocityY":0,"velocity":0}
  set {"velocity":0.2}
  zero
  stop
"""
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iface", default="eth0")
    parser.add_argument("--client-id", default="orin-highlevel-sdk-console")
    parser.add_argument("--lease-ms", type=int, default=15000)
    parser.add_argument("--discovery-timeout", type=float, default=10.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    sdk.service.set_network_interface(args.iface)
    if not sdk.service.initial(None, args.client_id):
        print("[FAIL] sdk.service.initial", file=sys.stderr)
        return 1

    client = sdk.MotionHighLevelClient()
    acquired = False
    action_active = False
    try:
        @client.on_connect
        def on_connect(state: sdk.HighLevelState, error: sdk.HighLevelError) -> None:
            print(f"[callback] state={state} error={error}")

        if not client.connect(lease_ms=args.lease_ms):
            print(f"[FAIL] connect error={client.get_last_error()}", file=sys.stderr)
            return 1
        capabilities = wait_for_rpc_discovery(client, args.discovery_timeout)
        if capabilities is None:
            print(f"[FAIL] RPC discovery error={client.get_last_error()}", file=sys.stderr)
            return 1
        if not client.start_control(timeout_ms=10000):
            print(f"[FAIL] start_control error={client.get_last_error()}", file=sys.stderr)
            return 1
        if not wait_for_state(client, sdk.HighLevelState.kControlled, 10.0):
            print(f"[FAIL] control state={client.get_state()} error={client.get_last_error()}", file=sys.stderr)
            return 1
        acquired = True
        print("[PASS] control acquired with cmdMode=true; no action has been started")
        print_help()

        while not _stopping:
            try:
                line = input("highlevel> ").strip()
            except EOFError:
                break
            if not line:
                continue
            command, _, rest = line.partition(" ")
            command = command.lower()
            rest = rest.strip()
            try:
                if command in ("quit", "exit"):
                    break
                if command == "help":
                    print_help()
                elif command == "caps":
                    print(pretty(capabilities))
                elif command == "state":
                    state = client.query_motion_state()
                    print(pretty(state) if state is not None else f"[FAIL] {client.get_last_error()}")
                elif command == "start":
                    parts = rest.split(maxsplit=1)
                    if not parts:
                        raise ValueError("usage: start ACTION [JSON]")
                    action = parts[0]
                    params = parse_json_object(parts[1]) if len(parts) == 2 else None
                    if not client.start_action(action, params):
                        print(f"[FAIL] start_action error={client.get_last_error()}")
                    else:
                        action_active = True
                        print(f"[PASS] started {action}")
                elif command == "set":
                    if not rest:
                        raise ValueError("usage: set JSON")
                    if not client.set_action_params(parse_json_object(rest)):
                        print(f"[FAIL] set_action_params error={client.get_last_error()}")
                    else:
                        print("[PASS] params set; command remains active")
                elif command == "send":
                    duration_raw, separator, params_raw = rest.partition(" ")
                    if not separator:
                        raise ValueError("usage: send SECONDS JSON")
                    duration = float(duration_raw)
                    if duration < 0:
                        raise ValueError("SECONDS must be non-negative")
                    params = parse_json_object(params_raw.strip())
                    if not client.set_action_params(params):
                        print(f"[FAIL] set_action_params error={client.get_last_error()}")
                        continue
                    print(f"[PASS] command active for {duration:g}s")
                    sleep_interruptibly(duration)
                    if not client.set_action_params({}):
                        print(f"[FAIL] timed command clear error={client.get_last_error()}")
                    else:
                        print("[PASS] command cleared; current action is still running")
                elif command == "zero":
                    if not client.set_action_params({}):
                        print(f"[FAIL] zero error={client.get_last_error()}")
                    else:
                        print("[PASS] command cleared; current action is still running")
                elif command == "stop":
                    if not client.stop_action():
                        print(f"[FAIL] stop_action error={client.get_last_error()}")
                    else:
                        action_active = False
                        print("[PASS] stop_action accepted")
                else:
                    print(f"unknown command: {command!r}; type help")
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"[INPUT ERROR] {exc}")

        return 0
    finally:
        if acquired and action_active:
            try:
                if client.set_action_params({}):
                    print("[cleanup] action params cleared")
                else:
                    print(f"[WARN] command clear rejected: {client.get_last_error()}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] command clear failed: {exc}", file=sys.stderr)
        if acquired:
            try:
                client.release_control()
                print("[cleanup] control released")
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] release failed: {exc}", file=sys.stderr)
        try:
            client.disconnect()
        finally:
            sdk.service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
