# Uniubi Robot SDK Python

[中文文档](README.zh-CN.md)

Python bindings for the robot motion-control SDK, built with pybind11. They provide the same capabilities as the C++ SDK. See the Python API references for [High-level](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/high-level.md), [Low-level](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/low-level.md), and [MediaBus](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/media.md).

- `service`: one-time global initialization
- `MotionLowLevelClient`: joint-level control; RPC control plane plus on-board shared-memory (SHM) data plane; local single-device only
- `MotionHighLevelClient`: built-in actions and RPC control ownership
- `MediaBusClient`: unified local audio/video and remote audio access, created with `client.create_media_bus_client()`.

## 1. Quick Installation

### Requirements

- Required robot software version: [Cyvet-V1.00.000](http://192.168.1.8/RobotRelease/System/littleDog/Release/dv500/Cyvet-V1.00.000).
- Python 3.8 or later
- Compiled SDK runtime libraries under `$UNIUBI_SDK_ROOT/lib/<arch>/` or `/opt/uniubi/lib/<arch>/`, where `<arch>` is `x86_64`, `aarch64`, `aarch64_host`, or `i386`:
  - `librobotMotionSdk.so`, `libmediaBus.so`, `libudbus.so`, and `libubase.so` must be delivered as a matched version and architecture set.
  - MediaBus is enabled by default on x86_64, i386, aarch64, and aarch64_host. Local Orin deployment supports video, audio, and layout queries; remote deployment supports PCM capture and RawBack playback via `media.setup(host)`. MediaBus SDK remote-video subscriptions and layout queries return `kNotSupported`; remote camera video is available independently over RTSP. SDK headers, runtime libraries, Python extensions, and device software must use matching versions.
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

The SDK Python native binding uses `UNIUBI_SDK_ENABLE_MEDIA` to control media-frame bindings:

- When unspecified, it defaults to `ON` on all supported architectures.
- An `OFF` build still provides LowLevel and HighLevel motion interfaces, but does not compile media-frame bindings or expose `MediaBusError`, `VideoFrame`, `AudioFrame`, or `EncodedVideoFrame`.
- At runtime, check `sdk.MEDIA_ENABLED`. When it is `False`, `create_media_bus_client()` raises `RuntimeError("MediaBus is not available in this SDK build")`.


### Before running the MediaBus example

`examples/example_media_frames.py` is not a remote-camera example. It subscribes to media frames locally on the robot's `aarch64` brain board. Before running it, verify all of the following:

- `sdk.MEDIA_ENABLED` is `True` in the Python environment that will run the example.
- `/etc/robot/sdk_config.json` exists, is readable, and contains a top-level `streamDefine` object.
- The on-board media service, requested stream channels, and SHM environment are ready.
- `librobotMotionSdk.so`, `libmediaBus.so`, `libudbus.so`, and `libubase.so` come from the same delivery and are visible through `LD_LIBRARY_PATH`.
- The example is started as root while preserving `LD_LIBRARY_PATH`.

The optional first argument to `example_media_frames.py` is the Motion SDK service configuration. It does **not** replace `/etc/robot/sdk_config.json`, which the local MediaBus client reads during `media.setup()`.

See [Local MediaBus Configuration](docs/troubleshooting.md#local-mediabus-configuration) for the configuration schema, error mapping, and SHM checks.

### Select the runtime platform

| Runtime location | SDK libraries | Installation |
|---|---|---|
| Brain board | `lib/aarch64/` | Install with the board Python; on-board programs use system Python |
| x86 host | `lib/x86_64/` | Install with the host Python, optionally in a virtual environment |
| ARM64 host | `lib/aarch64_host/` | Select the platform explicitly as shown below |

### pip install (recommended for an independent Python project)

Run the pip installation commands below on the corresponding target machine.

```bash
git clone https://github.com/uniubi-ai/uniubi_robot_sdk.git ~/uniubi_robot_sdk
git clone https://github.com/uniubi-ai/uniubi_robot_sdk_py.git ~/uniubi_robot_sdk_py
cd ~/uniubi_robot_sdk_py
export UNIUBI_SDK_ROOT=~/uniubi_robot_sdk   # or pass -Ccmake.define.UNIUBI_SDK_ROOT=...
```

#### Brain board (`aarch64`)

Install into the system Python on the brain board:

```bash
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install .
```

#### x86 host (`x86_64`)

Install into the current Python environment on the host:

```bash
python3 -m pip install .
```

This produces a standard wheel with an ABI suffix for the Python version, for example:
`robot_motion_sdk/_uniubi_robot_motion_py_native.cpython-310-x86_64-linux-gnu.so`

Build artifacts are written only to isolated CMake and wheel build directories; no native `.so` is generated inside the source package directory. To create a distributable wheel:

```bash
UNIUBI_SDK_ROOT=~/uniubi_robot_sdk python3 -m pip wheel . -w dist
```

For an offline environment, preinstall `scikit-build-core` and CMake, then add `--no-build-isolation` to prevent pip's temporary build environment from downloading tools.

#### ARM64 host (`aarch64_host`)

Use `aarch64_host` for a Linux ARM64 computer outside the robot brain board. It supports remote High-level control and remote PCM capture/RawBack playback, using the same generic media backend as x86. Low-level SHM control and local video/layout access require the robot brain board.

Both platforms have an ARM64 CPU: `CMAKE_SYSTEM_PROCESSOR=aarch64` alone selects the Orin runtime `lib/aarch64/`. Explicitly pass `-DPLATFORM=aarch64_host` to select `lib/aarch64_host/`, including when building against an installed SDK with `find_package(UniubiRobotSdk)`. Use a new build directory when switching platforms.

The delivered host libraries do not depend on NVIDIA media libraries. The target needs glibc >= 2.34, libstdc++ exporting `GLIBCXX_3.4.30` (GCC 12 runtime or later), and `libatomic.so.1`. Copy the complete matching `lib/aarch64_host/` directory, including DDS and other companion libraries.

From the Python SDK repository, build on the target ARM64 host with its Python interpreter:

```bash
export UNIUBI_SDK_ROOT=/path/to/uniubi_robot_sdk
python3 -m pip install . -Ccmake.define.PLATFORM=aarch64_host -Cbuild-dir=build/aarch64_host
export SDK_ARCH=aarch64_host
export LD_LIBRARY_PATH="$UNIUBI_SDK_ROOT/lib/$SDK_ARCH:${LD_LIBRARY_PATH:-}"
# Alternatively, create a wheel for this host platform:
python3 -m pip wheel . --no-deps -w dist/aarch64_host -Ccmake.define.PLATFORM=aarch64_host -Cbuild-dir=build/aarch64_host
```

Python wheels do not bundle SDK runtime libraries. Orin and external-host wheels can have the same `linux_aarch64` tag: retain the platform-specific output directory and use matching runtime libraries; the wheel tag does not distinguish the deployment platform. SDK headers, libraries, extensions, and device software must match.

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

For a Low-level application to access remote-controller input, the remote controller must be connected. If it is disconnected, press `M` until the robot announces “遥控器已连接” (remote controller connected). This is an input prerequisite and does not mean leaving Low-level control.

The basic communication example appears below. For a complete on-board model-inference example, see [`examples/example_lowlevel_tensorrt.py`](examples/example_lowlevel_tensorrt.py). It runs a `[1,45] -> [1,12]` FP32 velocity policy with TensorRT 10 and CUDA Python, without importing PyTorch. The example first reads and verifies the actual 12-joint leg-major `MotorLayout`, then builds control frames with its `limb_no` / `joint_no` fields. Model input and output follow a separate model-order contract, and the example explicitly reorders in both directions between SDK and model order. See the [joint-order contract](examples/README.md#joint-order-contract).

On the board, pinning the process to CPU 2 with `taskset -c 2` is recommended to reduce scheduler jitter and stabilize observation latency and the 50 Hz control period.

```python
import time
import robot_motion_sdk as sdk

sdk.service.set_network_interface("eth0.100")  # ignored by the on-board Low-level client
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

**When an external host is cabled straight into the robot Ethernet port**, first lease an IP to the robot (see [Connect Peripherals](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/connect-peripherals.md)).

### HighLevel

High-level control can run either on the robot's brain board or on an external Linux host. The complete example is an interactive CLI and does not execute an action automatically. Use read-only mode for the first connection.

On the brain board, no device ID is needed. Board-side SDK programs require root privileges; use the system Python after installing the SDK as described under Quick Installation:

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py --read-only
```

On an external Linux host, select the actual DDS network interface and the target robot SN explicitly. External High-level use does not inherently require root; replace `enp3s0` with the interface connected to the robot network:

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py \
  --iface "$UNIUBI_IFACE" --device-id ROBOT_SN --read-only
```

If the SN is unknown, discovery can list the available robots without selecting one:

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py \
  --iface "$UNIUBI_IFACE" --discover-only
```

There are two supported ways to obtain the device ID (SN):

1. Open the robot's **Basic Information** page in the Uniubi App and read the SN directly.
2. Run SDK discovery. The example prints each SN together with its complete discovery `info` JSON. If discovery returns multiple robots and the target IP address is already known, compare it with `network.ether.ipv4Addr`, `network.wlan.ipv4Addr`, `network.hotspot.ipv4Addr`, and `network.mobile.ipv4Addr` to identify the matching SN. The IP address is only a filter; always pass the matched SN, not the IP address, to `--device-id`.

`--discover` lists robots and then continues, but never connects to the first reply automatically. An external host uses device addressing and must receive an explicit `--device-id` even when only one robot is connected. A deployment for which the SDK reports multi-device support also requires `--device-id`. The discovery callback and `--iface` are configured before SDK initialization. If no callback arrives within 5 seconds, the example retries discovery once.

Before entering `take` on a real robot, disconnect the remote controller: either power it off, or press and hold its `M` button until the robot announces “遥控器连接已断开” (remote controller disconnected). High-level cannot obtain ownership while the remote controller remains connected. Read-only commands do not require this step.

In an emergency during High-level control, press `M` again and wait until the robot announces “遥控器已连接” (remote controller connected) before using the remote controller to take over.

At the `highlevel>` prompt, use `status`, `motors`, `sensor 5`, and `odom 5` for read-only checks. When control is needed, enter `take`, `start`, `set`, `send`, `zero`, `stop`, and `release`. For example, to move forward for a bounded duration:

```text
highlevel> take
highlevel> start walking {"lineVelocityX":0.0,"lineVelocityY":0.0,"velocity":0.0}
highlevel> send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
highlevel> stop
highlevel> release
highlevel> quit
```

The minimal lower-level API usage is:

```python
import os
import time
import robot_motion_sdk as sdk

# External Linux: use the actual interface and robot SN.
target_sn = "ROBOT_SN"
sdk.service.set_network_interface(os.environ["UNIUBI_IFACE"])
# On-board instead: target_sn = ""; set_network_interface is normally not required.
# If board-side interface selection is needed, use "eth0.100".
sdk.service.initial(None, "myApp")

with sdk.MotionHighLevelClient(device_id=target_sn) as client:
    if not client.connect() or not client.start_control(timeout_ms=30000):
        raise RuntimeError(f"start control failed: {client.get_last_error()}")

    deadline = time.monotonic() + 30.0
    while client.get_state() != sdk.HighLevelState.kControlled:
        if time.monotonic() >= deadline:
            raise TimeoutError("wait kControlled timeout")
        time.sleep(0.05)

    client.start_action("walking", {
        "lineVelocityX": 0.0,
        "lineVelocityY": 0.0,
        "velocity": 0.0,
    })
    time.sleep(3)
    print(client.query_motion_state())
    client.stop_action()
    client.lie_down()
    time.sleep(5)
    client.release_control()
```

For initial hardware integration, complete read-only checks first, then use the all-zero `walking` request above to validate ownership, action startup, and status feedback. `stop_action()` stops every current action, returns the effective action to zero-speed `walking`, and retains control; starting `walking` with full zero parameters is the equivalent explicit transition. `set_action_params()` with zero values only changes the current action's parameters, while supported speed parameters can also be updated for actions such as `bipedStand` and `handstand`. `stand_up()` / `lie_down()` depend on the current posture and server state machine, so they are not a universal round-trip test. `walking` / `move()` with nonzero velocity, plus `bipedStand` / `handstand` / `jump*` / `damp()`, are high-risk motions and require a clear area with a human ready to intervene.

**When the external host is cabled straight into the robot Ethernet port**, add `--dont-route` so only directly connected DDS locators are used. It is required when the robot Wi-Fi is also on (otherwise DDS may pick the unreachable Wi-Fi address) and optional otherwise:

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py \
  --iface "$UNIUBI_IFACE" --device-id ROBOT_SN --dont-route --read-only
```

### MediaBus

This video/layout example runs on the robot's `aarch64` brain board. Use `example_audio_rawback.py --host ... --device-id ...` for remote audio. Complete the [MediaBus preflight checks](#before-running-the-mediabus-example) first, then run the full example:

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_media_frames.py
```

The example subscribes to raw video, encoded video, and raw audio, prints frame counters, and saves the first 10 frames of each type under `/tmp/media_frame_dump`. It does not request motion-control ownership or send motion commands.

The minimal API lifecycle below subscribes to raw video channel 0 and prints frame metadata. A connected on-board Low-level client is used only to create `MediaBusClient`; `set_motion_enable()` is not required:

```python
import time
import robot_motion_sdk as sdk

if not sdk.MEDIA_ENABLED:
    raise RuntimeError("this Python SDK build does not include MediaBus bindings")

if not sdk.service.initial(None, "mediaQuickStart"):
    raise RuntimeError("SDK initialization failed")

try:
    with sdk.MotionLowLevelClient() as client:
        if not client.connect():
            raise RuntimeError(f"connect failed: {client.get_last_error()}")

        deadline = time.monotonic() + 5.0
        while client.get_state() != sdk.LowLevelState.kConnected:
            if time.monotonic() >= deadline:
                raise TimeoutError("wait kConnected timeout")
            time.sleep(0.05)

        media = client.create_media_bus_client()
        if media is None:
            raise RuntimeError("create_media_bus_client() failed")

        try:
            if not media.setup():
                raise RuntimeError(f"MediaBus setup failed: {media.get_last_error()}")

            def on_video(channel, frame):
                info = frame.frame_info
                print(channel, info.width, info.height, frame.size())

            if not media.start_raw_video_frame(0, on_video):
                raise RuntimeError(f"video subscription failed: {media.get_last_error()}")

            try:
                time.sleep(10)
            finally:
                media.stop_raw_video_frame(0)
        finally:
            media.shutdown()
finally:
    sdk.service.shutdown()
```

Frame callbacks run on SDK-managed media threads, so do not block them with expensive work. `frame.data()` returns a `bytes` copy that may be retained, while zero-copy views returned by `frame.plane_view()` / `frame.view()` are valid only during the callback; copy required pixels before handing them to another thread. For plane/stride-safe raw-video saving and audio or encoded-video subscription, use [`examples/example_media_frames.py`](examples/example_media_frames.py). Setup failures and zero-frame cases are covered by [Local MediaBus Configuration](docs/troubleshooting.md#local-mediabus-configuration).

See `examples/` for more.

Examples are readable, editable source maintained with the repository and are not installed with the wheel. An installed application depends only on the `robot_motion_sdk` package.

## 3. Complete Documentation

- [Custom audio: upload by URL and play](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/use-media-and-device-io.md#custom-audio-upload-by-url-and-play): serve an HTTP URL from Orin/PC, let cerebellum controller import the file, and wait for its audio ID before playback; includes a complete Python example.
- Troubleshooting: [`docs/troubleshooting.md`](docs/troubleshooting.md)
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
| `VideoFrame` / `AudioFrame` / `EncodedVideoFrame` | Same-named classes exported only when `sdk.MEDIA_ENABLED == True`; audio callbacks work in local and remote modes; video callbacks require local deployment |
| `ButtonDefine` / `AxesDefine` / `GPSSignalLevel` / `GEOGCoordMode` / `UWBPairState` / `MotionControlMode` | Same-named `IntEnum` types for button/axis indexes and GPS/UWB/coordinate decoding |

## 6. Known Limitations

- Windows is not supported; Linux only.
- Python multi-interpreter embedding is not supported.
- Python observation callbacks are affected by the GIL. High-level `set_motion_observed_callback` is approximately 50 Hz; for high-frequency Low-level observations use pull mode with `get_latest_observation()` at 500 Hz or above.
- Keep runtime libraries and Python extensions matched to device software; see the PCM example below for remote audio arguments.

## 7. License

Original UniUbi Python bindings, examples, and documentation in this repository are licensed under the Apache License 2.0. Vendored pybind11 remains under its original license. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- [Remote-controller observations](docs/trc-observation.md)

## RTSP camera video

x86 and ARM64 hosts can access two camera streams over RTSP without calling the SDK or acquiring motion control.

```text
rtsp://<DEVICE_IP>:554/live?channel=1&stream=0
rtsp://<DEVICE_IP>:554/live?channel=2&stream=0
```

Use the device Ethernet or Wi-Fi IP address. Set `channel` to `1` or `2`; `stream` is always `0`. Open the URL in an RTSP client such as VLC or FFplay. See [RTSP remote camera streaming](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/use-media-and-device-io.md#rtsp-remote-camera-streaming) for complete commands.

## PCM audio capture and playback

MediaBus is enabled by default on x86_64, i386, aarch64, and aarch64_host. Local Orin deployment supports video, audio, and layout queries; remote deployment supports PCM capture and RawBack playback via `media.setup(host)`. MediaBus SDK remote-video subscriptions and layout queries return `kNotSupported`; remote camera video is available independently over RTSP. SDK headers, runtime libraries, Python extensions, and device software must use matching versions.

[example_audio.py](examples/example_audio.py) · [example_audio_rawback.py](examples/example_audio_rawback.py) · [Audio guide](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/stream-pcm-audio.md)

Remote PC playback with audio capture:

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" python3 examples/example_audio_rawback.py input.pcm --host <ROBOT_IP> --device-id <ROBOT_SN> --interface <DDS_INTERFACE> --capture-channel 0
```

### NV21 and four-channel PCM capture

Use `--capture-all` to save five NV21 images per camera and four 20-second PCM files. Configuration template, commands and validation: [NV21 and four-channel PCM capture](docs/media-capture.md).

- [High-level controller input example](examples/example_highlevel_trc.py) — [TRC usage](docs/trc-observation.md)
