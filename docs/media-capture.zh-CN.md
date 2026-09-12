# 保存 NV21 图像和四路 PCM

普通 ARM64 外部主机请选择 `aarch64_host`：构建传入 `-DPLATFORM=aarch64_host`（Python 为 `-Ccmake.define.PLATFORM=aarch64_host`），运行时使用 `lib/aarch64_host/`。其媒体能力与 x86 远端模式相同，仅支持远程音频；Orin 本地视频/布局示例仍使用 `aarch64`。

在机器人的 aarch64 Orin 板内，从仓库根目录运行。先准备同版本 SDK 运行库、媒体服务和 SHM；Python 还要求 `sdk.MEDIA_ENABLED == True`。示例连接客户端仅用于创建 MediaBus，不申请运控控制权、不发送运动指令。

## 项目配置文件

项目提供 [`config/sdk_config.json`](../config/sdk_config.json)，作为两路摄像头、四路麦克风的配置参考，内容来自本示例附件，不含凭据。使用前应对照实际媒体服务确认通道名称；它不是所有固件和设备的通用配置。

MediaBus 的 `setup()` 读取 **`/etc/robot/sdk_config.json`**，项目中存在模板并不会自动启用它。原单通道示例的第一个 `config` 参数配置 Motion SDK service，不能改变 MediaBus 的配置读取路径。新增采集模式使用默认 Motion SDK service 配置。

先检查板端现有文件：如果已经存在，应备份后合并核对过的 `streamDefine`，保留其他设备配置，不能直接覆盖。板端尚无此文件时，确认通道匹配后可执行：

```bash
sudo install -d /etc/robot
# -n 保留已有配置文件。
sudo cp -n config/sdk_config.json /etc/robot/sdk_config.json
```

| 流 | MediaBus 通道 |
| --- | --- |
| 摄像头 0 / 1 | `mediaServer.viChannel.0` / `.1` |
| PCM 0 / 1 / 2 / 3 | `mediaServer.aiChannel.0.0` / `.0.1` / `.0.2` / `.0.3` |

配置文件随源码仓库提供；仅安装运行库或 Python wheel 不会自动配置 `/etc/robot/sdk_config.json`。

## 运行采集

按照仓库 README 构建或安装 SDK，设置匹配的 `LD_LIBRARY_PATH`，输出目录必须是**新目录**，且父目录已存在：

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_media_frames.py --capture-all /tmp/media-capture-01 20
```

最后可追加实际网络接口，例如板端确实使用 `eth0.100` 时才填写该值；省略或传 `-` 使用 SDK 默认值。`--pcm4` 是 `--capture-all` 的别名。默认采集 20 秒，可指定 1～60 的整数。原位置参数模式继续保留，每种媒体类型的前 10 帧保存到 `/tmp/media_frame_dump`。

新增模式订阅原始摄像头通道 0、1 和音频通道 0～3，输出：

- 每路摄像头 5 张 `cameraN_WIDTHxHEIGHT_ptsTIMESTAMP_INDEX.nv21`。按 plane/stride 逐行复制，去掉行尾填充，文件内容为 Y 后接 VU，大小为 `宽 × 高 × 3 / 2`。
- 四个 `dmic_chN.pcm`，每路独立保存。仅接受原始 PCM（`dataType=0`）、16000 Hz、16-bit、单声道；支持的小端板上文件为无 WAV 头的 S16LE。20 秒时每路必须为 **640000 字节**，即 320000 个采样点。

回调仅做有界内存复制，停止订阅并关闭 MediaBus 后统一写盘。图像最大接受 4096 × 2160，十张该尺寸图像约需 127 MiB；60 秒四路 PCM 最多另需 7.68 MB。本模式不保存编码视频或 IMU 元数据。

每路 PCM 达到目标字节数后停止追加，整个采集允许额外等待最多 5 秒。因此“20 秒”表示每路收到的样本时长，并不证明数据连续无丢失、四路精确同步。音频时间戳不递增会被拒绝并计数。静音也是有效 PCM，不作为失败条件。

退出码 0 要求六路订阅全部成功、每路摄像头保存 5 张 NV21、四路 PCM 全部足量，且无采集帧格式错误或音频重复时间戳。参数或初始化失败返回 1，采集不完整或保存失败返回 2。以各通道汇总为准；失败时可能保留部分文件供排查，不能作为完整采集结果。

## 查看文件

从图像文件名读取真实尺寸，替换下方占位符：

```bash
ffplay -f rawvideo -pixel_format nv21 -video_size WIDTHxHEIGHT camera0_WIDTHxHEIGHT_ptsTIMESTAMP_INDEX.nv21
ffplay -f s16le -ar 16000 -ac 1 dmic_ch0.pcm
ffmpeg -f s16le -ar 16000 -ac 1 -i dmic_ch0.pcm dmic_ch0.wav
```

构建或合成帧验证不代表实际设备提供了这些数据，板端仍需核对采集汇总与文件大小。
