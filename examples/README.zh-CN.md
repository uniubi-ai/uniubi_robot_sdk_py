# Python SDK 示例

[English](README.md)

先准备 C++ SDK 运行库并安装 Python 包：

```bash
export UNIUBI_SDK_ROOT=/path/to/uniubi_robot_sdk
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install ..
export LD_LIBRARY_PATH="$UNIUBI_SDK_ROOT/lib/$(uname -m):${LD_LIBRARY_PATH}"
```

High-level 在大脑板内可直接从当前目录运行，不需要设备 ID：

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py --read-only
```

High-level 也可在外部 Linux 主机以普通用户运行，此时必须同时指定实际 DDS 网卡和目标机器人 SN；请将 `enp3s0` 替换为连接机器人网络的真实网卡：

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py \
  --iface "$UNIUBI_IFACE" --device-id ROBOT_SN --read-only
```

如果不知道 SN，可只发现并列出设备，不建立连接：

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 example_highlevel.py --iface "$UNIUBI_IFACE" --discover-only
```

设备 ID（SN）既可在 Uniubi App 的机器人“基础信息”页面直接查看，也可通过 SDK discovery 获取。发现输出包含每个 SN 及其完整的 `info` JSON。多台机器人同时响应且已知目标 IP 时，可将该 IP 与 `network.ether.ipv4Addr`、`network.wlan.ipv4Addr`、`network.hotspot.ipv4Addr`、`network.mobile.ipv4Addr` 对比，筛选出对应 SN。IP 只用于筛选结果；`--device-id` 最终仍必须传 SN。

`--discover` 会先列出设备再继续，但不会自动选择第一条响应。外部主机使用设备寻址，即使只连接一台机器人也必须显式提供 `--device-id`；SDK 报告支持多设备的部署同样需要 `--device-id`。发现回调和网卡均在 SDK 初始化前设置；等待 5 秒无回调时只重试一次。板载示例需要 root 并直接使用系统 Python；如板载需要指定网卡，使用 `eth0.100`。Low-level 和媒体示例仅板内运行，并使用相同的 `sudo env LD_LIBRARY_PATH=... python3` 前缀。

| 示例 | 行为 | 实机要求 |
|---|---|---|
| `example_highlevel.py` | High-level 交互 CLI：状态、传感器/里程计、取权、动作和参数控制 | 启动不自动执行动作；控制命令要求空旷场地、急停可触达、有人值守 |
| `example_lowlevel.py` | 进入低级控制并周期下发控制帧 | 必须使用吊架，急停可触达 |
| `example_lowlevel_tensorrt.py` | 在 Orin 上用 TensorRT 执行 45 维观测、12 维动作的 Low-level 策略 | 先做 `--validate-only`；吊架上验证 `stand` / `lay`，空旷平整地面再验证 `walk`；急停可触达 |
| `example_media_frames.py` | 板内订阅并落盘媒体帧 | 仅 aarch64 且 `sdk.MEDIA_ENABLED` 为真 |

这些文件是面向开发者阅读和修改的源码示例，不随 wheel 安装。它们始终跟随对应 Python SDK 版本维护。

## Low-level TensorRT 模型示例

大脑上的 JetPack 已提供 CUDA 和 TensorRT。模型示例额外使用 NumPy 与 CUDA Python，
不依赖 PyTorch、TorchVision 或 ONNX Runtime：

```bash
sudo -H python3 -m pip install 'numpy>=1.26,<2' 'cuda-python>=12.6,<12.7'
```

示例策略契约与 Mock 中的公开速度策略一致：输入 `[1,45]`，输出 `[1,12]`，控制
频率 50 Hz。程序每次启动都从 `--onnx` 指定的模型重新构建 FP32 TensorRT engine，
不读取或缓存 `.engine` 文件；构建发生在连接机器人之前。

### 关节顺序契约

当前 `MotorLayout` 返回 12 个关节，SDK/机器人顺序为 leg-major：

```text
FL_ABAD, FL_HIP, FL_KNEE,
FR_ABAD, FR_HIP, FR_KNEE,
RL_ABAD, RL_HIP, RL_KNEE,
RR_ABAD, RR_HIP, RR_KNEE
```

示例不会只依赖硬编码数组下标。连接后先调用 `client.get_motor_layout()`，要求
`motor_num == 12`，并逐项校验实际 `(limb_no, joint_no)` 顺序为
`(0,0), (0,1), (0,2), ..., (3,2)`；数量或顺序不匹配时，会在使能 Low-level
控制前退出。构造每个 `MotorCtrl` 时，也使用该 `MotorLayout` 项中的 `limb_no` 和
`joint_no`，而不是自行推断控制帧的电机标识。

模型输入输出顺序属于模型训练和导出契约，不属于 SDK 契约，可能与上述 leg-major
顺序不同。本示例的模型顺序为 joint-major：

```text
FL_ABAD, FR_ABAD, RL_ABAD, RR_ABAD,
FL_HIP, FR_HIP, RL_HIP, RR_HIP,
FL_KNEE, FR_KNEE, RL_KNEE, RR_KNEE
```

因此示例在推理前显式执行 `SDK leg-major → model joint-major` 重排，并在生成控制帧
前执行 `model joint-major → SDK leg-major` 反向重排。替换 ONNX 时必须同步核对并修改
`MODEL_JOINT_ORDER`、观测归一化、action scale 和输入输出 shape，不能只替换模型文件。

首次只加载 engine 并执行一次零输入推理，不连接机器人：

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  taskset -c 2 python3 example_lowlevel_tensorrt.py \
  --onnx /path/to/policy.onnx \
  --validate-only
```

数值对比和 Mock 闭环均确认后，再运行交互式 Low-level CLI：

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  taskset -c 2 python3 example_lowlevel_tensorrt.py \
  --onnx /path/to/policy.onnx
```

板端运行时建议通过 `taskset -c 2` 将 Low-level 控制进程绑定到 CPU 2，以减少调度
抖动，使观测数据获取耗时和 50 Hz 控制周期更稳定。如果目标设备已有不同的 CPU
隔离或核分配方案，应改用实际分配给该控制进程的独立核心。

程序连接后不会自动使能或执行策略。实机动作分两阶段验证：首先将机器狗可靠固定在
安全吊架上，保持四脚完全腾空，只执行 `stand`、`lay`、`restore`；确认姿态、关节方向
和急停均正常后，将机器狗放到空旷、平整、无障碍地面，再执行 `stand`、
`walk 0.5 0 0`、`stop`、`lay`、`restore`。不要在四脚腾空时执行 `walk`；两个阶段都
必须保持急停可触达并由专人值守。

`restore` 只在内部姿态状态为 laying，并且最新 12 关节观测与趴下目标的最大误差不
超过 0.25 rad 时继续；随后停止控制线程、调用 `set_motion_enable(False)`、等待
`kConnected`、调用 `restore_motion_control_mode()` 并检查结果，成功后退出。`quit`
仍只关闭 Low-level、断开 SDK 并释放 CUDA buffer，不切换默认运控侧。TensorRT
构建失败时程序不会初始化 SDK 或连接机器人。

`example_highlevel.py` 保持一个控制 lease，并在 `highlevel>` 提示符中逐条输入命令。首次连接建议：

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
