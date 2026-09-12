## 通过运动观测读取手柄输入

连接 High-level 客户端、注册运动观测回调后，同时开启 `motionEnable` 和 `trcEnable`。在同一回调中读取 `obs.trc`；使用 `controlId`（Python 为 `control_id`）、`buttons` 和 `axes` 前先检查 `valid`。无需单独的 TRC 回调，也无需申请控制权。关闭 `trcEnable` 后 TRC 字段清零。

C++ （`client` 已连接）:

```cpp
client->setMotionObservedCallback([](const uniubi::RobotSdk::LowLevelMotionObserved& obs) {
    if (!obs.trc.valid) return;
    // Read obs.trc.buttons and obs.trc.axes here.
});
std::string result;
if (!client->setObservedEnable(R"({"motionEnable":true,"trcEnable":true})", result)) {
    // Handle the configuration failure before waiting for observations.
}
```

Python （`client` 已连接）:

```python
def on_motion(obs):
    if not obs.trc.valid:
        return
    print(obs.trc.control_id, obs.trc.buttons, obs.trc.axes)

client.set_motion_observed_callback(on_motion)
if client.set_observed_enable({"motionEnable": True, "trcEnable": True}) is None:
    raise RuntimeError("Cannot enable motion/TRC observations")
```

机器人服务需包含统一 TRC 观测转发改动（`robotservice_sdk` 提交 `8b6aff2b`）。仅更新客户端库不会更新机器人服务。手柄输入属于观测数据，不代表获得运动控制权。


### 完整只读示例

C++ 和 Python 示例均支持大脑本地、x86 host 和 ARM64 host。先按 README 完成对应平台的构建／安装。参数依次为网卡、设备 SN（本地用 `-`）、采样秒数。

```bash
# C++ (SDK build directory)
cmake --build build --target example_highlevel_trc
./build/examples/example_highlevel_trc eth0.100 - 60
./build/examples/example_highlevel_trc enp1s0 YOUR_ROBOT_SN 60
# ARM64 host: use its actual interface, e.g. eth0

# Python (installed SDK environment)
python3 examples/example_highlevel_trc.py eth0.100 - 60
python3 examples/example_highlevel_trc.py enp1s0 YOUR_ROBOT_SN 60
```

仅连接并开启运动／TRC 观测，不获取控制权、不发送动作。首个有效帧打印基准状态；后续打印 `Y pressed`、`Y released` 等按键变化，轴变化累计达到 0.02 时打印。无效帧不解释为按键松开。Ctrl+C 或到时退出会关闭本次运动／TRC 观测并断开；请勿与依赖同一观测开关的其他程序并行运行。手柄自身的运动绑定仍然生效，应在现场安全状态下操作。

按键下标 0–15：Back、Start、LB、RB、F1、F2、A、B、X、Y、Up、Down、Left、Right、LS、RS。轴下标 0–5：LX、LY、RX、RY、LT、RT。Y 对应 `buttons[9]`；业务代码也可使用 SDK 的 `buttonY` 枚举。
