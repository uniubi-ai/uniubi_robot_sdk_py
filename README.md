# Uniubi Robot SDK Python

[中文文档](README.zh-CN.md)

Python bindings for the robot motion-control SDK, built with pybind11. They provide the same capabilities as the C++ SDK. Complete interface documentation is maintained in [`uniubi-docs`](https://github.com/uniubi-ai/uniubi-docs).

- `service`: one-time global initialization
- `MotionLowLevelClient`: joint-level control; RPC control plane plus on-board shared-memory (SHM) data plane; local single-device only
- `MotionHighLevelClient`: built-in actions and RPC control ownership
- `MediaBusClient`: audio/video frame subscription, created with `client.create_media_bus_client()`; local on-board `aarch64` only; see [`uniubi-docs/docs/uniubi_media_sdk.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_media_sdk.md)

**Naming:** this package follows [PEP 8](https://peps.python.org/pep-0008/#function-and-variable-names). Methods and parameters use `snake_case`, such as `get_state` and `start_control`. The C++ SDK uses `camelCase`; the semantics correspond one-to-one. See section 6.1 of the [High-level SDK](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_high_level_sdk.md) and [Low-level SDK](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_low_level_sdk.md) documentation for C++ ↔ Python mappings.

## 1. Quick Installation

### Requirements

- Python 3.8 or later
- Compiled SDK runtime libraries under `$UNIUBI_SDK_ROOT/lib/<arch>/` or `/opt/uniubi/lib/<arch>/`, where `<arch>` is `x86_64`, `aarch64`, or `i386`:
  - `librobotMotionSdk.so`, `libmediaBus.so`, `libudbus.so`, and `libubase.so` must be delivered as a matched version and architecture set.
  - `MediaBusClient` supports only local, on-board media-frame subscription on `aarch64`; do not call it on `x86_64` or `i386`.
- pybind11 is vendored under `ThirdParty/pybind11/`; no separate installation is required.

### Orin Low-level TensorRT environment

Uniubi-provided brain boards ship with JetPack preinstalled. Do not reinstall `nvidia-jetpack` merely to run the Python SDK or Low-level model example. First inspect the installed version and system time:

```bash
date -Is
apt-cache policy nvidia-jetpack
sed -n '1p' /etc/nv_tegra_release
/usr/local/cuda/bin/nvcc --version
python3 -c 'import tensorrt as trt; print(trt.__version__)'
```

An incorrect system time causes HTTPS certificate validation failures in `apt` and `pip`; correct it before installing Python packages. JetPack already provides CUDA, the TensorRT runtime, and the TensorRT Python bindings. The Low-level TensorRT example additionally needs only NumPy and CUDA Python:

```bash
sudo -H python3 -m pip install 'numpy>=1.26,<2' 'cuda-python>=12.6,<12.7'
```

This runtime path does not depend on PyTorch, TorchVision, ONNX Runtime, or cuSPARSELt. The Python `onnx` package is also unnecessary at runtime: the example feeds the model directly to the TensorRT ONNX Parser and rebuilds an in-memory FP32 engine at every process startup, without reading or caching an `.engine` file.

### MediaBus build switch

The 2026-07-03 SDK Python native binding uses `UNIUBI_SDK_ENABLE_MEDIA` to control media-frame bindings:

- When unspecified, it defaults to `ON` on `aarch64` and `OFF` on `x86_64` / `i386`.
- An `OFF` build still provides LowLevel and HighLevel motion interfaces, but does not compile media-frame bindings or expose `MediaBusError`, `VideoFrame`, `AudioFrame`, or `EncodedVideoFrame`.
- At runtime, check `sdk.MEDIA_ENABLED`. When it is `False`, `create_media_bus_client()` raises `RuntimeError("MediaBus is not available in this SDK build")`.
- Enable media bindings only for local on-board `aarch64` deployment. Do not force-enable them on `x86_64` / `i386` merely to compile and then call media interfaces.

### pip install (recommended for an independent Python project)

```bash
git clone https://github.com/uniubi-ai/uniubi_robot_sdk.git ~/uniubi_robot_sdk
git clone https://github.com/uniubi-ai/uniubi_robot_sdk_py.git ~/uniubi_robot_sdk_py
cd ~/uniubi_robot_sdk_py
export UNIUBI_SDK_ROOT=~/uniubi_robot_sdk   # or pass -Ccmake.define.UNIUBI_SDK_ROOT=...
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install .
```

This produces a standard wheel with an ABI suffix for the Python version, for example:
`robot_motion_sdk/_uniubi_robot_motion_py_native.cpython-310-x86_64-linux-gnu.so`

Build artifacts are written only to isolated CMake and wheel build directories; no native `.so` is generated inside the source package directory. To create a distributable wheel:

```bash
UNIUBI_SDK_ROOT=~/uniubi_robot_sdk python3 -m pip wheel . -w dist
```

For an offline environment, preinstall `scikit-build-core` and CMake, then add `--no-build-isolation` to prevent pip's temporary build environment from downloading tools.

### Editable source build

```bash
git clone https://github.com/uniubi-ai/uniubi_robot_sdk.git ~/uniubi_robot_sdk
git clone https://github.com/uniubi-ai/uniubi_robot_sdk_py.git ~/uniubi_robot_sdk_py
cd ~/uniubi_robot_sdk_py
sudo -H env UNIUBI_SDK_ROOT=~/uniubi_robot_sdk \
  python3 -m pip install -e .
```

After editable installation, changes to the Python wrapper take effect immediately. Changes to the C++ binding require reinstallation.

Artifact: `robot_motion_sdk/_uniubi_robot_motion_py_native.cpython-...so`

For temporary use:

```bash
export PYTHONPATH=~/uniubi_robot_sdk_py:$PYTHONPATH
```

## 2. Quick Start

### LowLevel

The basic communication example appears below. For a complete on-board model-inference example, see [`examples/example_lowlevel_tensorrt.py`](examples/example_lowlevel_tensorrt.py). It runs a `[1,45] -> [1,12]` FP32 velocity policy with TensorRT 10 and CUDA Python, without importing PyTorch. The example first reads and verifies the actual 12-joint leg-major `MotorLayout`, then builds control frames with its `limb_no` / `joint_no` fields. Model input and output follow a separate model-order contract, and the example explicitly reorders in both directions between SDK and model order. See the [joint-order contract](examples/README.md#joint-order-contract).

On the board, pinning the process to CPU 2 with `taskset -c 2` is recommended to reduce scheduler jitter and stabilize observation latency and the 50 Hz control period.

```python
import time
import robot_motion_sdk as sdk

sdk.service.set_network_interface("eth0")    # required remotely/multi-device; ignored on-board
sdk.service.initial(None, "myApp")

with sdk.MotionLowLevelClient() as client:
    @client.on_connect
    def _(state, err): print(state, err)   # state: LowLevelState; err: LowLevelError

    client.connect(observed_hz=500)
    while client.get_state() != sdk.LowLevelState.kConnected:
        time.sleep(0.05)

    client.set_motion_enable(True)
    while client.get_state() != sdk.LowLevelState.kPrepared:
        time.sleep(0.05)

    # Query the hardware motor layout (available after kConnected; queried here after kPrepared).
    layout = client.get_motor_layout()
    print(f"motors={layout.motor_num}")
    for mi in layout.motors:
        print(f"  limb={mi.limb_no} joint={mi.joint_no} name={mi.name}")

    # First-run safety: use a rig, keep emergency stop reachable, and clear the area.
    # Zero target/gains/feed-forward torque below only demonstrate communication and
    # observation. They are not a balancing controller. A real closed loop must
    # initialize targets from the current posture and use validated damping, gains,
    # and torque policies.
    action = sdk.MotorCtrlAction()
    motors = []
    for mi in layout.motors:
        m = sdk.MotorCtrl()
        m.limb_no, m.joint_no = mi.limb_no, mi.joint_no
        m.position = m.velocity = m.kp_gain = m.kd_gain = m.torque = 0.0
        motors.append(m)
    action.motor_num = len(motors)
    action.motors = motors

    cmd = sdk.LowLevelMotionCmd()
    cmd.action = 1
    cmd.ac_name = "standing"
    client.send_control(action, cmd)

    obs = client.get_latest_observation(timeout_ms=5)
    if obs is not None:
        print(f"imu accel.z={obs.imu.accel.z:.2f}  motor[0].pos={obs.motors[0].position:.3f}")

    client.set_motion_enable(False)
```

Action-related control frames should also carry a `LowLevelMotionCmd`. For example, standing uses `action = 1` and `ac_name = "standing"`. Use the corresponding action ID and name for other actions so that the server and external observers can interpret the frame.

`MotionLowLevelClient.send_max_torque(action)` sets each motor's maximum torque. It is effective only in `kPrepared`; it identifies motors with `action.motors[i].limb_no` / `joint_no` and carries the target limit in `torque`. This is a low-frequency configuration interface and must not be placed in the high-frequency `send_control()` loop. When building and running the Python native module, the binding, public headers, and `librobotMotionSdk.so` must all come from the same SDK delivery.

### HighLevel

The complete example is an interactive CLI and does not execute an action automatically. Use read-only mode for the first connection.

SDK programs require root privileges on current devices. Use the system Python directly on the brain board. After installing the Python SDK into system Python as described under Quick Installation, run:

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py --read-only
```

At the `highlevel>` prompt, use `status`, `motors`, `sensor 5`, and `odom 5` for read-only checks. When control is needed, enter `take`, `start`, `set`, `send`, `zero`, `stop`, and `release`. For example, to move forward for a bounded duration:

```text
highlevel> take
highlevel> start walking
highlevel> send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
highlevel> stop
highlevel> release
highlevel> quit
```

The minimal lower-level API usage is:

```python
import time
import robot_motion_sdk as sdk

sdk.service.set_network_interface("eth0")    # required remotely/multi-device; ignored on-board
sdk.service.initial(None, "myApp")

with sdk.MotionHighLevelClient() as client:
    if not client.connect() or not client.start_control(timeout_ms=30000):
        raise RuntimeError(f"start control failed: {client.get_last_error()}")

    deadline = time.monotonic() + 30.0
    while client.get_state() != sdk.HighLevelState.kControlled:
        if time.monotonic() >= deadline:
            raise TimeoutError("wait kControlled timeout")
        time.sleep(0.05)

    client.stand_up()
    time.sleep(5)
    client.lie_down()
    time.sleep(5)
    client.release_control()
```

For initial hardware integration, execute only `stand_up()` / `lie_down()`. `walking` / `move()` / `bipedStand` / `handstand` / `jump*` / `damp()` are high-risk motions and require a clear area with a human ready to intervene.

See `examples/` for more.

Examples are readable, editable source maintained with the repository and are not installed with the wheel. An installed application depends only on the `robot_motion_sdk` package.

## 3. Complete Documentation

- Repository runtime notes: [`docs/runtime_notes.md`](docs/runtime_notes.md)
- Documentation home: [`uniubi-docs`](https://github.com/uniubi-ai/uniubi-docs)
- Python / C++ interface mapping: [`docs/uniubi_high_level_sdk.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_high_level_sdk.md)
- Low-level control: [`docs/uniubi_low_level_sdk.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_low_level_sdk.md)
- MediaBus: [`docs/uniubi_media_sdk.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_media_sdk.md)

## 4. Design Notes

- **Callback threads:** `on_connect` runs on an internal SDK thread. pybind11 handles the GIL automatically, but user callbacks must not block or recursively call synchronous SDK methods.
- **State machine:** `get_state()` returns a `LowLevelState` / `HighLevelState` enum. Action methods take effect only in the corresponding state.
- **Error codes:** `get_last_error()` returns a `LowLevelError` / `HighLevelError` enum, grouped by connection, runtime, and usage stages.
- **Idempotency:** repeated `connect()` / `start_control()` / `release_control()` calls are safe.
- **Resources:** a `with` statement disconnects automatically; destroying the Python object also destroys the native instance.

## 5. Type Mapping

| C++ | Python |
|---|---|
| `std::string` (JSON) | `dict` / `list` / scalar, converted automatically with `json.dumps` / `json.loads` |
| `bool` | `bool` |
| `int32_t` / `uint32_t` / `uint64_t` | `int` |
| `std::function<...>` callback | `Callable` |
| `LowLevelState` / `LowLevelError` and similar enums | `enum.IntEnum` generated by pybind |
| `MotorCtrl` / `MotorCtrlAction` / `LowLevelMotionCmd` / `LowLevelMotionObserved` | Python classes with the same names |
| `MotorInfo` / `MotorLayout` | Python classes with the same names, returned by `get_motor_layout()` |
| `IMUObserved` / `Vector3f` / `Quaternionf` / `PowerObserved` / `TRCStickFrame` | Same-named classes exposed through `obs.imu` / `obs.power` / `obs.trc` |
| `SensorObserved` / `GPSFrame` / `GEOGPoint` / `UWBRawObserved` / `MotionOdometry` | Same-named classes returned by HighLevel `get_sensor_observation()` and read through `sensor.gps` / `sensor.uwb` / `sensor.odom` |
| `MediaLayout` | Same-named Python class always exported by the motion native module |
| `VideoFrame` / `AudioFrame` / `EncodedVideoFrame` | Same-named classes exported only when `sdk.MEDIA_ENABLED == True`; for local on-board `MediaBusClient` callbacks on `aarch64` only |
| `ButtonDefine` / `AxesDefine` / `GPSSignalLevel` / `GEOGCoordMode` / `UWBPairState` / `MotionControlMode` | Same-named `IntEnum` types for button/axis indexes and GPS/UWB/coordinate decoding |

## 6. Known Limitations

- Windows is not supported; Linux only.
- Python multi-interpreter embedding is not supported.
- Python observation callbacks are affected by the GIL. High-level `set_motion_observed_callback` is approximately 50 Hz; for high-frequency Low-level observations use pull mode with `get_latest_observation()` at 500 Hz or above.
- Media-frame subscription supports only local on-board `aarch64` deployment. `x86_64` / `i386` builds default to `sdk.MEDIA_ENABLED == False`; do not call `create_media_bus_client()`, `setup()`, or `start_*_frame()`. Runtime `.so` files must still remain a matched version and architecture set.

## 7. License

Original UniUbi Python bindings, examples, and documentation in this repository are licensed under the Apache License 2.0. Vendored pybind11 remains under its original license. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
