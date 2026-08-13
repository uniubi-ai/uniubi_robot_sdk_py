# Python SDK 示例

先准备 C++ SDK 运行库并安装 Python 包：

```bash
export UNIUBI_SDK_ROOT=/path/to/uniubi_robot_sdk
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install ..
export LD_LIBRARY_PATH="$UNIUBI_SDK_ROOT/lib/$(uname -m):${LD_LIBRARY_PATH}"
```

示例直接从当前目录运行：

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py --read-only
```

当前设备运行 SDK 示例需要 root 权限。大脑上直接使用系统 Python。上面的安装命令将 SDK 安装到系统 Python；Low-level 和媒体示例也使用相同的 `sudo env LD_LIBRARY_PATH=... python3` 前缀。

| 示例 | 行为 | 实机要求 |
|---|---|---|
| `example_highlevel.py` | High-level 交互 CLI：状态、传感器/里程计、取权、动作和参数控制 | 启动不自动执行动作；控制命令要求空旷场地、急停可触达、有人值守 |
| `example_lowlevel.py` | 进入低级控制并周期下发控制帧 | 必须使用吊架，急停可触达 |
| `example_media_frames.py` | 板内订阅并落盘媒体帧 | 仅 aarch64 且 `sdk.MEDIA_ENABLED` 为真 |

这些文件是面向开发者阅读和修改的源码示例，不随 wheel 安装。它们始终跟随对应 Python SDK 版本维护。

`example_highlevel.py` 参考 8 号狗 Orin 上验证过的 `highlevel_sdk_console.py`，保持一个控制 lease 并在 `highlevel>` 提示符中逐条输入命令。首次连接建议：

```text
highlevel> status
highlevel> motors
highlevel> sensor 5
highlevel> odom 5
highlevel> take
highlevel> start walking
highlevel> send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
highlevel> stop
highlevel> release
highlevel> quit
```

`--read-only` 只表示启动时不申请控制权，进入 CLI 后仍可显式执行 `take`。程序退出时会清零 walking 速度、释放控制权、关闭观测并显式 `disconnect()`，不会依赖 Python GC 清理。
