# Troubleshooting

[中文文档](troubleshooting.zh-CN.md)

This document describes common Python SDK integration problems and the checks or handling steps for them. Complete interface documentation is maintained in [uniubi-docs](https://github.com/uniubi-ai/uniubi-docs).

## HighLevel Actions Are Asynchronous

A successful return from `start_action()`, `stand_up()`, or `lie_down()` only means that the robot accepted the request. It does not mean the physical posture has already reached its target.

Use an observation-based closed loop when finishing a test or exiting an application:

1. Call `stop_action()`; it returns the effective action to zero-speed `walking` while retaining control. Starting `walking` with full zero parameters is the equivalent explicit transition.
2. Call `lie_down()` or `start_action("laying")`.
3. Poll `query_motion_state()` until it returns an empty object (`{}`) or an object containing `"action": "laying"`.
4. Then call `release_control()`, `disconnect()`, and `sdk.service.shutdown()`.

Do not release the connection merely because an RPC succeeded while the robot may still be executing `walking` or another action.

## Adding an Audio URL Is Asynchronous

`add_audio_file()` may only indicate that a download task was accepted. The target audio appears in the custom audio list only after the robot has downloaded and stored it.

Recommended workflow:

1. Call `add_audio_file()` with a stable `id` and URL.
2. Poll `query_audio_play_list({"type": "customVoice"})`.
3. Play the audio only after the target `id` appears.
4. Stop playback before deleting it.

## Verify the Observation Loop Before a LowLevel Restore

Action-related control frames should include a `LowLevelMotionCmd` with both the action ID and action name. For example, standing uses `action = 1` and `ac_name = "standing"`. This helps both internal server interpretation and external observation.

A `True` result from `send_control()` only means that the frame was submitted. Before restoring the default motion-control mode, use observations to confirm that the robot has reached a safe posture:

1. Control the robot into the expected safe posture, normally laying.
2. Continue calling `get_latest_observation()` until joint positions are close to the target posture.
3. Call `set_motion_enable(False)`.
4. Call `restore_motion_control_mode()`.

Skipping the observation check can hand control back while the robot is still transitioning.

## LowLevel Maximum Torque Is a Low-frequency Configuration

`send_max_torque(action)` takes effect only in the `kPrepared` state. `action.motor_num` must be within `[1, kLowLevelMaxMotorNum]`. Each element identifies a motor with `limb_no` / `joint_no` and specifies the target maximum torque in N·m with `torque`. Build the complete configuration from the layout returned by `get_motor_layout()`.

A `True` return only means that the configuration frame was submitted to shared memory; it does not mean the motor-side transition has completed. The lower layer has a default torque-switching window of approximately 10 ms during which position commands are unsupported. Do not put this interface in a high-frequency `send_control()` loop or continue sending position frames during the switching window. Confirm the observed value later through `motors[i].max_torque` from `get_latest_observation()`.

## Local MediaBus Configuration

`MediaBusClient` provides local, on-board media-frame subscription on `aarch64`. Remote or multi-device SDK mode does not provide MediaBus frame subscription. On `x86_64` / `i386`, do not call `create_media_bus_client()`, `setup()`, or `start_*_frame()`.

The SDK Python native binding uses `UNIUBI_SDK_ENABLE_MEDIA` to control media-frame bindings. When unspecified, it defaults to enabled on `aarch64` and disabled on `x86_64` / `i386`. Check at runtime:

```python
import robot_motion_sdk as sdk

if not sdk.MEDIA_ENABLED:
    raise RuntimeError("current wheel does not include MediaBus bindings")
```

When `sdk.MEDIA_ENABLED == False`:

- `create_media_bus_client()` raises `RuntimeError("MediaBus is not available in this SDK build")`.
- Importing `robot_motion_sdk.media_frame` raises `ImportError("MediaBus is not available in this SDK build")`.
- `MediaBusError` is `None`, and media-frame types are not included in the public `__all__`.

For on-board deployment, the native `LocalMediaBusClient` always reads `/etc/robot/sdk_config.json`, which must contain a top-level `streamDefine` object. `media.setup()` fails when the file is missing or malformed:

| Error | Common cause |
|---|---|
| `MediaBusError.kConfigLoadFailed` | `/etc/robot/sdk_config.json` is missing or unreadable |
| `MediaBusError.kConfigInvalid` | The file exists but has no top-level `streamDefine` object |
| `MediaBusError.kMediaInitFailed` / `MediaBusError.kMediaStartFailed` | The media service, stream channel, runtime libraries, or SHM environment is not ready |

Minimal on-board configuration:

```json
{
  "streamDefine": {
    "streamMemory": {
      "total": 5,
      "unit": "M",
      "chunk": 1024,
      "align": 4
    },
    "mediaBus": {
      "domain": "mediaBus",
      "node": "sdkClient",
      "server": "mediaServer",
      "memoryPool": []
    },
    "viStream": [
      {
        "streamNo": 0,
        "channel": {
          "name": "mediaServer.viChannel.0"
        }
      }
    ],
    "aiStream": [
      {
        "streamNo": 0,
        "channel": {
          "name": "mediaServer.aiChannel.0.0"
        }
      }
    ],
    "videoEncode": [
      [
        {
          "stream": 0,
          "encoder": 0,
          "viDevice": 0,
          "codec": 1
        }
      ]
    ],
    "audioEncode": [
      {
        "encoder": 0,
        "aiDevice": 0
      }
    ],
    "streamSource": {
      "localChannel": 1,
      "attribute": [
        {
          "stream": 1,
          "attachVideo": 0,
          "attachAudio": 0
        }
      ]
    }
  }
}
```

Notes:

- The length of `viStream` becomes `MediaLayout.camera_num`.
- The length of `aiStream` becomes `MediaLayout.mic_num`.
- `streamSource.localChannel` becomes `MediaLayout.video_encoder_num`.
- This JSON is not a Cyclone DDS XML configuration.
- Successful `setup()` and `get_media_layout()` calls only confirm initialization and capability discovery. To verify media availability, subscribe and count frames continuously for several seconds.

## Runtime Library and SHM Checks

Runtime libraries must be a matched set from the same delivery version and target architecture. `librobotMotionSdk.so` and `libmediaBus.so` directly depend on `libudbus.so` and `libubase.so`; do not mix versions of these four files. DDS and iceoryx libraries must also match the delivery, otherwise failures can appear as service timeouts, initialization errors, or subscriptions that receive no frames.

SDK programs require root privileges on current devices. On-board LowLevel and MediaBus paths also depend on a restricted shared-memory environment. Use the system `python3` directly on the brain board and pass `LD_LIBRARY_PATH` explicitly through `sudo env` as described in the README. In source-only mode, also pass `PYTHONPATH`. Do not work around this requirement by relaxing system-file or SHM permissions.
