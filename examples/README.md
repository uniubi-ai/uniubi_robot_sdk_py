# Python SDK Examples

[中文文档](README.zh-CN.md)

Prepare the C++ SDK runtime libraries and install the Python package first:

```bash
export UNIUBI_SDK_ROOT=/path/to/uniubi_robot_sdk
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install ..
export LD_LIBRARY_PATH="$UNIUBI_SDK_ROOT/lib/$(uname -m):${LD_LIBRARY_PATH}"
```

Run High-level directly on the brain board; no device ID is needed:

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py --read-only
```

High-level can also run on an external Linux host without inherently requiring root. Pass both the actual DDS interface and the target robot SN; replace `enp3s0` with the interface connected to the robot network:

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py \
  --iface "$UNIUBI_IFACE" --device-id ROBOT_SN --read-only
```

To find the SN, list devices without connecting:

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py --iface "$UNIUBI_IFACE" --discover-only
```

Obtain the device ID (SN) either from the robot's **Basic Information** page in the Uniubi App or through SDK discovery. Discovery output includes each SN and its complete `info` JSON. When several robots reply and the target IP is known, compare that IP with `network.ether.ipv4Addr`, `network.wlan.ipv4Addr`, `network.hotspot.ipv4Addr`, and `network.mobile.ipv4Addr` to find the corresponding SN. Use the IP only to filter the results; `--device-id` must still receive the SN.

`--discover` lists devices before continuing, but never selects the first response. An external host uses device addressing and requires `--device-id` even when only one robot is connected. A deployment for which the SDK reports multi-device support also requires `--device-id`. The callback and interface are installed before SDK initialization; discovery waits 5 seconds and retries once only when no callback arrives. Board-side examples require root and use the system Python; if board-side interface selection is needed, use `eth0.100`. Low-level and media examples are board-local and use the same `sudo env LD_LIBRARY_PATH=... python3` prefix.

| Example | Behavior | Hardware requirements |
|---|---|---|
| `example_highlevel.py` | Interactive High-level CLI for state, sensors/odometry, ownership, actions, and parameters | Does not execute an action at startup; control commands require a clear area, reachable emergency stop, and attending operator |
| `example_lowlevel.py` | Enters Low-level control and periodically sends control frames | Safety rig and reachable emergency stop required |
| `release_control_to_dv500.sh` | Starts a dedicated Python SDK process to restore built-in/DV500 motion control | Run only after the previous Low-level process has completely exited; no motor enable or joint commands |
| `example_lowlevel_tensorrt.py` | Runs a Low-level policy with 45-dimensional observations and 12-dimensional actions through TensorRT on Orin | Run `--validate-only` first; validate `stand` / `lay` on a rig, then `walk` on clear, level ground; emergency stop reachable |
| `example_media_frames.py` | Subscribes to and saves on-board media frames | `aarch64` only and `sdk.MEDIA_ENABLED` must be true |

These are readable and editable source examples. They are not installed with the wheel and are maintained with the corresponding Python SDK version.

## Dedicated Low-level release control

After the controlling Low-level process has completely exited, run release control as a separate process:

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  ./release_control_to_dv500.sh
```

The Python process connects at 50 Hz with the server-default lease. If it encounters a prepared session, it disables Low-level motion and waits for `kConnected`; it then calls `restore_motion_control_mode()`, disconnects, and shuts down the SDK service. The wrapper starts a completely new Python process every 10 seconds after failure and enforces a total 60-second budget. It does not stop or signal another deployment process; the caller must first shut down the previous Low-level program normally.

## Low-level TensorRT Model Example

JetPack on the brain board already provides CUDA and TensorRT. The model example additionally uses NumPy and CUDA Python and does not depend on PyTorch, TorchVision, or ONNX Runtime:

```bash
sudo -H python3 -m pip install 'numpy>=1.26,<2' 'cuda-python>=12.6,<12.7'
```

The example policy follows the same contract as the public Mock velocity policy: input `[1,45]`, output `[1,12]`, and a 50 Hz control rate. At every startup, the program rebuilds an FP32 TensorRT engine from the model passed with `--onnx`. It neither reads nor caches an `.engine` file, and the build occurs before connecting to the robot.

### Joint-order contract

The current `MotorLayout` returns 12 joints. The SDK/robot uses leg-major order:

```text
FL_ABAD, FL_HIP, FL_KNEE,
FR_ABAD, FR_HIP, FR_KNEE,
RL_ABAD, RL_HIP, RL_KNEE,
RR_ABAD, RR_HIP, RR_KNEE
```

The example does not rely only on hard-coded array indexes. After connecting, it first calls `client.get_motor_layout()`, requires `motor_num == 12`, and verifies that the actual `(limb_no, joint_no)` order is `(0,0), (0,1), (0,2), ..., (3,2)`. It exits before enabling Low-level control if the count or order does not match. Each `MotorCtrl` is also constructed with the `limb_no` and `joint_no` from the corresponding `MotorLayout` item rather than inferred motor identifiers.

Model input and output order is part of the model's training and export contract, not the SDK contract, and may differ from the leg-major order above. This example model uses joint-major order:

```text
FL_ABAD, FR_ABAD, RL_ABAD, RR_ABAD,
FL_HIP, FR_HIP, RL_HIP, RR_HIP,
FL_KNEE, FR_KNEE, RL_KNEE, RR_KNEE
```

The example therefore explicitly reorders `SDK leg-major → model joint-major` before inference and `model joint-major → SDK leg-major` before generating control frames. When replacing the ONNX model, review and update `MODEL_JOINT_ORDER`, observation normalization, action scale, and input/output shapes together. Replacing only the model file is not sufficient.

For the first validation, load the engine and run one zero-input inference without connecting to the robot:

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  taskset -c 2 python3 example_lowlevel_tensorrt.py \
  --onnx /path/to/policy.onnx \
  --validate-only
```

After numerical comparison and Mock closed-loop validation both pass, run the interactive Low-level CLI:

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  taskset -c 2 python3 example_lowlevel_tensorrt.py \
  --onnx /path/to/policy.onnx
```

On the board, pinning the Low-level control process to CPU 2 with `taskset -c 2` is recommended to reduce scheduler jitter and stabilize observation latency and the 50 Hz control period. If the target device already uses a different CPU isolation or allocation plan, use the isolated core assigned to the control process instead.

The program does not automatically enable control or execute the policy after connecting. Validate hardware motion in two stages. First secure the robot on a safety rig with all four feet fully clear, and execute only `stand`, `lay`, and `restore`. After confirming posture, joint directions, and emergency stop operation, place the robot on clear, level, obstacle-free ground and execute `stand`, `walk 0.5 0 0`, `stop`, `lay`, and `restore`. Do not execute `walk` while all four feet are suspended. During both stages, keep the emergency stop within reach and have a dedicated operator attend the robot.

`restore` continues only when the internal posture state is laying and the latest 12-joint observation is within 0.25 rad of the laying target. It then stops the control loop, calls `set_motion_enable(False)`, waits for `kConnected`, calls and checks `restore_motion_control_mode()`, and exits after success. `quit` still only disables Low-level control, disconnects the SDK, and releases CUDA buffers without changing the default motion-control side. If the TensorRT build fails, the program does not initialize the SDK or connect to the robot.

`example_highlevel.py` keeps one control lease and accepts commands one at a time at the `highlevel>` prompt. Recommended first connection:

```text
highlevel> status
highlevel> motors
highlevel> sensor 5
highlevel> odom 5
highlevel> take
highlevel> start walking {"lineVelocityX":0.0,"lineVelocityY":0.0,"velocity":0.0}
highlevel> send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
highlevel> stop
highlevel> release
highlevel> quit
```

`--read-only` only prevents control acquisition at startup; you can still explicitly enter `take` from the CLI. On exit, the program zeros walking velocity, releases control, stops observation, and explicitly calls `disconnect()` rather than relying on Python garbage collection. This cleanup path does not call `stop_action()` automatically; issue `stop` explicitly before `release` when an action may still be active.
