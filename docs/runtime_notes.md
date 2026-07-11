# 运行注意事项

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

运行库必须使用同一交付版本、同一目标架构的一组文件。混用不同版本的 `librobotMotionSdk.so`、`libmediaBus.so`、DDS 库或 iceoryx 库，可能表现为服务超时、初始化失败或订阅无帧。

板内 LowLevel 和 MediaBus 链路依赖共享内存运行环境。如果进程报告没有可写的 iceoryx/RouDi SHM segment，应修正目标设备的运行账号权限或使用设备支持的开发者运行模式，不要通过随意修改系统文件权限来制造“通过”。
