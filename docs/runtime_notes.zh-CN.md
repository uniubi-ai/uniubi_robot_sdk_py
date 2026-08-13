# 运行注意事项

[English](runtime_notes.md)

本文记录 Python SDK 接入时容易踩坑的运行行为。完整接口说明统一维护在 [uniubi-docs](https://github.com/uniubi-ai/uniubi-docs)。

## HighLevel 动作是异步的

`start_action()`、`stand_up()`、`lie_down()` 返回成功，只代表机器人已接受请求，不代表真实姿态已经到位。

测试收尾或业务退出时，建议使用观测闭环：

1. 调用 `stop_action()`。
2. 调用 `lie_down()` 或 `start_action("laying")`。
3. 轮询 `query_motion_state()`，直到返回空对象（`{}`）或包含 `"action": "laying"`。
4. 再调用 `release_control()`、`disconnect()` 和 `sdk.service.shutdown()`。

不要在机器人仍可能处于 `walking` 或其它动作执行中时，只因为 RPC 返回成功就释放连接。

## 音频 URL 入库是异步的

`add_audio_file()` 可能只表示下载任务已被受理。机器人下载并保存完成后，目标音频才会出现在自定义音频列表中。

推荐流程：

1. 使用稳定的 `id` 和 URL 调用 `add_audio_file()`。
2. 轮询 `query_audio_play_list({"type": "customVoice"})`。
3. 只在目标 `id` 出现后再播放。
4. 删除前先停止播放。

## LowLevel restore 前要确认观测闭环

动作相关控制帧建议传入 `LowLevelMotionCmd`，并同时填写动作 id 和动作名，例如站立使用 `action = 1`、`ac_name = "standing"`，便于服务端内部理解和外部观测。

`send_control()` 返回 `True` 只代表控制帧已提交。恢复默认运控模式前，需要通过观测确认机器人已经到达安全姿态：

1. 将机器人控制到预期安全姿态，通常是 laying。
2. 持续调用 `get_latest_observation()`，确认关节位置接近目标姿态。
3. 调用 `set_motion_enable(False)`。
4. 调用 `restore_motion_control_mode()`。

跳过观测检查，可能会在机器人仍处于过渡姿态时交回控制权。

## LowLevel 最大扭矩设置是低频配置

`send_max_torque(action)` 仅在 `kPrepared` 状态下生效。`action.motor_num` 必须在 `[1, kLowLevelMaxMotorNum]` 范围内；每个元素使用 `limb_no` / `joint_no` 定位电机，并使用 `torque` 表示目标最大扭矩（N·m）。建议基于 `get_motor_layout()` 返回的布局构造完整配置。

返回 `True` 只代表配置帧已提交到共享内存，不代表电机侧已经完成切换。底层默认存在约 10 ms 的扭矩切换窗口，期间不支持位置控制指令；不要将该接口放入高频 `send_control()` 循环，也不要在切换窗口内继续下发位置控制帧。可通过后续 `get_latest_observation()` 返回的 `motors[i].max_torque` 确认当前观测值。

## MediaBus 本地配置

`MediaBusClient` 用于 `aarch64` 板内本地媒体帧订阅。远端 / 多设备 SDK 模式不提供 MediaBus 帧订阅；`x86_64` / `i386` 平台不要调用 `create_media_bus_client()`、`setup()` 或 `start_*_frame()`。

2026-07-03 版 SDK Python native binding 使用 `UNIUBI_SDK_ENABLE_MEDIA` 控制媒体帧绑定。未显式指定时，`aarch64` 默认开启，`x86_64` / `i386` 默认关闭。运行时先检查：

```python
import robot_motion_sdk as sdk

if not sdk.MEDIA_ENABLED:
    raise RuntimeError("current wheel does not include MediaBus bindings")
```

`sdk.MEDIA_ENABLED == False` 时：

- `create_media_bus_client()` 会抛出 `RuntimeError("MediaBus is not available in this SDK build")`。
- `robot_motion_sdk.media_frame` 不可导入，会抛出 `ImportError("MediaBus is not available in this SDK build")`。
- `MediaBusError` 为 `None`，媒体帧类型不会进入公共 `__all__`。

板内部署时，native `LocalMediaBusClient` 固定读取 `/etc/robot/sdk_config.json`，并要求存在顶层 `streamDefine` 对象。配置缺失或格式错误时，`media.setup()` 会失败：

| 错误 | 常见原因 |
|---|---|
| `MediaBusError.kConfigLoadFailed` | `/etc/robot/sdk_config.json` 缺失或不可读 |
| `MediaBusError.kConfigInvalid` | 文件存在，但没有顶层 `streamDefine` 对象 |
| `MediaBusError.kMediaInitFailed` / `MediaBusError.kMediaStartFailed` | 媒体服务、流通道、运行库或 SHM 运行环境未就绪 |

板内最小配置示例：

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

说明：

- `viStream` 数组长度会成为 `MediaLayout.camera_num`。
- `aiStream` 数组长度会成为 `MediaLayout.mic_num`。
- `streamSource.localChannel` 会成为 `MediaLayout.video_encoder_num`。
- 这个 JSON 不是 Cyclone DDS XML 配置。
- `setup()` 和 `get_media_layout()` 成功只代表初始化和能力查询成功。要确认媒体可用，应订阅并持续统计数秒帧数。

## 运行库与 SHM 检查

运行库必须使用同一交付版本、同一目标架构的一组文件。`librobotMotionSdk.so` 和 `libmediaBus.so` 直接依赖 `libudbus.so` 与 `libubase.so`，四者不能跨版本混用；DDS 库和 iceoryx 库也必须与交付包匹配，否则可能表现为服务超时、初始化失败或订阅无帧。

当前设备运行 SDK 程序需要 root 权限；板内 LowLevel 和 MediaBus 链路还依赖受限的共享内存环境。大脑上直接使用系统 `python3`，并按 README 通过 `sudo env` 显式传入 `LD_LIBRARY_PATH`；源码直用模式再额外传入 `PYTHONPATH`。不要通过放宽系统文件或 SHM 权限来绕过要求。
