#!/usr/bin/env python3
"""Low-level TensorRT policy example for an on-board Jetson Orin.

The policy contract intentionally matches the public Mock example: one
``[1, 45]`` observation tensor produces one ``[1, 12]`` action tensor at
50 Hz.  This example uses NumPy, CUDA Python and TensorRT directly; PyTorch
and ONNX Runtime are not runtime dependencies.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np


DEFAULT_POS_LEG_MAJOR = np.asarray([0.0, 0.8, -1.58] * 4, dtype=np.float32)
CROUCH_POS_LEG_MAJOR = np.asarray(
    [
        0.48,
        1.10,
        -2.72,
        -0.48,
        1.10,
        -2.72,
        0.48,
        1.10,
        -2.72,
        -0.48,
        1.10,
        -2.72,
    ],
    dtype=np.float32,
)
POSTURE_KP_LEG_MAJOR = np.asarray(
    [90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 130.0, 130.0, 140.0, 130.0, 130.0, 140.0],
    dtype=np.float32,
)
POSTURE_KD_LEG_MAJOR = np.asarray(
    [1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5],
    dtype=np.float32,
)
SDK_JOINT_ORDER = (
    "FL_ABAD", "FL_HIP", "FL_KNEE",
    "FR_ABAD", "FR_HIP", "FR_KNEE",
    "RL_ABAD", "RL_HIP", "RL_KNEE",
    "RR_ABAD", "RR_HIP", "RR_KNEE",
)
SDK_LIMB_JOINT_ORDER = tuple((limb, joint) for limb in range(4) for joint in range(3))

# This example's public policy was trained/exported in joint-major order.  This
# is a model contract, not an SDK contract; another model may use another order.
MODEL_JOINT_ORDER = (
    "FL_ABAD", "FR_ABAD", "RL_ABAD", "RR_ABAD",
    "FL_HIP", "FR_HIP", "RL_HIP", "RR_HIP",
    "FL_KNEE", "FR_KNEE", "RL_KNEE", "RR_KNEE",
)
SDK_TO_MODEL = np.asarray(
    [SDK_JOINT_ORDER.index(name) for name in MODEL_JOINT_ORDER], dtype=np.int64
)
MODEL_TO_SDK = np.asarray(
    [MODEL_JOINT_ORDER.index(name) for name in SDK_JOINT_ORDER], dtype=np.int64
)
DEFAULT_POS_MODEL = DEFAULT_POS_LEG_MAJOR[SDK_TO_MODEL]
CONTROL_RATE_HZ = 50.0


def _load_cuda_runtime():
    """Support both current and legacy CUDA Python import layouts."""
    try:
        from cuda.bindings import runtime as cudart
    except ImportError:
        try:
            from cuda import cudart
        except ImportError as exc:
            raise RuntimeError(
                "CUDA Python is required; install the cuda-python package"
            ) from exc
    return cudart


class TensorRTPolicy:
    """Build and run a static one-input/one-output TensorRT 10 policy."""

    def __init__(
        self,
        onnx_path: Path,
        *,
        workspace_mib: int,
    ) -> None:
        try:
            import tensorrt as trt
        except ImportError as exc:
            raise RuntimeError(
                "TensorRT Python bindings are required (provided by JetPack)"
            ) from exc

        self.trt = trt
        self.cudart = _load_cuda_runtime()
        self.logger = trt.Logger(trt.Logger.WARNING)
        builder = trt.Builder(self.logger)
        network = builder.create_network(
            1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
        )
        parser = trt.OnnxParser(network, self.logger)
        if not parser.parse(onnx_path.read_bytes()):
            errors = "\n".join(str(parser.get_error(i)) for i in range(parser.num_errors))
            raise RuntimeError(f"failed to parse ONNX model {onnx_path}:\n{errors}")
        if network.num_inputs != 1 or network.num_outputs != 1:
            raise RuntimeError(
                f"expected one ONNX input and one output, got "
                f"inputs={network.num_inputs}, outputs={network.num_outputs}"
            )
        network_input_shape = tuple(network.get_input(0).shape)
        network_output_shape = tuple(network.get_output(0).shape)
        if network_input_shape != (1, 45) or network_output_shape != (1, 12):
            raise RuntimeError(
                f"unsupported ONNX shapes: input={network_input_shape}, "
                f"output={network_output_shape}"
            )

        config = builder.create_builder_config()
        config.set_memory_pool_limit(
            trt.MemoryPoolType.WORKSPACE,
            max(int(workspace_mib), 1) * 1024 * 1024,
        )
        print(
            f"[INFO] building TensorRT engine from {onnx_path} "
            f"precision=FP32 workspace={workspace_mib} MiB",
            flush=True,
        )
        serialized_engine = builder.build_serialized_network(network, config)
        if serialized_engine is None:
            raise RuntimeError(f"failed to build TensorRT engine from: {onnx_path}")

        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(serialized_engine)
        if self.engine is None:
            raise RuntimeError("failed to deserialize the newly built TensorRT engine")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("failed to create TensorRT execution context")

        inputs = []
        outputs = []
        for index in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(index)
            mode = self.engine.get_tensor_mode(name)
            if mode == trt.TensorIOMode.INPUT:
                inputs.append(name)
            else:
                outputs.append(name)
        if len(inputs) != 1 or len(outputs) != 1:
            raise RuntimeError(
                f"expected one input and one output, got inputs={inputs}, outputs={outputs}"
            )

        self.input_name = inputs[0]
        self.output_name = outputs[0]
        if not self.context.set_input_shape(self.input_name, (1, 45)):
            raise RuntimeError("engine does not accept input shape [1,45]")
        self.input_shape = tuple(self.context.get_tensor_shape(self.input_name))
        self.output_shape = tuple(self.context.get_tensor_shape(self.output_name))
        if self.input_shape != (1, 45) or self.output_shape != (1, 12):
            raise RuntimeError(
                f"unsupported engine shapes: input={self.input_shape}, output={self.output_shape}"
            )

        self.input_dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(self.input_name)))
        self.output_dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(self.output_name)))
        if self.input_dtype not in (np.dtype(np.float16), np.dtype(np.float32)):
            raise RuntimeError(f"unsupported input dtype: {self.input_dtype}")
        if self.output_dtype not in (np.dtype(np.float16), np.dtype(np.float32)):
            raise RuntimeError(f"unsupported output dtype: {self.output_dtype}")

        self.host_output = np.empty(self.output_shape, dtype=self.output_dtype)
        self.stream = None
        self.device_input = None
        self.device_output = None
        try:
            self.stream = self._cuda_value("cudaStreamCreate", self.cudart.cudaStreamCreate())
            self.device_input = self._cuda_value(
                "cudaMalloc(input)", self.cudart.cudaMalloc(45 * self.input_dtype.itemsize)
            )
            self.device_output = self._cuda_value(
                "cudaMalloc(output)", self.cudart.cudaMalloc(12 * self.output_dtype.itemsize)
            )
            if not self.context.set_tensor_address(self.input_name, int(self.device_input)):
                raise RuntimeError(f"failed to bind TensorRT input: {self.input_name}")
            if not self.context.set_tensor_address(self.output_name, int(self.device_output)):
                raise RuntimeError(f"failed to bind TensorRT output: {self.output_name}")
        except Exception:
            self.close()
            raise

    def _cuda_value(self, operation: str, result):
        error, *values = result
        if int(error) != 0:
            raise RuntimeError(f"{operation} failed with CUDA error {int(error)}")
        return values[0] if values else None

    def infer(self, observation: np.ndarray) -> np.ndarray:
        host_input = np.ascontiguousarray(observation, dtype=self.input_dtype)
        if host_input.shape != self.input_shape:
            raise ValueError(f"expected input {self.input_shape}, got {host_input.shape}")
        kind = self.cudart.cudaMemcpyKind
        self._cuda_value(
            "cudaMemcpyAsync(H2D)",
            self.cudart.cudaMemcpyAsync(
                self.device_input,
                host_input.ctypes.data,
                host_input.nbytes,
                kind.cudaMemcpyHostToDevice,
                self.stream,
            ),
        )
        if not self.context.execute_async_v3(stream_handle=int(self.stream)):
            raise RuntimeError("TensorRT execute_async_v3 failed")
        self._cuda_value(
            "cudaMemcpyAsync(D2H)",
            self.cudart.cudaMemcpyAsync(
                self.host_output.ctypes.data,
                self.device_output,
                self.host_output.nbytes,
                kind.cudaMemcpyDeviceToHost,
                self.stream,
            ),
        )
        self._cuda_value(
            "cudaStreamSynchronize", self.cudart.cudaStreamSynchronize(self.stream)
        )
        return self.host_output.astype(np.float32, copy=True)

    def close(self) -> None:
        if getattr(self, "device_input", None) is not None:
            self._cuda_value("cudaFree(input)", self.cudart.cudaFree(self.device_input))
            self.device_input = None
        if getattr(self, "device_output", None) is not None:
            self._cuda_value("cudaFree(output)", self.cudart.cudaFree(self.device_output))
            self.device_output = None
        if getattr(self, "stream", None) is not None:
            self._cuda_value("cudaStreamDestroy", self.cudart.cudaStreamDestroy(self.stream))
            self.stream = None


def _quat_rotate_inverse_wxyz(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    w, x, y, z = [float(a) for a in q]
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-6:
        return v.astype(np.float32)
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    # Inverse rotation by q is rotation by conjugate(q).
    x, y, z = -x, -y, -z
    qv = np.asarray([x, y, z], dtype=np.float32)
    uv = np.cross(qv, v)
    uuv = np.cross(qv, uv)
    return (v + 2.0 * (w * uv + uuv)).astype(np.float32)


def _obs_to_arrays(obs) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if int(getattr(obs, "motor_num", 0)) != 12 or len(getattr(obs, "motors", [])) != 12:
        raise RuntimeError("expected exactly 12 motors in Low-level observation")
    gyro = np.asarray([obs.imu.gyro.x, obs.imu.gyro.y, obs.imu.gyro.z], dtype=np.float32)
    quat = np.asarray(
        [obs.imu.quaternion.w, obs.imu.quaternion.x, obs.imu.quaternion.y, obs.imu.quaternion.z],
        dtype=np.float32,
    )
    pos_leg = np.asarray([m.position for m in obs.motors[:12]], dtype=np.float32)
    vel_leg = np.asarray([m.velocity for m in obs.motors[:12]], dtype=np.float32)
    return gyro, quat, pos_leg, vel_leg


def _build_policy_obs(obs, command: np.ndarray, last_action_model: np.ndarray) -> np.ndarray:
    gyro, quat, pos_leg, vel_leg = _obs_to_arrays(obs)
    gravity_body = _quat_rotate_inverse_wxyz(quat, np.asarray([0.0, 0.0, -1.0], dtype=np.float32))
    # SDK observations are leg-major; explicitly reorder them to this model's
    # joint-major training/export contract before inference.
    pos_model = pos_leg[SDK_TO_MODEL]
    vel_model = vel_leg[SDK_TO_MODEL]
    parts = (
        gyro * 0.2,
        gravity_body,
        command.astype(np.float32),
        pos_model - DEFAULT_POS_MODEL,
        vel_model * 0.05,
        last_action_model.astype(np.float32),
    )
    return np.concatenate(parts, dtype=np.float32).reshape(1, 45)


def _command_from_trc(obs, fallback: np.ndarray) -> np.ndarray:
    trc = getattr(obs, "trc", None)
    if trc is None or not int(getattr(trc, "valid", 0)):
        return fallback.copy()
    axes = list(getattr(trc, "axes", []))
    if len(axes) < 3:
        return fallback.copy()
    # Match mock motionTRC mapping: yaw=axesLX, lineVelocityX=axesLY, lineVelocityY=axesRX.
    return np.asarray([float(axes[1]), float(axes[2]), float(axes[0])], dtype=np.float32)


def _make_action(sdk, layout, target_leg: np.ndarray, kp: float, kd: float):
    kp_values = np.broadcast_to(np.asarray(kp, dtype=np.float32), (12,))
    kd_values = np.broadcast_to(np.asarray(kd, dtype=np.float32), (12,))
    action = sdk.MotorCtrlAction()
    motors = []
    for i, mi in enumerate(layout.motors[:12]):
        m = sdk.MotorCtrl()
        m.limb_no = mi.limb_no
        m.joint_no = mi.joint_no
        m.position = float(target_leg[i])
        m.velocity = 0.0
        m.kp_gain = float(kp_values[i])
        m.kd_gain = float(kd_values[i])
        m.torque = 0.0
        motors.append(m)
    action.motor_num = len(motors)
    action.motors = motors
    return action


def _validate_motor_layout(layout) -> None:
    if layout is None:
        raise RuntimeError("get_motor_layout returned None")
    motors = list(getattr(layout, "motors", []))
    actual = tuple((int(m.limb_no), int(m.joint_no)) for m in motors)
    if int(getattr(layout, "motor_num", 0)) != 12 or len(motors) != 12:
        raise RuntimeError(
            f"expected MotorLayout with 12 motors, got motor_num="
            f"{getattr(layout, 'motor_num', None)} entries={len(motors)}"
        )
    if actual != SDK_LIMB_JOINT_ORDER:
        raise RuntimeError(
            "unsupported MotorLayout order; refusing to enable Low-level control: "
            f"expected={SDK_LIMB_JOINT_ORDER}, actual={actual}"
        )
    print(f"[PASS] MotorLayout SDK order: {', '.join(SDK_JOINT_ORDER)}", flush=True)
    print(f"[INFO] policy model order: {', '.join(MODEL_JOINT_ORDER)}", flush=True)


def _latest_joint_pos_leg_major(client, timeout_ms: int, fallback: np.ndarray) -> np.ndarray:
    obs = client.get_latest_observation(timeout_ms=timeout_ms)
    if obs is None or len(getattr(obs, "motors", [])) < 12:
        return fallback.astype(np.float32).copy()
    return np.asarray([m.position for m in obs.motors[:12]], dtype=np.float32)


def _send_pose(client, sdk, layout, pose: np.ndarray, kp: float, kd: float) -> bool:
    return bool(client.send_control(_make_action(sdk, layout, pose.astype(np.float32), kp, kd)))


def _run_pose_transition(
    client,
    sdk,
    layout,
    start_pose: np.ndarray,
    target_pose: np.ndarray,
    duration_s: float,
    rate_hz: float,
    kp: float,
    kd: float,
    name: str,
) -> tuple[np.ndarray, int]:
    duration_s = max(float(duration_s), 0.0)
    period = 1.0 / max(float(rate_hz), 1.0)
    steps = max(1, int(math.ceil(duration_s / period))) if duration_s > 0.0 else 1
    start_pose = start_pose.astype(np.float32).copy()
    target_pose = target_pose.astype(np.float32).copy()
    next_t = time.monotonic()
    sent_count = 0
    for step in range(steps):
        ratio = 1.0 if steps <= 1 else float(step + 1) / float(steps)
        pose = (1.0 - ratio) * start_pose + ratio * target_pose
        _send_pose(client, sdk, layout, pose, kp, kd)
        sent_count += 1
        next_t += period
        sleep_s = next_t - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)
    print(
        f"{name} transition sent count={sent_count} duration={duration_s:.2f}s "
        f"kp={kp} kd={kd} target[:3]={np.round(target_pose[:3], 3).tolist()}",
        flush=True,
    )
    return target_pose, sent_count


def _wait_lowlevel_state(client, target, timeout_s: float, state_event: threading.Event) -> bool:
    deadline = time.monotonic() + max(timeout_s, 0.0)
    while client.get_state() != target:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return False
        state_event.clear()
        state_event.wait(min(remain, 0.5))
    return True


class PolicyControlLoop:
    def __init__(self, client, sdk, layout, policy, rate_hz: float) -> None:
        self.client = client
        self.sdk = sdk
        self.layout = layout
        self.policy = policy
        self.period = 1.0 / max(rate_hz, 1.0)
        self.lock = threading.Lock()
        self.mode = "idle"
        self.command = np.zeros(3, dtype=np.float32)
        self.hold_pose = DEFAULT_POS_LEG_MAJOR.copy()
        self.hold_kp = POSTURE_KP_LEG_MAJOR.copy()
        self.hold_kd = POSTURE_KD_LEG_MAJOR.copy()
        self.last_action = np.zeros(12, dtype=np.float32)
        self.running = True
        self.sent = 0
        self.failed = 0
        self.thread = threading.Thread(target=self._run, name="tensorrt-policy-control", daemon=True)
        self.thread.start()

    def pause(self) -> None:
        with self.lock:
            self.mode = "idle"
        time.sleep(self.period * 2.0)

    def hold(self, pose: np.ndarray, kp=POSTURE_KP_LEG_MAJOR, kd=POSTURE_KD_LEG_MAJOR) -> None:
        with self.lock:
            self.hold_pose = pose.astype(np.float32).copy()
            self.hold_kp = np.broadcast_to(np.asarray(kp, dtype=np.float32), (12,)).copy()
            self.hold_kd = np.broadcast_to(np.asarray(kd, dtype=np.float32), (12,)).copy()
            self.mode = "stand"

    def walk(self, command: np.ndarray) -> None:
        with self.lock:
            self.command = command.astype(np.float32).copy()
            self.last_action.fill(0.0)
            self.mode = "walk"

    def state(self) -> tuple[str, np.ndarray, int, int]:
        with self.lock:
            return self.mode, self.command.copy(), self.sent, self.failed

    def close(self) -> None:
        self.running = False
        self.thread.join(timeout=2.0)

    def _run(self) -> None:
        next_cycle = time.monotonic()
        while self.running:
            with self.lock:
                mode = self.mode
                command = self.command.copy()
                hold_pose = self.hold_pose.copy()
                hold_kp = self.hold_kp.copy()
                hold_kd = self.hold_kd.copy()
                last_action = self.last_action.copy()

            ok = None
            if mode == "stand":
                ok = self.client.send_control(_make_action(self.sdk, self.layout, hold_pose, hold_kp, hold_kd))
            elif mode == "walk":
                obs = self.client.get_latest_observation(timeout_ms=10)
                if obs is not None:
                    policy_obs = _build_policy_obs(obs, command, last_action)
                    action_model = self.policy.infer(policy_obs)
                    action_model = np.clip(action_model.reshape(12), -100.0, 100.0).astype(np.float32)
                    target_model = DEFAULT_POS_MODEL + 0.25 * action_model
                    # Explicitly reorder model outputs back to SDK leg-major
                    # order before constructing control frames from MotorLayout.
                    target_leg = target_model[MODEL_TO_SDK]
                    ok = self.client.send_control(_make_action(self.sdk, self.layout, target_leg, 35.0, 1.0))
                    with self.lock:
                        self.last_action = action_model

            if ok is not None:
                with self.lock:
                    if ok:
                        self.sent += 1
                    else:
                        self.failed += 1
            next_cycle += self.period
            delay = next_cycle - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_cycle = time.monotonic()


def _print_help() -> None:
    print(
        """commands:
  stand                 smoothly stand up from the current measured pose
  walk [VX VY YAW]      stand first if needed, then run the TensorRT engine; defaults to 0.5 0 0
  stop                  stop the policy and return to the standing target
  lay                   smoothly return to the laying pose
  obs                   print the latest observation
  state                 print client and control-loop state
  help                  show this help
  quit                  stop sending, disable LowLevel control, and exit
"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and run a [1,45] -> [1,12] ONNX policy with TensorRT on Orin."
    )
    parser.add_argument(
        "--onnx",
        required=True,
        type=Path,
        help="Static ONNX policy with input [1,45] and output [1,12].",
    )
    parser.add_argument(
        "--workspace-mib",
        type=int,
        default=512,
        help="TensorRT build workspace limit in MiB (default: 512).",
    )
    parser.add_argument(
        "--sdk-python",
        default=os.getenv("ROBOTSDK_PYTHON_PATH", ""),
        help="Optional source path containing robot_motion_sdk; an installed package is used by default.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Build the engine and run one zero-input inference without connecting to the robot.",
    )
    args = parser.parse_args()

    if args.sdk_python:
        sdk_python = Path(args.sdk_python).expanduser().resolve()
        sys.path.insert(0, str(sdk_python))

    onnx_path = args.onnx.expanduser().resolve()
    if not onnx_path.is_file():
        print(f"ONNX model does not exist: {onnx_path}", flush=True)
        return 2
    policy = TensorRTPolicy(
        onnx_path,
        workspace_mib=args.workspace_mib,
    )
    if args.validate_only:
        try:
            output = policy.infer(np.zeros((1, 45), dtype=np.float32))
            if not np.all(np.isfinite(output)):
                raise RuntimeError("TensorRT validation output contains NaN or Inf")
            print(
                f"[PASS] TensorRT engine built; input=(1,45) output={output.shape} "
                f"dtype={output.dtype}",
                flush=True,
            )
            return 0
        finally:
            policy.close()

    import robot_motion_sdk as sdk

    if not sdk.service.initial(None, "tensorrtPolicyCli"):
        print("sdk.service.initial failed", flush=True)
        policy.close()
        return 1

    client = sdk.MotionLowLevelClient()
    state_event = threading.Event()

    @client.on_connect
    def _on_connect(state, err):
        print(f"[callback] state={state} error={err}", flush=True)
        state_event.set()

    loop = None
    try:
        if not client.connect(observed_hz=500, lease_ms=60000):
            print(f"connect rejected: {client.get_last_error()}", flush=True)
            return 1
        if not _wait_lowlevel_state(client, sdk.LowLevelState.kConnected, 5.0, state_event):
            print(f"connect timeout: {client.get_last_error()}", flush=True)
            return 1
        layout = client.get_motor_layout()
        try:
            _validate_motor_layout(layout)
        except RuntimeError as exc:
            print(f"invalid motor layout: {exc}; sdk_error={client.get_last_error()}", flush=True)
            return 1

        loop = PolicyControlLoop(client, sdk, layout, policy, CONTROL_RATE_HZ)
        posture = "laying"

        def ensure_prepared() -> None:
            if client.get_state() == sdk.LowLevelState.kConnected:
                if not client.set_motion_enable(True):
                    raise RuntimeError(f"enable rejected: {client.get_last_error()}")
                if not _wait_lowlevel_state(client, sdk.LowLevelState.kPrepared, 10.0, state_event):
                    raise RuntimeError(f"enable timeout: {client.get_last_error()}")
            if client.get_state() != sdk.LowLevelState.kPrepared:
                raise RuntimeError(f"LowLevel control is not prepared: {client.get_state()}")

        def transition_to_stand(name: str = "stand") -> None:
            nonlocal posture
            ensure_prepared()
            loop.pause()
            start = _latest_joint_pos_leg_major(client, 500, CROUCH_POS_LEG_MAJOR)
            _run_pose_transition(
                client, sdk, layout, start, DEFAULT_POS_LEG_MAJOR, 2.0, CONTROL_RATE_HZ,
                POSTURE_KP_LEG_MAJOR, POSTURE_KD_LEG_MAJOR, name,
            )
            loop.hold(DEFAULT_POS_LEG_MAJOR)
            posture = "standing"

        print(f"[PASS] connected; model={onnx_path}; robot starts in laying pose", flush=True)
        _print_help()

        while True:
            try:
                line = input("lowlevel> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            command_name, _, raw_args = line.partition(" ")
            command_name = command_name.lower()
            raw_args = raw_args.strip()
            try:
                if command_name in ("quit", "exit"):
                    break
                if command_name == "help":
                    _print_help()
                elif command_name == "stand":
                    transition_to_stand()
                    print("[PASS] standing", flush=True)
                elif command_name == "walk":
                    values = [float(value) for value in raw_args.split()] if raw_args else [0.5, 0.0, 0.0]
                    if len(values) != 3:
                        raise ValueError("usage: walk [VX VY YAW]")
                    if posture not in ("standing", "walking"):
                        print(f"[INFO] current posture={posture}; standing before walk", flush=True)
                        transition_to_stand("walk prepare")
                    else:
                        ensure_prepared()
                    loop.walk(np.asarray(values, dtype=np.float32))
                    posture = "walking"
                    print(f"[PASS] policy running command={values}", flush=True)
                elif command_name == "stop":
                    if client.get_state() != sdk.LowLevelState.kPrepared:
                        raise RuntimeError("LowLevel control is not enabled")
                    loop.pause()
                    start = _latest_joint_pos_leg_major(client, 500, DEFAULT_POS_LEG_MAJOR)
                    _run_pose_transition(
                        client, sdk, layout, start, DEFAULT_POS_LEG_MAJOR, 1.0, CONTROL_RATE_HZ,
                        POSTURE_KP_LEG_MAJOR, POSTURE_KD_LEG_MAJOR, "stop"
                    )
                    loop.hold(DEFAULT_POS_LEG_MAJOR)
                    posture = "standing"
                    print("[PASS] policy stopped; standing", flush=True)
                elif command_name == "lay":
                    if client.get_state() != sdk.LowLevelState.kPrepared:
                        raise RuntimeError("run stand before lay")
                    loop.pause()
                    start = _latest_joint_pos_leg_major(client, 500, DEFAULT_POS_LEG_MAJOR)
                    _run_pose_transition(
                        client, sdk, layout, start, CROUCH_POS_LEG_MAJOR, 2.0, CONTROL_RATE_HZ,
                        POSTURE_KP_LEG_MAJOR, POSTURE_KD_LEG_MAJOR, "lay"
                    )
                    loop.hold(CROUCH_POS_LEG_MAJOR)
                    posture = "laying"
                    print("[PASS] laying", flush=True)
                elif command_name == "obs":
                    obs = client.get_latest_observation(timeout_ms=500)
                    if obs is None:
                        print("[WAIT] no observation", flush=True)
                    else:
                        q = [round(m.position, 3) for m in obs.motors[:12]]
                        print(f"motors={obs.motor_num} q={q}", flush=True)
                elif command_name == "state":
                    mode, command, sent, failed = loop.state()
                    print(
                        f"client={client.get_state()} error={client.get_last_error()} "
                        f"posture={posture} mode={mode} command={command.tolist()} sent={sent} failed={failed}",
                        flush=True,
                    )
                else:
                    print(f"unknown command: {command_name!r}; type help", flush=True)
            except (RuntimeError, ValueError) as exc:
                print(f"[ERROR] {exc}", flush=True)
        return 0
    finally:
        if loop is not None:
            loop.pause()
            loop.close()
        if client.get_state() == sdk.LowLevelState.kPrepared:
            client.set_motion_enable(False)
        client.disconnect()
        sdk.service.shutdown()
        policy.close()


if __name__ == "__main__":
    raise SystemExit(main())
