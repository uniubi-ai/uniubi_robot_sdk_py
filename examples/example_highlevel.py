"""HighLevel 控制模式示例：连接 → 取控制权 → 动作 + 音频 → 释放 → 断开。

用法：
  python3 example_highlevel.py [iface]
  iface 未提供时默认使用 eth0（远端/多设备模式生效；板内忽略）

退出死锁规避（务必照做）：
- 全程在 try/finally 里调度，finally 段显式调用 client.disconnect() + service.shutdown()
- 不要依赖 Python GC 析构 client，机理详见 SDK 接口手册 §6.2
- 装 SIGINT/SIGTERM handler 让 Ctrl+C 也走 finally 路径
"""

from __future__ import annotations

import json
import signal
import sys
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

    # 远端 / 多设备场景指定网卡；板内忽略。argv[1] 可覆盖默认 eth0
    iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
    sdk.service.set_network_interface(iface)

    if not sdk.service.initial(None, "myAppHighLevel"):
        print("SDK init failed")
        return 1

    # 板内单设备直接 MotionHighLevelClient()；远端多设备需要先 discoverDevices 拿 SN
    if sdk.service.is_multi_device():
        print("multi-device mode: use discover_devices() first to obtain a SN")
        sdk.service.shutdown()
        return 1
    client = sdk.MotionHighLevelClient()
    try:
        # ── 1) 注册回调（必须在 connect 之前）──
        @client.on_connect
        def _on_connect(state: sdk.HighLevelState, err: sdk.HighLevelError) -> None:
            if state == sdk.HighLevelState.kControlled:
                print("[high] control acquired")
            elif state == sdk.HighLevelState.kConnected:
                if err == sdk.HighLevelError.kSessionExpired:
                    print("[high] lease expired")
                elif err == sdk.HighLevelError.kSessionRevoked:
                    print("[high] preempted by others")
                elif err == sdk.HighLevelError.kRpcAcquireRejected:
                    print("[high] startControl rejected/timeout")
                else:
                    print("[high] control released")

        @client.on_event
        def _on_event(topic: str, payload_json: str) -> None:
            info = json.loads(payload_json) if payload_json else {}
            if topic == "statistics/play_list":
                print(f"[evt] play idx={info.get('index')} playing={info.get('playing')}")
            elif topic == "statistics/device_status":
                print(f"[evt] dev keys={list(info.keys())}")

        # ── 2) 连接 ──
        if not client.connect(lease_ms=60000):
            print(f"connect failed: {client.get_last_error()}")
            return 1

        # ── 3) 查询类接口：能力 + 系统状态 ──
        caps = client.get_motion_capabilities()
        if caps is not None:
            print("capabilities:", caps)

        status = client.query_system_status()
        if status is not None:
            print("battery:", status.get("battery"))
            print("network keys:", list((status.get("network") or {}).keys()))

        # ── 4) 取控制权（异步；轮询等到 kControlled）──
        if not client.start_control(timeout_ms=30000):
            print(f"startControl failed: {client.get_last_error()}")
            return 1

        deadline = time.monotonic() + 30.0
        while client.get_state() != sdk.HighLevelState.kControlled:
            if _stop or time.monotonic() > deadline:
                print("[high] not controlled, give up")
                return 1
            time.sleep(0.05)

        # ── 5) 首跑安全动作 ──
        client.stand_up()
        for _ in range(50):  # 5s
            if _stop:
                break
            time.sleep(0.1)
        client.lie_down()
        for _ in range(50):  # 5s
            if _stop:
                break
            time.sleep(0.1)

        # ── 5b) 原始 TRC 控制帧（DDS topic motion/trc，不走 RPC）──
        # 默认不发送真实原始控制帧；需要动作调试时打开开关，并确认场地、急停和人工接管。
        # 前置：host proxy 已 setup TRC reader 并在 acquire 响应里下发 rawActionId（SDK 持权后自动接收）
        # 若服务端 TRC reader 未配置 → SDK 收不到 rawActionId → set_raw_control_cmd 返 False + kActionRejected
        enable_raw_control_demo = False
        if enable_raw_control_demo:
            frame = sdk.TRCStickFrame()
            frame.valid = 1
            frame.control_id = 0  # 由 SDK 内部用 rawActionId 覆盖，此字段值实际不参与发送
            buttons = [0] * int(sdk.ButtonDefine.BUTTON_MAX)
            buttons[int(sdk.ButtonDefine.buttonStart)] = 1  # Motion
            buttons[int(sdk.ButtonDefine.buttonA)] = 1  # Motion+A = Lie Down（内部动作 laying）
            frame.buttons = buttons
            frame.axes = [0.0] * int(sdk.AxesDefine.AXES_MAX)  # axesLX/LY/RX/RY/LT/RT
            if not client.set_raw_control_cmd(frame):
                print(f"set_raw_control_cmd skipped/failed: {client.get_last_error()}")

        # ── 6) 音频：启动 → 暂停 → 停止 ──
        client.start_audio_play({
            "list": [{"id": "1"}],
            "volume": 50,
            "repeat": 1,
        })
        time.sleep(5)
        client.pause_audio_play()
        time.sleep(1)
        client.stop_audio_play()

        # ── 7) 查询：音频详情 + 文件列表 ──
        detail = client.query_audio_play_detail()
        if detail is not None:
            print("audio detail:", detail)

        audio_list = client.query_audio_play_list({"type": "customVoice"})
        if audio_list is not None:
            print("audio list:", audio_list)

        # ── 8) 观测量数据面：开使能 → 拉电源信息 ──
        # set_observed_enable 用字段开关运控/传感器观测；
        # get_power_info 的 timeout 是微秒级新鲜度窗口（仅返回此窗口内的最新电源量）。
        def _on_obs(obs) -> None:
            pass  # 50Hz 观测帧，此处仅注册示意，不打印避免刷屏

        def _on_gps(gps) -> None:
            print(f"[gps] valid={gps.valid} "
                  f"point=({gps.point.lat:.6f},{gps.point.lng:.6f}) speed={gps.speed:.2f}")

        # set_observed_enable 返回当前实际生效的开关 dict（失败返回 None）
        state = client.set_observed_enable({"motionEnable": True, "sensorEnable": True})
        print(f"[obs] enabled, state={state}")
        client.set_motion_observed_callback(_on_obs)
        client.set_gps_callback(_on_gps)

        time.sleep(5)
        power = client.get_power_info(1_000_000)  # 1s 新鲜度窗口
        if power is not None:
            print(f"[power] level={power.power}% health={power.health} temper={power.temper:.1f} "
                  f"charge={power.charge_current:.2f}A/{power.charge_voltage:.2f}V")
        client.set_observed_enable({"motionEnable": False, "sensorEnable": False})

        # ── 9) 主动释放控制权 ──
        client.release_control()

        deadline = time.monotonic() + 3.0
        while client.get_state() != sdk.HighLevelState.kConnected:
            if _stop or time.monotonic() > deadline:
                break
            time.sleep(0.05)

    finally:
        # ── 10) 显式释放 —— 不依赖 GC，避免退出死锁 ──
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
