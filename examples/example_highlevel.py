#!/usr/bin/env python3
"""Interactive High-level SDK CLI. No motion action starts automatically."""

from __future__ import annotations

import argparse
import json
import select
import signal
import sys
import threading
import time
from typing import Any, Optional

import robot_motion_sdk as sdk


STOP_VELOCITY = {
    "lineVelocityX": 0.0,
    "lineVelocityY": 0.0,
    "velocity": 0.0,
}
_stopping = False


def on_signal(_signum: int, _frame: Any) -> None:
    global _stopping
    _stopping = True


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def parse_json_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("parameters must be a JSON object")
    return value


def wait_for_state(client: sdk.MotionHighLevelClient, expected: Any, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _stopping:
        if client.get_state() == expected:
            return True
        time.sleep(0.05)
    return client.get_state() == expected


def wait_for_rpc_discovery(
    client: sdk.MotionHighLevelClient, timeout_s: float
) -> Optional[dict[str, Any]]:
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


def sleep_interruptibly(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline and not _stopping:
        time.sleep(min(0.1, deadline - time.monotonic()))


def read_command(prompt: str) -> Optional[str]:
    print(prompt, end="", flush=True)
    while not _stopping:
        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if readable:
            line = sys.stdin.readline()
            return line.strip() if line else None
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iface",
        default="eth0.100",
        help="DDS network interface (board default: eth0.100; external: pass the actual interface)",
    )
    parser.add_argument("--client-id", default="uniubi-python-highlevel-cli")
    parser.add_argument(
        "--device-id",
        default="",
        help="target robot SN (required on external hosts and when SDK reports multi-device)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="list discovered robots before connecting; never selects one automatically",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="list discovered robots and exit without creating a client",
    )
    parser.add_argument("--lease-ms", type=int, default=60000)
    parser.add_argument("--discovery-timeout", type=float, default=10.0)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="connect without acquiring High-level control",
    )
    return parser


class DeviceDiscovery:
    """Collect asynchronous discovery replies, de-duplicated by robot SN."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._callback_count = 0
        self._devices: dict[str, str] = {}

    def callback(self, sn: str, info_json: str) -> None:
        with self._condition:
            self._callback_count += 1
            self._devices[sn] = info_json
            self._condition.notify_all()

    def discover(self) -> dict[str, str]:
        for attempt in range(2):
            with self._condition:
                callbacks_before = self._callback_count
            if not sdk.service.discover_devices(timeout_ms=5000):
                raise RuntimeError("discover_devices failed")

            deadline = time.monotonic() + 5.0
            with self._condition:
                while not _stopping:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        break
                    self._condition.wait(timeout=remaining)
                received = self._callback_count > callbacks_before

            if received or _stopping:
                break
            if attempt == 0:
                print("[WARN] no discovery callback in 5s; retrying once")

        with self._condition:
            return dict(self._devices)


def print_discovered_devices(devices: dict[str, str]) -> None:
    if not devices:
        print("[WARN] no robots discovered")
        return
    print(f"[INFO] discovered {len(devices)} robot(s):")
    for sn in sorted(devices):
        try:
            info: Any = json.loads(devices[sn])
        except (json.JSONDecodeError, TypeError):
            info = devices[sn]
        print(f"  SN={sn} info={json.dumps(info, ensure_ascii=False, default=str)}")


class HighLevelConsole:
    def __init__(self, client: sdk.MotionHighLevelClient) -> None:
        self.client = client
        self.capabilities: Optional[dict[str, Any]] = None
        self.controlled = False
        self.action_active = False
        self._sensor_lock = threading.Lock()
        self._latest_sensor: Any = None
        self._sensor_frames = 0

        @client.on_connect
        def on_connect(state: sdk.HighLevelState, error: sdk.HighLevelError) -> None:
            if state == sdk.HighLevelState.kControlled:
                print("\n[INFO] High-level control acquired")
            elif state == sdk.HighLevelState.kConnected and error != sdk.HighLevelError.kNone:
                print(f"\n[WARN] control lost, error={error}")

        @client.on_event
        def on_event(topic: str, payload_json: str) -> None:
            if topic == "control.status":
                print(f"\n[EVENT] {topic}: {payload_json}")

        def on_sensor(sensor: Any) -> None:
            with self._sensor_lock:
                self._latest_sensor = sensor
                self._sensor_frames += 1

        client.set_sensor_observed_callback(on_sensor)

    def connect(self, lease_ms: int, discovery_timeout: float, read_only: bool) -> None:
        if not self.client.connect(lease_ms=lease_ms):
            self.fail("connect")
        self.capabilities = wait_for_rpc_discovery(self.client, discovery_timeout)
        if self.capabilities is None:
            self.fail("get_motion_capabilities discovery")
        print("[PASS] connected; no action has been started")

        observed = self.client.set_observed_enable(
            {"motionEnable": False, "sensorEnable": True}
        )
        if observed is None:
            print(f"[WARN] enable SensorObserved failed, error={self.client.get_last_error()}")

        if read_only:
            print("[INFO] read-only mode; use 'take' before control commands")
        else:
            self.take_control()

    def take_control(self) -> None:
        if self.client.get_state() == sdk.HighLevelState.kControlled:
            self.controlled = True
            print("[INFO] control is already held")
            return
        if not self.client.start_control(timeout_ms=10000):
            self.print_failure("take control")
            return
        if not wait_for_state(self.client, sdk.HighLevelState.kControlled, 10.0):
            self.print_failure("wait controlled")
            return
        self.controlled = True
        print("[PASS] control acquired; no action has been started")

    def release_control(self) -> None:
        if self.client.get_state() != sdk.HighLevelState.kControlled:
            self.controlled = False
            return
        if self.action_active:
            if self.client.set_action_params(STOP_VELOCITY):
                print("[cleanup] walking velocity cleared before release")
            else:
                print(
                    f"[WARN] velocity clear before release failed, "
                    f"error={self.client.get_last_error()}",
                    file=sys.stderr,
                )
            self.action_active = False
        if not self.client.release_control():
            self.print_failure("release control")
            return
        wait_for_state(self.client, sdk.HighLevelState.kConnected, 3.0)
        self.controlled = False
        print("[PASS] control released")

    def require_control(self) -> bool:
        if self.client.get_state() == sdk.HighLevelState.kControlled:
            self.controlled = True
            return True
        self.controlled = False
        print("[FAIL] High-level control is not held; run 'take' first")
        return False

    def run(self) -> None:
        self.print_help()
        while not _stopping:
            line = read_command("highlevel> ")
            if line is None:
                break
            if not line:
                continue
            try:
                if not self.execute(line):
                    break
            except (ValueError, json.JSONDecodeError) as error:
                print(f"[INPUT ERROR] {error}")

    def execute(self, line: str) -> bool:
        command, _, rest = line.partition(" ")
        command = command.lower()
        rest = rest.strip()

        if command in ("quit", "exit"):
            return False
        if command in ("help", "?"):
            self.print_help()
        elif command in ("capabilities", "caps"):
            self.query("capabilities", self.client.get_motion_capabilities)
        elif command == "system":
            self.query("system", self.client.query_system_status)
        elif command == "state":
            self.query("state", self.client.query_motion_state)
        elif command == "motors":
            self.print_motors()
        elif command == "status":
            self.query("capabilities", self.client.get_motion_capabilities)
            self.query("system", self.client.query_system_status)
            self.query("state", self.client.query_motion_state)
            self.print_sensor(odom_only=False)
        elif command == "take":
            self.take_control()
        elif command == "release":
            self.release_control()
        elif command == "start":
            parts = rest.split(maxsplit=1)
            if not parts:
                raise ValueError("usage: start ACTION [JSON]")
            if not self.require_control():
                return True
            action = parts[0]
            params = parse_json_object(parts[1]) if len(parts) == 2 else None
            if self.client.start_action(action, params):
                self.action_active = True
                print(f"[PASS] started {action}")
            else:
                self.print_failure(f"start {action}")
        elif command == "set":
            if not rest:
                raise ValueError("usage: set JSON")
            if self.require_control():
                self.result(
                    self.client.set_action_params(parse_json_object(rest)),
                    "params set; action remains active",
                )
        elif command == "send":
            duration_raw, separator, params_raw = rest.partition(" ")
            if not separator:
                raise ValueError("usage: send SECONDS JSON")
            duration = float(duration_raw)
            if duration <= 0:
                raise ValueError("SECONDS must be positive")
            params = parse_json_object(params_raw.strip())
            if self.require_control() and self.client.set_action_params(params):
                print(f"[PASS] command active for {duration:g}s")
                sleep_interruptibly(duration)
                self.result(
                    self.client.set_action_params(STOP_VELOCITY),
                    "timed command finished; walking velocity cleared",
                )
            elif self.client.get_state() == sdk.HighLevelState.kControlled:
                self.print_failure("set params")
        elif command == "zero":
            if self.require_control():
                self.result(
                    self.client.set_action_params(STOP_VELOCITY),
                    "walking velocity cleared; action remains active",
                )
        elif command == "stop":
            if self.require_control() and self.client.stop_action():
                self.action_active = False
                print("[PASS] stop action requested")
            elif self.client.get_state() == sdk.HighLevelState.kControlled:
                self.print_failure("stop action")
        elif command == "estop":
            if self.require_control():
                self.result(self.client.emergency_stop(), "emergency stop requested")
        elif command in ("sensor", "odom"):
            seconds = float(rest) if rest else (5.0 if command == "odom" else 0.0)
            if seconds < 0:
                raise ValueError("SECONDS must be non-negative")
            self.observe(seconds, odom_only=command == "odom")
        else:
            print(f"[FAIL] unknown command: {command} (use help)")
        return True

    def query(self, name: str, call: Any) -> None:
        value = call()
        if value is None:
            self.print_failure(name)
        else:
            print(pretty(value))

    def print_motors(self) -> None:
        layout = self.client.get_motor_layout()
        if layout is None:
            self.print_failure("motors")
            return
        print(f"motorNum={layout.motor_num}")
        for motor in layout.motors:
            print(f"  limb={motor.limb_no} joint={motor.joint_no} name={motor.name}")

    def observe(self, seconds: float, odom_only: bool) -> None:
        with self._sensor_lock:
            first_frame = self._sensor_frames
        if seconds > 0:
            deadline = time.monotonic() + seconds
            next_print = time.monotonic()
            while time.monotonic() < deadline and not _stopping:
                if time.monotonic() >= next_print:
                    self.print_sensor(odom_only)
                    next_print = time.monotonic() + 0.2
                time.sleep(0.02)
        else:
            self.print_sensor(odom_only)
        if seconds > 0:
            with self._sensor_lock:
                received = self._sensor_frames - first_frame
            print(
                f"[INFO] SensorObserved frames={received} elapsed={seconds:g}s "
                f"rate={received / seconds:.2f}Hz"
            )

    def print_sensor(self, odom_only: bool) -> None:
        with self._sensor_lock:
            sensor = self._latest_sensor
        if sensor is None:
            print("[WAIT] no SensorObserved frame received")
            return
        odom = sensor.odom
        prefix = "" if odom_only else f"sensor gps={sensor.gps.valid} uwb={sensor.uwb.valid} "
        print(
            f"{prefix}odom valid={odom.valid} epoch={odom.epoch} "
            f"pos=({odom.position[0]:.3f},{odom.position[1]:.3f},{odom.position[2]:.3f}) "
            f"yaw={odom.yaw:.3f} "
            f"vel=({odom.velocity[0]:.3f},{odom.velocity[1]:.3f},{odom.velocity[2]:.3f}) "
            f"yawSpeed={odom.yaw_speed:.3f}"
        )

    def close(self) -> None:
        try:
            observed = self.client.set_observed_enable(
                {"motionEnable": False, "sensorEnable": False}
            )
            if observed is None:
                print(
                    f"[WARN] disable SensorObserved failed, "
                    f"error={self.client.get_last_error()}",
                    file=sys.stderr,
                )
        except Exception as error:  # noqa: BLE001
            print(f"[WARN] disable SensorObserved failed: {error}", file=sys.stderr)
        self.release_control()
        self.client.disconnect()

    def result(self, ok: bool, success: str) -> None:
        if ok:
            print(f"[PASS] {success}")
        else:
            self.print_failure(success)

    def print_failure(self, operation: str) -> None:
        print(f"[FAIL] {operation}, error={self.client.get_last_error()}")

    def fail(self, operation: str) -> None:
        raise RuntimeError(f"{operation} failed, error={self.client.get_last_error()}")

    @staticmethod
    def print_help() -> None:
        print(
            """Commands:
  status                       query capabilities, system, state and sensor
  capabilities | caps          list supported actions and parameters
  system                       query robot system status
  state                        query current motion state
  motors                       query motor layout
  odom [SECONDS]               print odometry at about 5 Hz (default 5s)
  sensor [SECONDS]             print GPS/UWB/odometry observation
  take                         acquire High-level control; starts no action
  release                      release High-level control
  start ACTION [JSON]          start an action
  set JSON                     keep action parameters active
  send SECONDS JSON            apply parameters, then clear walking velocity
  zero                         clear walking velocity; action keeps running
  stop                         stop the current RPC action
  estop                        request emergency stop
  quit                         clear velocity, release control and exit

Examples:
  take
  start walking
  send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
  odom 5
  zero
  stop
"""
        )


def main() -> int:
    args = build_parser().parse_args()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    discovery: Optional[DeviceDiscovery] = None
    if args.discover or args.discover_only:
        discovery = DeviceDiscovery()
        # Discovery and log callbacks, plus the DDS interface, must be set before init.
        sdk.service.set_discover_callback(discovery.callback)
    sdk.service.set_network_interface(args.iface)
    if not sdk.service.initial(None, args.client_id):
        print("[FAIL] sdk.service.initial", file=sys.stderr)
        return 1

    client: Optional[sdk.MotionHighLevelClient] = None
    console: Optional[HighLevelConsole] = None
    status = 0
    try:
        if discovery is not None:
            devices = discovery.discover()
            print_discovered_devices(devices)
            if args.discover_only:
                return 0 if devices else 1
        if sdk.service.is_multi_device() and not args.device_id:
            suffix = "; choose an SN and rerun with --device-id SN" if discovery else ""
            raise RuntimeError(f"multi-device mode requires --device-id SN{suffix}")
        client = sdk.MotionHighLevelClient(device_id=args.device_id)
        console = HighLevelConsole(client)
        console.connect(args.lease_ms, args.discovery_timeout, args.read_only)
        console.run()
    except Exception as error:  # noqa: BLE001
        print(f"[FAIL] {error}", file=sys.stderr)
        status = 1
    finally:
        if console is not None:
            try:
                console.close()
            except Exception as cleanup_error:  # noqa: BLE001
                print(f"[WARN] cleanup failed: {cleanup_error}", file=sys.stderr)
                status = 1
        elif client is not None:
            try:
                client.disconnect()
            except Exception as cleanup_error:  # noqa: BLE001
                print(f"[WARN] disconnect failed: {cleanup_error}", file=sys.stderr)
                status = 1
        sdk.service.shutdown()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
