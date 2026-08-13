"""
Motion SDK — Python 包装层

命名风格：遵循 PEP 8 —— 方法 / 参数全部 snake_case。
对应的 C++ SDK 使用 camelCase，两端语义一一对应（仅风格不同）。
完整命名映射参见 ``uniubi-docs/docs/uniubi_high_level_sdk.md`` §6.1（高级）
与 ``uniubi-docs/docs/uniubi_low_level_sdk.md`` §6.1（低级）。

底层调用 pybind11 native 模块（``_uniubi_robot_motion_py_native``，私有，不要直接 import）。
"""

from __future__ import annotations

from typing import Callable, Optional

from . import _uniubi_robot_motion_py_native as _native  # noqa: F401  本地编译的 .so
MEDIA_ENABLED = bool(getattr(_native, "MEDIA_ENABLED", False))

if MEDIA_ENABLED:
    from .media_frame import (
        AudioEncode,
        AudioFrame,
        AudioFrameInfo,
        CMediaFrame,
        CMediaFrameView,
        EncodedVideoFrame,
        EncodedVideoFrameView,
        EncodedAudioFrameInfo,
        EncodedFrameInfo,
        EncodedVideoFrameInfo,
        FIRST_PKT,
        FrameType,
        IMU_FRAME_META_HEADER_SIZE,
        IMU_SAMPLE_SIZE,
        ImuCoordFrame,
        ImuFrameStatus,
        LAST_PKT,
        MediaBuffer,
        MediaBufferMetaType,
        MediaBufferView,
        MediaPixelFormat,
        StreamChange,
        StreamTrack,
        StreamType,
        VideoEncode,
        VideoFrame,
        VideoFrameInfo,
        VideoFramePlaneView,
        VideoFrameRowView,
        VideoStreamType,
        frame_bytes,
        frame_extra_bytes,
        frame_view,
        video_plane_view,
    )

# ---------------------------------------------------------------------------
#  枚举（直接复用 native 的）
# ---------------------------------------------------------------------------
LogLevel          = _native.LogLevel
LowLevelState     = _native.LowLevelState
LowLevelError     = _native.LowLevelError
HighLevelState    = _native.HighLevelState
HighLevelError    = _native.HighLevelError
MediaBusError     = _native.MediaBusError if MEDIA_ENABLED else None
MotionControlMode = _native.MotionControlMode  # 大脑/小脑运控模式
ButtonDefine      = _native.ButtonDefine       # TRCStickFrame.buttons 下标
AxesDefine        = _native.AxesDefine         # TRCStickFrame.axes 下标
GPSSignalLevel    = _native.GPSSignalLevel     # GPSFrame.level
GEOGCoordMode     = _native.GEOGCoordMode      # 坐标系类型
UWBPairState      = _native.UWBPairState       # UWBRawObserved.pairState
IMUDeviceErrno    = _native.IMUDeviceErrno     # Vector3f/Quaternionf.error 解码
MotorDeviceErrno  = _native.MotorDeviceErrno   # MotorObserved.error 解码


# ---------------------------------------------------------------------------
#  运动 SDK 数据结构（透传）
# ---------------------------------------------------------------------------
MotorCtrl              = _native.MotorCtrl
MotorCtrlAction        = _native.MotorCtrlAction
LowLevelMotionCmd      = _native.LowLevelMotionCmd
MotorObserved          = _native.MotorObserved
MotorInfo              = _native.MotorInfo
MotorLayout            = _native.MotorLayout
Vector3f               = _native.Vector3f
Quaternionf            = _native.Quaternionf
IMUObserved            = _native.IMUObserved
PowerObserved          = _native.PowerObserved
TRCStickFrame          = _native.TRCStickFrame
LowLevelMotionObserved = _native.LowLevelMotionObserved
MotionOdometry         = _native.MotionOdometry
MediaLayout            = _native.MediaLayout
SensorObserved         = _native.SensorObserved
GPSFrame               = _native.GPSFrame
GEOGPoint              = _native.GEOGPoint
UWBRawObserved         = _native.UWBRawObserved


# ---------------------------------------------------------------------------
#  BusService 单例的便利包装
# ---------------------------------------------------------------------------
class _URobotService:
    """全局 SDK 入口。App 启动时调用 `service.initial(file, client_id)` 一次。"""

    @staticmethod
    def version() -> str:
        """返回 SDK 版本号（如 "1.0.0"），任意时刻可调，无需先 initial()。"""
        return _native.MotionSdkService.version()

    @staticmethod
    def initial(config_file: str, client_id: str, timeout: int = 30) -> bool:
        """加载配置 + 初始化 UDBus DDS + RPC 客户端。重复调用返回 True。
        timeout：等待系统环境就绪的超时（秒，默认 30）；板内模式下 SDK 比系统先起时可能需要等待。
        """
        return _native.MotionSdkService.instance().initial_service(config_file, client_id, timeout)

    @staticmethod
    def set_log_callback(cb: Callable[[LogLevel, str], None]) -> None:
        """注册 SDK 日志回调；必须在 initial() 之前调用。
        cb(level: LogLevel, msg: str) —— 每条日志触发一次
        """
        _native.MotionSdkService.instance().set_log_callback(cb)

    @staticmethod
    def shutdown() -> None:
        _native.MotionSdkService.instance().shutdown()

    @staticmethod
    def is_multi_device() -> bool:
        """返回当前部署是否支持多设备（外部主机模式）。
        - False（板内）：直接 MotionHighLevelClient() 即可，无需发现
        - True（外部主机）：应先 set_discover_callback + discover_devices 后再 MotionHighLevelClient(sn)
        """
        return _native.MotionSdkService.instance().is_multi_device()

    @staticmethod
    def set_network_interface(iface: str) -> None:
        """指定 SDK 使用的网络接口（多设备/外部主机模式生效）。
        例如 "eth0" / "wlan0"，必须在 initial 之前调；
        空字符串 = 由 Cyclone DDS 自动选择接口
        """
        _native.MotionSdkService.instance().set_network_interface(iface)

    @staticmethod
    def set_discover_callback(cb: Callable[[str, str], None]) -> None:
        """注册设备发现回调（建议在 initial 之前调）。

        cb(sn: str, info_json: str) —— info_json 是设备详情 JSON 字符串，
        典型字段（调用方自行 json.loads）：

            {
              "version":      "...",   # 整机软件版本
              "brainVersion": "...",   # 大脑（高层算法）版本
              "deviceCP":     "...",   # 主控芯片标识
              "deviceModel":  "...",   # 设备型号
              "productDate":  "...",   # 出厂日期
              "network":      { "ether": {...}, "hotspot": {...},
                                "mobile": {...}, "wlan": {...} }
            }

        设备版本演进可能新增字段；遇未知字段宽容透传。
        """
        _native.MotionSdkService.instance().set_discover_callback(cb)

    @staticmethod
    def discover_devices(timeout_ms: int = 10000) -> bool:
        """主动发起一次设备发现（非阻塞）。
        - 当前已有发现窗口未过期 → 延长窗口到至少 timeout_ms
        - 窗口已过期 → 开新窗口
        发现窗口内收到的每条机器人响应都会通过 set_discover_callback 注册的回调上抛。
        """
        return _native.MotionSdkService.instance().discover_devices(timeout_ms)


service = _URobotService()


# ---------------------------------------------------------------------------
#  MediaBusClient
# ---------------------------------------------------------------------------
class MediaBusClient:
    """音视频帧订阅客户端。

    由 MotionLowLevelClient.create_media_bus_client() / MotionHighLevelClient.create_media_bus_client()
    工厂分配，不要直接构造。

    生命周期：
        media = client.create_media_bus_client()
        media.setup()
        layout = media.get_media_layout()             # 摄像头 / 麦克风 / 编码器数量
        media.start_raw_video_frame(0, on_video)      # on_video(channel, VideoFrame)
        media.start_encoded_video_frame(0, on_enc)    # on_enc(channel, EncodedVideoFrame)
        media.start_raw_audio_frame(0, on_audio)      # on_audio(channel, AudioFrame)
        ...
        media.stop_raw_video_frame(0)
        media.shutdown()
    """

    def __init__(self, impl) -> None:
        self._impl = impl

    def setup(self) -> bool:
        """初始化媒体总线连接（订阅前必须先调用）。"""
        return self._impl.setup()

    def shutdown(self) -> None:
        """断开媒体总线连接，停止所有订阅。"""
        self._impl.shutdown()

    def get_last_error(self) -> MediaBusError:
        """获取最后一次失败原因（MediaBusError）。"""
        return MediaBusError(self._impl.get_last_error())

    def get_media_layout(self) -> Optional[MediaLayout]:
        """查询媒体硬件布局，失败返回 None。

        Returns:
            MediaLayout（mic_num / camera_num / video_encoder_num）。
        """
        return self._impl.get_media_layout()

    # — 视频原始帧 —
    def start_raw_video_frame(self, channel: int, callback: Callable[[int, VideoFrame], None]) -> bool:
        """订阅视频原始帧。callback(channel, frame)，frame 为 MediaBus VideoFrame 格式。"""
        return self._impl.start_raw_video_frame(
            channel,
            lambda ch, frame: callback(ch, VideoFrame._from_native(frame)),
        )

    def stop_raw_video_frame(self, channel: int) -> bool:
        """停止订阅视频原始帧。"""
        return self._impl.stop_raw_video_frame(channel)

    # — 视频编码帧 —
    def start_encoded_video_frame(self, channel: int, callback: Callable[[int, EncodedVideoFrame], None]) -> bool:
        """订阅视频编码帧。callback(channel, frame)，frame 为 EncodedVideoFrame 格式。"""
        return self._impl.start_encoded_video_frame(
            channel,
            lambda ch, frame: callback(ch, EncodedVideoFrame._from_native(frame)),
        )

    def stop_encoded_video_frame(self, channel: int) -> bool:
        """停止订阅视频编码帧。"""
        return self._impl.stop_encoded_video_frame(channel)

    # — 音频原始帧 —
    def start_raw_audio_frame(self, channel: int, callback: Callable[[int, AudioFrame], None]) -> bool:
        """订阅音频原始帧。callback(channel, frame)，frame 为 MediaBus AudioFrame 格式。"""
        return self._impl.start_raw_audio_frame(
            channel,
            lambda ch, frame: callback(ch, AudioFrame._from_native(frame)),
        )

    def stop_raw_audio_frame(self, channel: int) -> bool:
        """停止订阅音频原始帧。"""
        return self._impl.stop_raw_audio_frame(channel)

    # — 上下文管理 —
    def __enter__(self) -> "MediaBusClient":
        return self

    def __exit__(self, *exc) -> None:
        self.shutdown()


# ---------------------------------------------------------------------------
#  MotionLowLevelClient
# ---------------------------------------------------------------------------
class MotionLowLevelClient:
    """低级控制模式客户端（板内单例）。

    生命周期：
        client = MotionLowLevelClient()
        client.set_connect_callback(cb)        # 可选
        client.connect(observed_hz=500)
        # 等到 state == kConnected 后显式开 motion 使能
        # （后续 set_motion_enable 内部异步处理，调用立即返回，state 由 worker 推进）
        client.set_motion_enable(True)
        cmd = LowLevelMotionCmd()
        cmd.action, cmd.ac_name = 1, "standing"
        client.send_control(action, cmd)       # state == kPrepared 时生效；cmd 填 action/ac_name
        client.set_motion_enable(False)
        client.disconnect()
    """

    def __init__(self) -> None:
        self._impl = _native.LowLevelClient()
        self._media_bus_client = None

    def create_media_bus_client(self) -> MediaBusClient:
        """创建（或复用）音视频帧订阅客户端。"""
        if not MEDIA_ENABLED:
            raise RuntimeError("MediaBus is not available in this SDK build")
        if self._media_bus_client is None:
            self._media_bus_client = MediaBusClient(self._impl.create_media_bus_client())
        return self._media_bus_client

    # — 状态 —
    def get_state(self) -> LowLevelState:
        return LowLevelState(self._impl.get_state())

    def get_last_error(self) -> LowLevelError:
        return LowLevelError(self._impl.get_last_error())

    def is_prepared(self) -> bool:
        return self.get_state() == LowLevelState.kPrepared

    # — 生命周期 —
    def connect(self, observed_hz: int = 500, lease_ms: int = 0) -> bool:
        """连接 MotionServer（非阻塞）。
        Args:
            observed_hz: 期望观测频率（Hz）
            lease_ms:    控制权租约时长（ms）；0 = server 默认。
                         server 按自身策略 clamp/校验后下发真实值，
                         SDK 内部按真实值算续约间隔（lease/3）。
        """
        return self._impl.connect(observed_hz, lease_ms)

    def disconnect(self) -> None:
        self._impl.disconnect()

    # — 控制 / 观测 —
    def set_motion_enable(self, enable: bool) -> bool:
        """切换运控使能状态（异步，调用立即返回）。

        - enable=True：请求开启，state 由 worker 推进至 kPrepared 后 send_control 才会被服务端采纳
        - enable=False：请求关闭，state 退回 kConnected
        - 调用方应通过 get_state() / on_connect 回调感知状态变化，不应依赖本方法返回值的"已生效"语义
        """
        return self._impl.set_motion_enable(enable)

    def send_control(self, action: MotorCtrlAction, cmd: Optional[LowLevelMotionCmd] = None) -> bool:
        """下发一帧低级控制。

        Args:
            action: 电机控制数据。
            cmd: 低级运控操作指令；动作相关控制帧建议填写 action/ac_name。
        """
        return self._impl.send_control(action, cmd)

    def send_max_torque(self, action: MotorCtrlAction) -> bool:
        """下发一帧最大扭矩设置，使用 action.motors[i].torque 表示目标最大扭矩。"""
        return self._impl.send_max_torque(action)

    def get_latest_observation(self, timeout_ms: int = 5) -> Optional[LowLevelMotionObserved]:
        """获取最近一帧运控观测（电机/IMU/TRC/电源），无新数据返回 None。

        Args:
            timeout_ms: 阻塞至多 timeout_ms（毫秒，默认 5ms）等服务端写入一帧**新**观测；
                        窗口内取到则返回，超时返回 None（不回退到旧缓存帧）。
        """
        return self._impl.get_latest_observation(timeout_ms)

    def get_sensor_observation(self, timeout_us: int = 5000) -> Optional[SensorObserved]:
        """获取最近一帧传感器观测（GPS + UWB），无新数据返回 None。

        Args:
            timeout_us: 阻塞至多 timeout_us（微秒，默认 5000us=5ms）轮询等一帧**新**传感器观测；
                        窗口内取到则返回，超时返回 None。（注意单位是 us，与 get_power_info 一致）
        """
        return self._impl.get_sensor_observation(timeout_us)

    def get_motor_layout(self, timeout_ms: int = 5000) -> Optional[MotorLayout]:
        """查询电机硬件布局（kConnected 后即可调用，SDK 内部缓存）。

        Returns:
            MotorLayout（motor_num + motors[i].limb_no/joint_no/name），失败返回 None。
        """
        return self._impl.get_motor_layout(timeout_ms)

    def emergency_stop(self, timeout_ms: int = 5000) -> bool:
        return self._impl.emergency_stop(timeout_ms)

    # — 运控模式（大脑/小脑）—
    def restore_motion_control_mode(self, timeout_ms: int = 5000) -> bool:
        """恢复运控模式到出厂模式。"""
        return self._impl.restore_motion_control_mode(timeout_ms)

    # — 回调 —
    def set_connect_callback(self, cb: Callable[[LowLevelState, LowLevelError], None]) -> None:
        """注册状态变化回调；每次 state 转换都会触发，参数 (state, error)。
        - state: 当前最新状态（kConnecting/kConnected/kPrepared/kConnectionLost/kDisconnected）
        - error: 本次变化的具体原因（kNone 表示无错误）
        """
        self._impl.set_connect_callback(cb)

    # — 装饰器风格（语法糖）—
    def on_connect(self, fn):
        self.set_connect_callback(fn)
        return fn

    # — 上下文管理 —
    def __enter__(self) -> "MotionLowLevelClient":
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()


# ---------------------------------------------------------------------------
#  MotionHighLevelClient
# ---------------------------------------------------------------------------
class MotionHighLevelClient:
    """高级控制模式客户端。

    生命周期：
        client = MotionHighLevelClient()                   # 板内单例
        client = MotionHighLevelClient("SN-ABC123")        # 多设备指定 SN（远端）
        client.set_connect_callback(cb)        # 可选，必须 connect 之前注册
        client.set_event_callback(cb)          # 可选，必须 connect 之前注册
        client.connect(lease_ms=60000)
        client.start_control()
        client.start_action("walking")
        client.start_audio_play({"list":[{"id":"1"}],"volume":50,"repeat":1})
        ...
        client.stop_action()
        client.release_control()
        client.disconnect()                    # 务必显式，避免 GC 死锁
    """

    def __init__(self, device_id: str = "", as_master: bool = False) -> None:
        """构造高级客户端。
        Args:
            device_id: 空 = 板内单例（按 as_master 协商主从）；非空 = 远端指定设备 SN。
            as_master: 板内模式下是否以 master 角色入会（device_id 为空时生效）。
        """
        self._impl = _native.HighLevelClient(device_id, as_master)
        self._media_bus_client = None

    def create_media_bus_client(self) -> MediaBusClient:
        """创建（或复用）音视频帧订阅客户端。"""
        if not MEDIA_ENABLED:
            raise RuntimeError("MediaBus is not available in this SDK build")
        if self._media_bus_client is None:
            self._media_bus_client = MediaBusClient(self._impl.create_media_bus_client())
        return self._media_bus_client

    # — 状态 —
    def get_state(self) -> HighLevelState:
        return HighLevelState(self._impl.get_state())

    def get_last_error(self) -> HighLevelError:
        return HighLevelError(self._impl.get_last_error())

    def is_controlled(self) -> bool:
        return self.get_state() == HighLevelState.kControlled

    # — 生命周期 —
    def connect(self, lease_ms: int = 0) -> bool:
        """进入高级模式。lease_ms<=0 时 SDK 默认 60000ms。"""
        return self._impl.connect(lease_ms)

    def disconnect(self) -> None:
        self._impl.disconnect()

    def start_control(self, timeout_ms: int = 10000) -> bool:
        return self._impl.start_control(timeout_ms)

    def release_control(self) -> bool:
        return self._impl.release_control()

    # — 运控动作 —
    def start_action(self, action: str, params: Optional[dict] = None, timeout_ms: int = 5000) -> bool:
        """启动高级动作（必须先 start_control）。

        Args:
            action: 动作名，如 "walking" / "bipedStand" / "handstand" / "laying"
                    / "standing" / "jumpFrontflip" / "jumpSideflip" / "jumpBackflip"
            params: 动作参数 dict；字段以 get_motion_capabilities() 返回的 params 为准，
                    walking 常用 {"lineVelocityX","lineVelocityY","velocity"}；
                    一次性动作（如 jumpBackflip）传 None 即可
            timeout_ms: RPC 超时
        """
        return self._impl.start_action(action, params, timeout_ms)

    def stop_action(self, timeout_ms: int = 5000) -> bool:
        return self._impl.stop_action(timeout_ms)

    def set_action_params(self, params: Optional[dict] = None, timeout_ms: int = 5000) -> bool:
        """修改当前动作参数（不切动作），全量重写语义（未传字段归 0）。
        字段以 get_motion_capabilities() 返回的当前动作 params 为准，
        walking 常用 {"lineVelocityX","lineVelocityY","velocity"}。
        """
        return self._impl.set_action_params(params, timeout_ms)

    def emergency_stop(self, timeout_ms: int = 5000) -> bool:
        return self._impl.emergency_stop(timeout_ms)

    def recovery_stand(self, timeout_ms: int = 5000) -> bool:
        """从倒地/异常姿态恢复站立。"""
        return self._impl.recovery_stand(timeout_ms)

    def damp(self, timeout_ms: int = 5000) -> bool:
        """进入阻尼模式（关节缓慢下沉）。"""
        return self._impl.damp(timeout_ms)

    def stand_up(self, timeout_ms: int = 5000) -> bool:
        """站起。"""
        return self._impl.stand_up(timeout_ms)

    def lie_down(self, timeout_ms: int = 5000) -> bool:
        """趴下。"""
        return self._impl.lie_down(timeout_ms)

    def move(self, vx: float, vy: float, vyaw: float, timeout_ms: int = 5000) -> bool:
        """速度控制行走。vx/vy 为线速度，vyaw 为偏航角速度。"""
        return self._impl.move(vx, vy, vyaw, timeout_ms)

    # — 查询 —
    def query_motion_state(self, timeout_ms: int = 5000) -> Optional[dict]:
        """查询当前运控状态。任何已 connect 状态均可。"""
        return self._impl.query_motion_state(timeout_ms)

    def get_motion_capabilities(self, timeout_ms: int = 5000) -> Optional[dict]:
        """查询服务端运控能力（支持的高级动作集合等）。"""
        return self._impl.get_motion_capabilities(timeout_ms)

    def query_system_status(self, timeout_ms: int = 5000) -> Optional[dict]:
        """查询系统状态详情，返回 {battery, network} 子对象。"""
        return self._impl.query_system_status(timeout_ms)

    def get_motor_layout(self, timeout_ms: int = 5000) -> Optional[MotorLayout]:
        """查询电机硬件布局（SDK 内部缓存），失败返回 None。"""
        return self._impl.get_motor_layout(timeout_ms)

    # — 观测量数据面 —
    def set_observed_enable(self, params: Optional[dict] = None, timeout_ms: int = 5000) -> Optional[dict]:
        """开/停观测量上报。

        Args:
            params: dict，字段：
                {"motionEnable": bool, "sensorEnable": bool}
                - motionEnable：开启后 50Hz 推送运控观测（IMU+电机+电源），经
                  set_motion_observed_callback 回调上抛。
                - sensorEnable：开启后推送完整传感器观测（GPS、UWB、odom），经
                  set_sensor_observed_callback 回调上抛。
            timeout_ms: RPC 超时

        Returns:
            成功返回当前实际生效的观测开关 dict（如 {"motionEnable": True, "sensorEnable": False}），
            失败返回 None（get_last_error() 取错误码）。
        """
        return self._impl.set_observed_enable(params, timeout_ms)

    def get_power_info(self, timeout_us: int = 5000) -> Optional[PowerObserved]:
        """获取电源观测（电量/健康度/温度/充电电流电压）。

        Args:
            timeout_us: 数据新鲜度窗口（微秒）；仅当最近 timeout_us 内有数据才返回，
                        否则返回 None。
        """
        return self._impl.get_power_info(timeout_us)

    def get_sensor_observation(self, timeout_ms: int = 5000) -> Optional[SensorObserved]:
        """获取完整传感器观测，包含 GPS、UWB 和 ``odom``。

        ``timeout_ms`` 是数据新鲜度窗口；该方法只读缓存，不发送 RPC，也不申请控制权。
        """
        return self._impl.get_sensor_observation(timeout_ms)

    def set_motion_observed_callback(self, cb: Callable[[LowLevelMotionObserved], None]) -> None:
        """注册运控观测回调；需先 set_observed_enable({"motionEnable": True})。
        cb(observed: LowLevelMotionObserved) —— 每帧触发一次。
        """
        self._impl.set_motion_observed_callback(cb)

    def set_sensor_observed_callback(self, cb: Callable[[SensorObserved], None]) -> None:
        """注册完整传感器观测回调；需开启 ``sensorEnable``。

        回调参数包含 GPS、UWB 和 ``odom``。
        """
        self._impl.set_sensor_observed_callback(cb)

    # — 音频播放器 —
    def start_audio_play(self, params: dict, timeout_ms: int = 5000) -> bool:
        """启动/调参/恢复/改重复次数 —— 按 params 字段决定语义：
            1) 启动播放列表：{"list":[{"id":"1"},{"id":"2"}], "volume":50, "repeat":1}
            2) 调音量：{"volume":50}
            3) 恢复播放：{"resume":true}
            4) 修改重复次数：{"repeat":-1}（-1=无限循环；>0=次数；0 无意义）
        """
        return self._impl.start_audio_play(params, timeout_ms)

    def stop_audio_play(self, timeout_ms: int = 5000) -> bool:
        """停止播放。"""
        return self._impl.stop_audio_play(timeout_ms)

    def pause_audio_play(self, timeout_ms: int = 5000) -> bool:
        """暂停播放；恢复用 start_audio_play({"resume": True})."""
        return self._impl.pause_audio_play(timeout_ms)

    def add_audio_file(self, params: dict, timeout_ms: int = 30000) -> bool:
        """新增音频文件。

        params 支持本地文件或 URL 两种形态：
            {"id": "custom_1", "name": "hello.mp3", "file": "/data/hello.mp3"}
            {"id": "custom_1", "name": "hello.mp3", "url": "http://host/hello.mp3"}
        """
        return self._impl.add_audio_file(params, timeout_ms)

    def delete_audio_file(self, params: dict, timeout_ms: int = 5000) -> bool:
        """删除音频文件。params 形如 {"id": "1"}."""
        return self._impl.delete_audio_file(params, timeout_ms)

    def query_audio_play_detail(self, timeout_ms: int = 5000) -> Optional[dict]:
        """查询当前播放详情。"""
        return self._impl.query_audio_play_detail(timeout_ms)

    def query_audio_play_list(self, params: Optional[dict] = None, timeout_ms: int = 5000) -> Optional[dict]:
        """查询音频文件列表。params 形如 {"type": "customVoice"}."""
        return self._impl.query_audio_play_list(params, timeout_ms)

    # — 灯光 —
    def get_camera_light_brightness(self, timeout_ms: int = 5000) -> Optional[dict]:
        """查询摄像头前灯控制状态和亮度，返回 dict（失败返回 None）。"""
        return self._impl.get_camera_light_brightness(timeout_ms)

    def set_camera_light_brightness(self, brightness: int, timeout_ms: int = 5000) -> bool:
        """摄像头前灯亮度控制，brightness=0~100。"""
        return self._impl.set_camera_light_brightness(brightness, timeout_ms)

    # — 回调 —
    def set_connect_callback(self, cb: Callable[[HighLevelState, HighLevelError], None]) -> None:
        """控制权状态变化回调，参数 (state, error)：
            - (Controlled,   None)              start_control 成功
            - (Connected,    None)              自己 release 完成
            - (Connected,    RpcAcquireRejected) start_control 整体超时
            - (Connected,    SessionExpired)    lease 到期
            - (Connected,    SessionRevoked)    被另一方接管
        """
        self._impl.set_connect_callback(cb)

    def on_connect(self, fn):
        self.set_connect_callback(fn)
        return fn

    def set_event_callback(self, cb: Callable[[str, str], None]) -> None:
        """服务端业务事件回调，参数 (topic, payload_json)：
            - "statistics/play_list"     播放状态变化
            - "statistics/device_status" 设备状态变化（电池/网络）
        payload_json 为 UTF-8 JSON 字符串，调用方按需 json.loads()。
        """
        self._impl.set_event_callback(cb)

    def on_event(self, fn):
        self.set_event_callback(fn)
        return fn

    # — 上下文管理 —
    def __enter__(self) -> "MotionHighLevelClient":
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()


# ---------------------------------------------------------------------------
#  顶层便捷函数
# ---------------------------------------------------------------------------
def version() -> str:
    """返回 SDK 版本号。"""
    return service.version()


def initial_service(config_file: str, client_id: str, timeout: int = 30) -> bool:
    """初始化 SDK（等价 service.initial）。"""
    return service.initial(config_file, client_id, timeout)


def create_low_level_client() -> MotionLowLevelClient:
    """创建低级控制客户端（板内单例）。"""
    return MotionLowLevelClient()


def create_high_level_client(device_id: str = "", as_master: bool = False) -> MotionHighLevelClient:
    """创建高级控制客户端。
    device_id 空 = 板内单例（按 as_master 协商主从）；非空 = 远端指定设备 SN。
    """
    return MotionHighLevelClient(device_id, as_master)


__all__ = [
    "service",
    "MEDIA_ENABLED",
    "version", "initial_service",
    "create_low_level_client", "create_high_level_client",
    "MotionLowLevelClient", "MotionHighLevelClient",
    "LowLevelState", "LowLevelError",
    "HighLevelState", "HighLevelError",
    "MotionControlMode",
    "ButtonDefine", "AxesDefine", "GPSSignalLevel", "GEOGCoordMode", "UWBPairState",
    "IMUDeviceErrno", "MotorDeviceErrno",
    "MotorCtrl", "MotorCtrlAction", "LowLevelMotionCmd", "MotorObserved",
    "MotorInfo", "MotorLayout",
    "Vector3f", "Quaternionf", "IMUObserved", "PowerObserved", "TRCStickFrame",
    "LowLevelMotionObserved", "MotionOdometry",
    "MediaLayout", "SensorObserved", "GPSFrame", "GEOGPoint", "UWBRawObserved",
]

if MEDIA_ENABLED:
    __all__ += [
        "MediaBusClient",
        "MediaBusError",
        "MediaPixelFormat", "VideoStreamType", "VideoEncode", "AudioEncode",
        "MediaBufferMetaType", "ImuCoordFrame", "ImuFrameStatus",
        "StreamType", "StreamTrack", "FrameType", "StreamChange",
        "FIRST_PKT", "LAST_PKT", "IMU_FRAME_META_HEADER_SIZE", "IMU_SAMPLE_SIZE",
        "MediaBuffer", "MediaBufferView", "CMediaFrameView", "EncodedVideoFrameView",
        "VideoFrameInfo", "AudioFrameInfo",
        "EncodedVideoFrameInfo", "EncodedAudioFrameInfo", "EncodedFrameInfo",
        "VideoFrame", "CMediaFrame", "EncodedVideoFrame", "AudioFrame",
        "VideoFramePlaneView", "VideoFrameRowView",
        "frame_bytes", "frame_extra_bytes", "frame_view", "video_plane_view",
    ]
