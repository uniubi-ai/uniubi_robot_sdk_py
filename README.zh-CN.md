# Uniubi Robot SDK Python

UWB 观测新增当前配对信标编号：IDL / C++ 为 `uwb.beaconId`，ROS 2 / Python 为 `uwb.beacon_id`。应结合 `pairState` / `pair_state` 和 `valid` 判断配对状态及观测有效性。本版本要求 SDK、消息定义和设备固件版本匹配；升级后需重新生成消息并重新编译应用和 Python 绑定，不支持旧布局混用。

[English](README.md)

机器人运控 SDK 的 Python 绑定，基于 pybind11。功能与 C++ SDK 等价；完整接口说明见 Python API 文档：[High-level](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/high-level.zh-CN.md)、[Low-level](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/low-level.zh-CN.md) 和 [MediaBus](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/api-reference/python/media.zh-CN.md)。

- `service`：全局初始化（一次）
- `MotionLowLevelClient`：低级控制（关节级；RPC 控制面 + 板内共享内存(SHM) 数据面，仅板内单设备）
- `MotionHighLevelClient`：高级控制（预置动作、RPC 控制权）
- `MediaBusClient`：统一媒体入口，支持本机音视频和远端音频，由 `client.create_media_bus_client()` 创建。

## 普通 ARM64 外部主机（`aarch64_host`）

机器人非大脑板的 ARM64 Linux 主机使用 `aarch64_host`，支持远端 High-level 控制、PCM 采集和 RawBack 播放，媒体后端与 x86 相同。Low-level 共享内存控制、本地视频和布局访问要求在机器人大脑板运行。

两个平台都是 ARM64 CPU：仅设置 `CMAKE_SYSTEM_PROCESSOR=aarch64` 仍选择 Orin 的 `lib/aarch64/`。必须显式传入 `-DPLATFORM=aarch64_host` 才会选择 `lib/aarch64_host/`，通过 `find_package(UniubiRobotSdk)` 使用已安装 SDK 时也需要传入。切换平台请使用新的构建目录。

host 包使用主仓 Build 提交 da59f36 中由通用 GCC 11.4 独立编译的 aarch64_host DDS、iceoryx、OpenSSL、zlib、ACL 和 attr 依赖。交付的 host 库不依赖 NVIDIA 媒体库。目标系统需要 glibc ≥ 2.34、提供 `GLIBCXX_3.4.30` 的 libstdc++（GCC 12 或更新的运行库）及 `libatomic.so.1`。请完整携带同版本 `lib/aarch64_host/`，包括 DDS 等配套依赖。

在普通 ARM64 主机的 C++ SDK 仓库中原生构建：

```bash
cmake -S . -B build-aarch64-host -DPLATFORM=aarch64_host
cmake --build build-aarch64-host -j
cmake --install build-aarch64-host --prefix "$HOME/.local/uniubi-aarch64-host"
export SDK_ARCH=aarch64_host
export LD_LIBRARY_PATH="$PWD/lib/$SDK_ARCH:${LD_LIBRARY_PATH:-}"
```

从 x86 交叉编译时，在配置命令中增加 `-DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-aarch64-linux-gnu.cmake`，并安装通用 GNU `gcc-aarch64-linux-gnu` / `g++-aarch64-linux-gnu` 工具链。将产物部署到 ARM64 主机运行。该平台默认不开启 Orin TensorRT 示例。

在目标 ARM64 主机的 Python SDK 仓库中，使用目标 Python 构建：

```bash
export UNIUBI_SDK_ROOT=/path/to/uniubi_robot_sdk
python3 -m pip install . -Ccmake.define.PLATFORM=aarch64_host -Cbuild-dir=build/aarch64_host
export SDK_ARCH=aarch64_host
export LD_LIBRARY_PATH="$UNIUBI_SDK_ROOT/lib/$SDK_ARCH:${LD_LIBRARY_PATH:-}"
# 或生成该 host 平台的 wheel：
python3 -m pip wheel . --no-deps -w dist/aarch64_host -Ccmake.define.PLATFORM=aarch64_host -Cbuild-dir=build/aarch64_host
```

Python wheel 不内置 SDK 运行库。Orin 和外部主机 wheel 可能具有相同的 `linux_aarch64` 标签，请保留按平台区分的产物目录并配套使用运行库；wheel 标签无法区分部署平台。SDK 头文件、运行库、扩展与设备软件必须版本匹配。

远程媒体需先通过设备 ID 连接 High-level 客户端，再调用 `media.setup(robot_ip)`。使用 C++ `example_audio_rawback` 或 Python `example_audio_rawback.py --host ROBOT_IP --device-id DEVICE_ID` 并提供 PCM 文件。远端视频订阅和布局查询返回 `kNotSupported`。


## 1. 快速安装

### 依赖

- 机器人版本必须 **大于等于 1.00.000**。低于该版本的机器人请先升级后再使用本 SDK。
- Python ≥ 3.8
- 已编译的 SDK 运行库（位于 `$UNIUBI_SDK_ROOT/lib/<arch>/` 或 `/opt/uniubi/lib/<arch>/`，`<arch>` ∈ `x86_64/aarch64/aarch64_host/i386`）：
  - `librobotMotionSdk.so`、`libmediaBus.so`、`libudbus.so`、`libubase.so`：运行库包按同版本、同架构成组提供
  - x86_64、i386、aarch64、aarch64_host 默认开启 MediaBus。Orin 本机模式支持视频、音频和布局查询；远端模式通过 `media.setup(host)` 支持 PCM 采集和 RawBack 播放。远端视频订阅和布局查询返回 `kNotSupported`。SDK 头文件、运行库、Python 扩展与设备软件必须版本匹配。
- pybind11 已 vendor 到 `ThirdParty/pybind11/`，无需另装

### Orin Low-level TensorRT 环境

Uniubi 交付的大脑开发板已经预装 JetPack。不要为了运行 Python SDK 或 Low-level
模型示例重复安装 `nvidia-jetpack`；先检查板上现有版本和系统时间：

```bash
date -Is
apt-cache policy nvidia-jetpack
sed -n '1p' /etc/nv_tegra_release
/usr/local/cuda/bin/nvcc --version
python3 -c 'import tensorrt as trt; print(trt.__version__)'
```

系统时间错误会导致 `apt` / `pip` 的 HTTPS 证书校验失败，应先校准时间再安装
Python 包。JetPack 已提供 CUDA、TensorRT 运行库和 TensorRT Python binding；
Low-level TensorRT 示例只额外需要 NumPy 和 CUDA Python：

```bash
sudo -H python3 -m pip install 'numpy>=1.26,<2' 'cuda-python>=12.6,<12.7'
```

该运行链路不依赖 PyTorch、TorchVision、ONNX Runtime 或 cuSPARSELt。Python 的
`onnx` 包也不是运行模型的必要依赖：示例直接通过 TensorRT ONNX Parser 读取模型，
并在每次进程启动时重新构建内存中的 FP32 engine，不读取或缓存 `.engine` 文件。

### MediaBus 构建开关

SDK Python native binding 使用 `UNIUBI_SDK_ENABLE_MEDIA` 控制媒体帧绑定：

- 未显式指定时，所有支持架构默认 `ON`。
- `OFF` 构建仍提供 LowLevel / HighLevel 运控接口，但 native 不编译媒体帧绑定，不提供 `MediaBusError` 和 `VideoFrame` / `AudioFrame` / `EncodedVideoFrame` 等媒体帧类型。
- 运行时可用 `sdk.MEDIA_ENABLED` 判断当前 wheel 是否包含媒体绑定；为 `False` 时调用 `create_media_bus_client()` 会抛出 `RuntimeError("MediaBus is not available in this SDK build")`。


### 运行 MediaBus 示例前

`examples/example_media_frames.py` 不是远程读取摄像头的示例，它只在机器人的 `aarch64` 大脑板内本地订阅媒体帧。运行前必须确认：

- 实际运行示例的 Python 环境中 `sdk.MEDIA_ENABLED` 为 `True`。
- `/etc/robot/sdk_config.json` 存在、可读，并包含顶层 `streamDefine` 对象。
- 板内媒体服务、需要订阅的流通道和 SHM 环境已经就绪。
- `librobotMotionSdk.so`、`libmediaBus.so`、`libudbus.so` 和 `libubase.so` 来自同一交付版本，并可通过 `LD_LIBRARY_PATH` 找到。
- 使用 root 运行示例，同时保留 `LD_LIBRARY_PATH`。

`example_media_frames.py` 可选的第一个参数是 Motion SDK service 配置，**不能**替代本地 MediaBus client 在 `media.setup()` 阶段固定读取的 `/etc/robot/sdk_config.json`。

配置结构、错误码对应原因和 SHM 检查方法见[MediaBus 本地配置](docs/troubleshooting.zh-CN.md#mediabus-本地配置)。

### pip install（推荐，独立 Python 项目）

```bash
git clone https://github.com/uniubi-ai/uniubi_robot_sdk.git ~/uniubi_robot_sdk
git clone https://github.com/uniubi-ai/uniubi_robot_sdk_py.git ~/uniubi_robot_sdk_py
cd ~/uniubi_robot_sdk_py
export UNIUBI_SDK_ROOT=~/uniubi_robot_sdk   # 或在命令行加 -Ccmake.define.UNIUBI_SDK_ROOT=...
sudo -H env UNIUBI_SDK_ROOT="$UNIUBI_SDK_ROOT" \
  python3 -m pip install .
```

产出标准 wheel，按 Python 版本附 ABI 后缀：
`robot_motion_sdk/_uniubi_robot_motion_py_native.cpython-310-x86_64-linux-gnu.so`

构建产物只写入隔离的 CMake / wheel 构建目录，不会在源码包目录中生成 native `.so`。需要生成可分发文件时使用：

```bash
UNIUBI_SDK_ROOT=~/uniubi_robot_sdk python3 -m pip wheel . -w dist
```

离线环境需要预先安装 `scikit-build-core` 和 CMake，然后为 pip 增加 `--no-build-isolation`，避免临时构建环境联网下载工具。

### 源码构建（开发期）

```bash
git clone https://github.com/uniubi-ai/uniubi_robot_sdk.git ~/uniubi_robot_sdk
git clone https://github.com/uniubi-ai/uniubi_robot_sdk_py.git ~/uniubi_robot_sdk_py
cd ~/uniubi_robot_sdk_py
sudo -H env UNIUBI_SDK_ROOT=~/uniubi_robot_sdk \
  python3 -m pip install -e .
```

可编辑安装后，修改 Python 包装层即时生效；修改 C++ binding 代码后需要重新安装。

产物：`robot_motion_sdk/_uniubi_robot_motion_py_native.cpython-...so`

临时使用：

```bash
export PYTHONPATH=~/uniubi_robot_sdk_py:$PYTHONPATH
```

## 2. 快速上手

### LowLevel

Low-level 程序要接入遥控器输入时，遥控器必须处于已连接状态；若已断开，按 `M` 键直到听到
“遥控器已连接”的语音提示。这个状态是接收遥控器输入的前置条件，不表示退出 Low-level 控制。

基础通信示例见下文；完整的板端模型推理示例见
[`examples/example_lowlevel_tensorrt.py`](examples/example_lowlevel_tensorrt.py)。后者使用
TensorRT 10 + CUDA Python 执行 `[1,45] -> [1,12]` 的 FP32 速度策略，不导入 PyTorch。
示例会先读取并校验实际 `MotorLayout` 的 12 关节 leg-major 顺序，再用其中的
`limb_no` / `joint_no` 构造控制帧；模型输入输出采用独立的模型顺序契约，示例显式
完成 SDK 顺序与模型顺序之间的双向重排。详见
[`examples/README.md`](examples/README.md#关节顺序契约)。
板端运行时建议通过 `taskset -c 2` 绑定 CPU 2，以减少调度抖动，使观测数据获取
耗时和 50 Hz 控制周期更稳定。

```python
import time
import robot_motion_sdk as sdk

sdk.service.set_network_interface("eth0.100")  # 板内 Low-level 客户端忽略该设置
sdk.service.initial(None, "myApp")

with sdk.MotionLowLevelClient() as client:
    @client.on_connect
    def _(state, err): print(state, err)   # state: LowLevelState 枚举；err: LowLevelError

    client.connect(observed_hz=500)
    while client.get_state() != sdk.LowLevelState.kConnected:
        time.sleep(0.05)

    client.set_motion_enable(True)
    while client.get_state() != sdk.LowLevelState.kPrepared:
        time.sleep(0.05)

    # 查询硬件电机布局（kConnected 后即可调用；本示例在 kPrepared 后调用）
    layout = client.get_motor_layout()
    print(f"motors={layout.motor_num}")
    for mi in layout.motors:
        print(f"  limb={mi.limb_no} joint={mi.joint_no} name={mi.name}")

    # 硬件首跑安全前提：仅在吊架 / 急停可触达 / 空旷场地条件下运行。
    # 下方零目标、零增益、零前馈力矩只是通信与观测闭环模板，不是平衡站立控制器。
    # 真实闭环控制应从当前观测姿态初始化目标，并使用经过验证的阻尼、增益和力矩策略。
    # 按 layout 构造动作模板
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

    # 拉取观测量
    obs = client.get_latest_observation(timeout_ms=5)
    if obs is not None:
        print(f"imu accel.z={obs.imu.accel.z:.2f}  motor[0].pos={obs.motors[0].position:.3f}")

    client.set_motion_enable(False)
```

动作相关控制帧建议同时携带 `LowLevelMotionCmd`：例如站立使用 `action = 1`、`ac_name = "standing"`，其它动作按对应的 action id 和动作名填写，便于服务端理解和外部观测。

`MotionLowLevelClient.send_max_torque(action)` 可设置各电机最大扭矩。该接口只在 `kPrepared` 生效，使用 `action.motors[i].limb_no` / `joint_no` 定位电机、`torque` 携带目标上限；它是低频配置接口，不应放入高频 `send_control()` 控制循环。构建和运行 Python native 模块时，binding、公开头和 `librobotMotionSdk.so` 必须来自同一套 SDK。

### HighLevel

High-level 既可在机器人大脑板内运行，也可在外部 Linux 主机运行。完整示例是交互式 CLI，启动后不会自动执行动作。首次连接先使用只读模式。

板内运行不需要设备 ID。板载 SDK 程序需要 root 权限；按“快速安装”将 Python SDK 安装到系统 Python 后运行：

```bash
sudo env \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py --read-only
```

外部 Linux 主机必须显式指定实际 DDS 网卡和目标机器人 SN。外部 High-level 运行本身不要求 root；请将 `enp3s0` 替换为连接机器人网络的真实网卡：

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py \
  --iface "$UNIUBI_IFACE" --device-id ROBOT_SN --read-only
```

如果不知道 SN，可仅发现并列出可用机器人，不连接设备：

```bash
UNIUBI_IFACE=enp3s0
env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_highlevel.py \
  --iface "$UNIUBI_IFACE" --discover-only
```

设备 ID（SN）有两种获取方式：

1. 在 Uniubi App 的机器人“基础信息”页面直接查看 SN。
2. 使用 SDK discovery。示例会输出每个 SN 及其完整的发现 `info` JSON。如果发现结果包含多台机器人且已知目标 IP，可将 IP 与 `network.ether.ipv4Addr`、`network.wlan.ipv4Addr`、`network.hotspot.ipv4Addr`、`network.mobile.ipv4Addr` 对比，筛选出对应 SN。IP 只用于筛选；传给 `--device-id` 的始终是匹配到的 SN，不能传 IP。

`--discover` 会先列出机器人再继续运行，但不会自动连接第一条发现结果。外部主机使用设备寻址，即使只连接一台机器人也必须显式提供 `--device-id`；SDK 报告支持多设备的部署同样需要 `--device-id`。发现回调和 `--iface` 均在 SDK 初始化前设置；5 秒内无回调时，示例只重试一次。

真机输入 `take` 申请控制权前，必须先关闭遥控器，或长按遥控器 `M` 键切换，直到听到
“遥控器连接已断开”的语音提示。遥控器仍连接时，High-level 无法取得控制权；只读命令不要求断开遥控器。

High-level 控制过程中如遇紧急情况，可再次按 `M` 键，直到听到“遥控器已连接”的语音提示，
再开始使用遥控器接管。

进入 `highlevel>` 后可用 `status`、`motors`、`sensor 5`、`odom 5` 做只读检查；需要控制时再输入 `take`、`start`、`set`、`send`、`zero`、`stop` 和 `release`。例如限时前进：

```text
highlevel> take
highlevel> start walking {"lineVelocityX":0.0,"lineVelocityY":0.0,"velocity":0.0}
highlevel> send 3 {"lineVelocityX":0.3,"lineVelocityY":0,"velocity":0}
highlevel> stop
highlevel> release
highlevel> quit
```

底层 API 的最小调用方式如下：

```python
import os
import time
import robot_motion_sdk as sdk

# 外部 Linux 主机：设置实际网卡和机器人 SN。
target_sn = "ROBOT_SN"
sdk.service.set_network_interface(os.environ["UNIUBI_IFACE"])
# 板内改为 target_sn = ""，通常无需调用 set_network_interface；如需指定则用 "eth0.100"。
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

首次真实机器人联调应先完成只读检查，再以上述三个速度字段均显式为 0 的 `walking` 验证取权、
动作启动和状态反馈。`stop_action()` 会停止当前动作，将实际动作切回零速 `walking` 并继续保留
控制权；显式启动三个参数均为 0 的 `walking` 也可以完成同样的动作切换。`set_action_params()`
下发零值只会修改当前动作参数；`bipedStand`、`handstand` 等动作如果在 capabilities 中暴露速度参数，
也可以接收这些参数。`stand_up()` / `lie_down()` 受当前姿态和服务端状态机约束，不能
作为通用的往返测试。带非零速度的 `walking` / `move()`，以及 `bipedStand` / `handstand` / `jump*` /
`damp()` 属于高风险运动动作，应在空旷场地和人工接管条件下执行。

### MediaBus

该视频/布局示例只在机器人的 `aarch64` 大脑板内运行；远程音频请使用 `example_audio_rawback.py --host ... --device-id ...`。先完成[运行前检查](#运行-mediabus-示例前)，再运行完整示例：

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_media_frames.py
```

该示例订阅原始视频、编码视频和原始音频，持续打印帧计数，并将每种类型的前 10 帧保存到 `/tmp/media_frame_dump`。整个过程不申请运控控制权，也不发送运动指令。

下面的最小 API 示例订阅原始视频通道 0 并打印帧元数据。板内 Low-level client 只用于创建 `MediaBusClient`，不需要调用 `set_motion_enable()`：

```python
import time
import robot_motion_sdk as sdk

if not sdk.MEDIA_ENABLED:
    raise RuntimeError("当前 Python SDK 构建未包含 MediaBus binding")

if not sdk.service.initial(None, "mediaQuickStart"):
    raise RuntimeError("SDK 初始化失败")

try:
    with sdk.MotionLowLevelClient() as client:
        if not client.connect():
            raise RuntimeError(f"连接失败：{client.get_last_error()}")

        deadline = time.monotonic() + 5.0
        while client.get_state() != sdk.LowLevelState.kConnected:
            if time.monotonic() >= deadline:
                raise TimeoutError("等待 kConnected 超时")
            time.sleep(0.05)

        media = client.create_media_bus_client()
        if media is None:
            raise RuntimeError("create_media_bus_client() 失败")

        try:
            if not media.setup():
                raise RuntimeError(f"MediaBus setup 失败：{media.get_last_error()}")

            def on_video(channel, frame):
                info = frame.frame_info
                print(channel, info.width, info.height, frame.size())

            if not media.start_raw_video_frame(0, on_video):
                raise RuntimeError(f"视频订阅失败：{media.get_last_error()}")

            try:
                time.sleep(10)
            finally:
                media.stop_raw_video_frame(0)
        finally:
            media.shutdown()
finally:
    sdk.service.shutdown()
```

帧回调运行在 SDK 管理的媒体线程中，不要在回调内执行耗时或阻塞操作。`frame.data()` 返回可跨回调保留的 `bytes` 拷贝；`frame.plane_view()` / `frame.view()` 返回的零拷贝视图只在当前回调内有效，需要交给其他线程时应先复制数据。需要正确处理 plane/stride 的原始视频落盘，或订阅音频、编码视频时，直接使用 [`examples/example_media_frames.py`](examples/example_media_frames.py)。setup 失败或持续零帧的排查方法见 [MediaBus 本地配置](docs/troubleshooting.zh-CN.md#mediabus-本地配置)。

更多见 `examples/`。

示例作为可阅读、可修改的源码随仓库维护，不随 wheel 安装；安装后的业务程序只依赖 `robot_motion_sdk` 包。

## 3. 完整文档

- [自定义音频：通过 URL 上传并播放](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/use-media-and-device-io.zh-CN.md#自定义音频通过-url-上传并播放)：Orin/PC 提供 HTTP URL，DV500 下载入库，等待音频 ID 出现后再播放；包含 Python 完整示例。
- 故障排查：[`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md)
- 文档总站：[`uniubi-docs`](https://github.com/uniubi-ai/uniubi-docs)
- Python / C++ 接口映射：[`docs/uniubi_high_level_sdk.zh-CN.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_high_level_sdk.zh-CN.md)
- 低级控制：[`docs/uniubi_low_level_sdk.zh-CN.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_low_level_sdk.zh-CN.md)
- 媒体总线：[`docs/uniubi_media_sdk.zh-CN.md`](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/uniubi_media_sdk.zh-CN.md)

## 4. 设计要点

- **回调线程**：`on_connect` 在 SDK 内部线程触发。pybind11 自动处理 GIL，但用户回调内不要阻塞或递归调用 SDK 同步方法。
- **状态机**：`get_state()` 返回 `LowLevelState` / `HighLevelState` 枚举；动作类接口必须在对应状态下才生效。
- **错误码**：`get_last_error()` 返回 `LowLevelError` / `HighLevelError` 枚举；分阶段定义（连接 / 运行时 / 用法错误）。
- **幂等**：`connect()` / `start_control()` / `release_control()` 重复调用安全。
- **资源**：`with` 语句自动 `disconnect`；Python 对象生命周期结束时也会析构 native 实例。

## 5. 类型映射

| C++ | Python |
|---|---|
| `std::string`（JSON） | `dict` / `list` / 标量（自动 `json.dumps` / `json.loads` 互转） |
| `bool` | `bool` |
| `int32_t` / `uint32_t` / `uint64_t` | `int` |
| `std::function<...>` 回调 | `Callable` |
| `LowLevelState` / `LowLevelError` 等枚举 | `enum.IntEnum`（pybind 生成） |
| `MotorCtrl` / `MotorCtrlAction` / `LowLevelMotionCmd` / `LowLevelMotionObserved` | 同名 Python 类 |
| `MotorInfo` / `MotorLayout` | 同名 Python 类（`get_motor_layout()` 返回） |
| `IMUObserved` / `Vector3f` / `Quaternionf` / `PowerObserved` / `TRCStickFrame` | 同名 Python 类（`obs.imu` / `obs.power` / `obs.trc` 字段） |
| `SensorObserved` / `GPSFrame` / `GEOGPoint` / `UWBRawObserved` / `MotionOdometry` | 同名 Python 类（HighLevel `get_sensor_observation()` 返回；通过 `sensor.gps` / `sensor.uwb` / `sensor.odom` 读取） |
| `MediaLayout` | 同名 Python 类（运控 native 模块固定导出） |
| `VideoFrame` / `AudioFrame` / `EncodedVideoFrame` | 同名 Python 类（仅 `sdk.MEDIA_ENABLED == True` 时导出，音频回调支持本机和远端模式，视频回调需要本机模式；详见媒体 SDK 手册） |
| `ButtonDefine` / `AxesDefine` / `GPSSignalLevel` / `GEOGCoordMode` / `UWBPairState` / `MotionControlMode` | 同名 `IntEnum`（按键/摇杆下标、GPS/UWB/坐标系解码用） |

## 6. 已知限制

- 不支持 Windows（仅 Linux）
- 不支持 Python 多解释器嵌入
- 观测帧 Python 回调（高级 `set_motion_observed_callback`，约 50Hz）受 GIL 影响；低级高频观测请用拉模式 `get_latest_observation()`（≥ 500 Hz）
- 运行库和 Python 扩展需与设备版本匹配；远端音频参数见下方 PCM 示例。

## 7. 许可证

本仓库中的 UniUbi 原创 Python binding、示例和文档使用 Apache License 2.0。vendored pybind11 按其原始许可证授权。详见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

- [手柄观测](docs/trc-observation.zh-CN.md)

## PCM 音频采集与播放

x86_64、i386、aarch64、aarch64_host 默认开启 MediaBus。Orin 本机模式支持视频、音频和布局查询；远端模式通过 `media.setup(host)` 支持 PCM 采集和 RawBack 播放。远端视频订阅和布局查询返回 `kNotSupported`。SDK 头文件、运行库、Python 扩展与设备软件必须版本匹配。

[example_audio.py](examples/example_audio.py) · [example_audio_rawback.py](examples/example_audio_rawback.py) · [音频使用指南](https://github.com/uniubi-ai/uniubi-docs/blob/main/docs/how-to/stream-pcm-audio.zh-CN.md)

远端 PC 播放并采集音频：

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" python3 examples/example_audio_rawback.py input.pcm --host <DV500_IP> --device-id <ROBOT_SN> --interface <DDS_INTERFACE> --capture-channel 0
```

### NV21 与四路 PCM 采集

使用 `--capture-all` 保存每路摄像头 5 张 NV21 图像和四路各 20 秒 PCM。配置模板、命令与验收方法：[NV21 与四路 PCM 采集](docs/media-capture.zh-CN.md)。

- [High-level 遥控器按键示例](examples/example_highlevel_trc.py) — [TRC 运行说明](docs/trc-observation.zh-CN.md)
