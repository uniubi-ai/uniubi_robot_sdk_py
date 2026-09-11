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
