"""LowLevel 控制模式示例：回调驱动 + 异步 set_motion_enable + 拉模式 obs。

用法：
  python3 example_lowlevel.py [iface]
  iface 未提供时默认使用 eth0（远端/多设备模式生效；板内忽略）

退出死锁规避（务必照做）：
- 全程在 try/finally 里调度，finally 段显式 disconnect + service.shutdown
- 不要依赖 Python GC 析构 client，机理详见 SDK 接口手册 §6.2
- 装 SIGINT/SIGTERM handler 让 Ctrl+C 也走 finally 路径
"""

from __future__ import annotations

import signal
import sys
import threading
import time

import robot_motion_sdk as sdk


_stop = False


def _on_signal(signum, frame):
    """SIGINT/SIGTERM —— 仅置位标志，不在 handler 内做 IO，避免重入死锁。"""
    global _stop
    _stop = True


def main() -> int:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # 可选：注册 SDK 日志回调（必须在 initial 之前）
    def _on_log(level: sdk.LogLevel, msg: str):
        print(f"[sdk-log lv={int(level)}] {msg}", end="")
    sdk.service.set_log_callback(_on_log)

    if not sdk.service.initial(None, "myAppLowLevel"):
        print("SDK init failed")
        return 1

    # 低级控制为板内单设备部署，直接构造（进程内单例）
    client = sdk.MotionLowLevelClient()
    try:
        # 回调驱动：每次 state 变化都 set，主线程 wait_state_cb 用 Event 唤醒
        state_event = threading.Event()

        @client.on_connect
        def _on_connect(state: sdk.LowLevelState, err: sdk.LowLevelError):
            if state == sdk.LowLevelState.kPrepared:
                print("[low] prepared (ready for send_control)")
            elif state == sdk.LowLevelState.kConnected:
                print("[low] connected (call set_motion_enable to prepare)")
            elif state == sdk.LowLevelState.kConnecting:
                print(f"[low] connecting: err={err}")
            elif state == sdk.LowLevelState.kConnectionLost:
                print(f"[low] connection lost (auto-reconnecting): err={err}")
            elif state == sdk.LowLevelState.kDisconnected:
                print(f"[low] disconnected: err={err}")
            if err == sdk.LowLevelError.kMasterSwitchFailed:
                print("[low] master role switch failed (peer may hold motion), retrying...")
            state_event.set()

        def wait_state_cb(target: sdk.LowLevelState, timeout_s: float) -> bool:
            deadline = time.monotonic() + timeout_s
            while client.get_state() != target:
                if _stop:
                    return False
                remain = deadline - time.monotonic()
                if remain <= 0:
                    return False
                state_event.clear()
                state_event.wait(remain)
            return True

        # connect(observed_hz, lease_ms)：lease_ms=0 → server 默认
        if not client.connect(observed_hz=500, lease_ms=60000):
            print(f"connect failed: {client.get_last_error()}")
            return 1

        if not wait_state_cb(sdk.LowLevelState.kConnected, 10.0):
            print("wait connected timeout")
            return 1

        # 异步请求开启 motion；返回 True 仅表示请求已受理
        if not client.set_motion_enable(True):
            print(f"set_motion_enable(True) request rejected: {client.get_last_error()}")
            return 1

        # motor enable 是异步过程，每个关节上电+校验可能几百 ms 到几秒，留充足超时
        if not wait_state_cb(sdk.LowLevelState.kPrepared, 60.0):
            print("wait prepared timeout")
            return 1

        # 按真实硬件布局构造零力矩控制模板：从 get_motor_layout 拿到电机数 + 每电机 (limb_no, joint_no)
        layout = client.get_motor_layout()
        if layout is None:
            print(f"get_motor_layout failed: {client.get_last_error()}")
            client.set_motion_enable(False)
            return 1
        print(f"[low] motor layout: {layout.motor_num} motor(s)")
        for i, mi in enumerate(layout.motors):
            print(f"  motor[{i}]: limb={mi.limb_no} joint={mi.joint_no} name={mi.name}")

        # 硬件首跑安全前提：
        # - 仅在吊架 / 急停可触达 / 空旷场地条件下运行；
        # - 下方零目标、零增益、零前馈力矩只是通信与观测闭环模板，不是平衡站立控制器；
        # - 真实闭环控制应从当前观测姿态初始化目标，并使用经过验证的阻尼、增益和力矩策略。
        action = sdk.MotorCtrlAction()
        motors = []
        for mi in layout.motors:
            m = sdk.MotorCtrl()
            m.limb_no = mi.limb_no
            m.joint_no = mi.joint_no
            m.position = 0.0
            m.velocity = 0.0
            m.kp_gain = 0.0
            m.kd_gain = 0.0
            m.torque = 0.0
            motors.append(m)
        action.motor_num = len(motors)
        action.motors = motors

        cmd = sdk.LowLevelMotionCmd()
        cmd.action = 1
        cmd.ac_name = "standing"

        # 首次联调建议 50Hz × 60s；长稳态验证可在安全闭环确认后按需要延长。
        cycle_period = 0.020   # 20ms
        obs_timeout_ms = 5
        deadline = time.monotonic() + 60.0
        next_cycle = time.monotonic()
        obs_fail_count = 0
        obs_last_log_at = time.monotonic()
        dump_at = time.monotonic()

        while time.monotonic() < deadline:
            if _stop:
                break
            next_cycle += cycle_period

            obs = client.get_latest_observation(obs_timeout_ms)
            if obs is None:
                obs_fail_count += 1
                now = time.monotonic()
                if now - obs_last_log_at >= 1.0:
                    print(f"get_latest_observation failed {obs_fail_count} times/1s, "
                          f"state={client.get_state()} lastErr={client.get_last_error()}")
                    obs_fail_count = 0
                    obs_last_log_at = now
                sleep = next_cycle - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
                continue

            # 1Hz 打印观测量摘要（IMU / power / 第 0 号电机）
            now = time.monotonic()
            if now - dump_at >= 1.0:
                a = obs.imu.accel; g = obs.imu.gyro; q = obs.imu.quaternion
                m0 = obs.motors[0]
                print(f"[obs] imu: temp={obs.imu.temp:.1f}  "
                      f"accel=({a.x:+.2f},{a.y:+.2f},{a.z:+.2f})  "
                      f"gyro=({g.x:+.3f},{g.y:+.3f},{g.z:+.3f})  "
                      f"quat=({q.w:.3f},{q.x:.3f},{q.y:.3f},{q.z:.3f})  "
                      f"power={obs.power.charge_voltage:.2f}V  "
                      f"motor[0]: pos={m0.position:+.3f} vel={m0.velocity:+.3f} torq={m0.torque:+.3f}")
                dump_at = now

            if not client.send_control(action, cmd):
                print(f"send_control failed: {client.get_last_error()}")
                break

            sleep = next_cycle - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)

        # 额外：拉一次传感器观测（gps/uwb），低频即可
        sensor = client.get_sensor_observation()
        if sensor is not None:
            gps = sensor.gps
            uwb = sensor.uwb
            print(f"[sensor] gps valid={gps.valid} "
                  f"point=({gps.point.lat:.6f},{gps.point.lng:.6f}) speed={gps.speed:.2f}  "
                  f"uwb valid={uwb.valid} dist={uwb.distance:.2f} azimuth={uwb.azimuth:.1f}")

        # 退出主循环 → 关 motion enable（异步，不等回调直接走 finally）
        client.set_motion_enable(False)

    finally:
        # 显式释放：避免 GC 死锁
        try:
            client.disconnect()
        except Exception as e:  # noqa: BLE001
            print(f"disconnect raised: {e}")
        try:
            sdk.service.shutdown()
        except Exception as e:  # noqa: BLE001
            print(f"shutdown raised: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
