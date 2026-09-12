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


### Complete read-only examples

The C++ and Python examples support brain-local, x86 host and ARM64 host. Build/install for the target platform following the README first. Arguments are interface, device SN (`-` for local), and duration in seconds.

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

The examples only connect and enable motion/TRC observations; they never acquire control or send actions. The first valid frame is a baseline. Subsequent output includes `Y pressed`, `Y released`, and accumulated axis changes of at least 0.02. Invalid frames are not interpreted as releases. Ctrl+C or expiry disables motion/TRC observations and disconnects. Do not run alongside another program relying on the same observation switches. Physical controller motion bindings remain active; operate it only in a safe state.

Button indices 0–15: Back, Start, LB, RB, F1, F2, A, B, X, Y, Up, Down, Left, Right, LS, RS. Axis indices 0–5: LX, LY, RX, RY, LT, RT. Y is `buttons[9]`; applications can also use the SDK `buttonY` enum.
