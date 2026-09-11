## Read remote-controller input through motion observations

Connect the High-level client, register the motion observation callback, then enable both `motionEnable` and `trcEnable`. Read `obs.trc` in that callback and check `valid` before using `controlId` (Python: `control_id`), `buttons`, or `axes`. No separate TRC callback or control acquisition is required. Disabling `trcEnable` clears the TRC fields.

C++ (with a connected `client`):

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

Python (with a connected `client`):

```python
def on_motion(obs):
    if not obs.trc.valid:
        return
    print(obs.trc.control_id, obs.trc.buttons, obs.trc.axes)

client.set_motion_observed_callback(on_motion)
if client.set_observed_enable({"motionEnable": True, "trcEnable": True}) is None:
    raise RuntimeError("Cannot enable motion/TRC observations")
```

Use robot services that include unified TRC observation forwarding (`robotservice_sdk` commit `8b6aff2b`). Updating client libraries alone does not update robot services. TRC observations do not grant motion control ownership.
