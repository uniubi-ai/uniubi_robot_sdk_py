/**
 * ========================================================
 *  @file MotionSdkPython.cpp
 *  @brief  Motion SDK pybind11 绑定
 *  @author shangyang
 *  @date 2026-05-07
 *  @details
 *      把 C++ SDK 暴露为 Python 模块 robot_motion_sdk._uniubi_robot_motion_py_native。
 *      上层 Pythonic API 由 robot_motion_sdk/__init__.py 包装。
 *  @copyright Copyright (c) 2026 UNIUBI All rights reserved.
 * ========================================================
 */

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#ifndef UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
#define UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA 1
#endif

#if UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
#include "uniubi/robot_sdk/Media/MediaBuffer.h"
#include "uniubi/robot_sdk/Media/MediaFrame.h"
#include "MediaFrameBindings.h"
#endif
#include "uniubi/robot_sdk/MotionSdkService.h"
#include "uniubi/robot_sdk/MediaBusClient.h"
#include "uniubi/robot_sdk/MotionLowLevelClient.h"
#include "uniubi/robot_sdk/MotionHighLevelClient.h"

namespace py = pybind11;
using namespace uniubi::RobotSdk;

namespace {

/// Python 对象 ↔ JSON 字符串：复用 stdlib json 模块，零额外依赖
std::string pyToJsonString(const py::object& obj) {
    if (obj.is_none()) return std::string();
    py::module_ json = py::module_::import("json");
    return json.attr("dumps")(obj).cast<std::string>();
}

py::object jsonStringToPy(const std::string& s) {
    if (s.empty()) return py::none();
    py::module_ json = py::module_::import("json");
    return json.attr("loads")(s);
}

using PyCallback = std::shared_ptr<py::function>;

PyCallback makePyCallback(py::function cb) {
    return PyCallback(new py::function(std::move(cb)), [](py::function* callback) {
        py::gil_scoped_acquire g;
        delete callback;
    });
}

}

PYBIND11_MODULE(_uniubi_robot_motion_py_native, m) {
    m.doc() = "UU Robot Motion SDK native bindings (pybind11)";
    m.attr("MEDIA_ENABLED") = py::bool_(UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA != 0);

    /// ───────────────────────────────────────────────────────
    /// IMotionSdkService 日志级别枚举
    /// ───────────────────────────────────────────────────────
    py::enum_<IMotionSdkService::LogLevel>(m, "LogLevel")
        .value("kLogDebug", IMotionSdkService::kLogDebug)
        .value("kLogTrace", IMotionSdkService::kLogTrace)
        .value("kLogInfo",  IMotionSdkService::kLogInfo)
        .value("kLogWarn",  IMotionSdkService::kLogWarn)
        .value("kLogError", IMotionSdkService::kLogError)
        .value("kLogFatal", IMotionSdkService::kLogFatal)
        .export_values();

    /// ───────────────────────────────────────────────────────
    /// IMotionSdkService（单例，仅暴露公开接口）
    /// ───────────────────────────────────────────────────────
    py::class_<IMotionSdkService, std::unique_ptr<IMotionSdkService, py::nodelete>>(m, "MotionSdkService")
        .def_static("version", &IMotionSdkService::version,
                    "Return SDK version string, e.g. '1.0.0 (commit <sha>)'")
        .def_static("instance", &IMotionSdkService::instance,
                    py::return_value_policy::reference)
        .def("initial_service", &IMotionSdkService::initialService,
             py::arg("file"), py::arg("server"), py::arg("timeout_ms") = 30000,
             py::call_guard<py::gil_scoped_release>())
        .def("set_log_callback", [](IMotionSdkService& self, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setLogCallback([callback](IMotionSdkService::LogLevel level, const char* msg, int32_t length) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(level, py::str(msg, length)); }
                    catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        .def("shutdown", &IMotionSdkService::shutdown,
             py::call_guard<py::gil_scoped_release>())
        .def("is_multi_device", &IMotionSdkService::isMultiDevice,
             "Return True if current deployment supports multiple robots (external host mode)")
        .def("set_network_interface", [](IMotionSdkService& self, const std::string& iface) {
                self.setNetworkInterface(iface.c_str());
            },
            py::arg("iface"),
            "Specify network interface (e.g. 'eth0' / 'wlan0') for multi-device/remote mode; "
            "must be called before initial. Empty string = let Cyclone DDS auto-select")
        .def("set_discover_callback", [](IMotionSdkService& self, py::function cb) {
                if (!cb) {
                    self.setDiscoverCallback(nullptr);
                    return;
                }
                PyCallback callback = makePyCallback(std::move(cb));
                self.setDiscoverCallback([callback](const std::string& sn, const std::string& infoJson) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(sn, infoJson); }
                    catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        .def("discover_devices", [](IMotionSdkService& self, uint32_t timeoutMs) {
                py::gil_scoped_release rel;
                return self.discoverDevices(timeoutMs);
            },
             py::arg("timeout_ms") = 10000,
             "Non-blocking discovery: publish a request and extend/restart the discovery window; responses fire DeviceDiscover callback asynchronously");

    /// 运控模式（大脑/小脑），Low/High 两端共用同一组取值
    py::enum_<MotionControlMode>(m, "MotionControlMode")
        .value("cerebellumMode",     cerebellumMode)
        .value("brainControlMode",   brainControlMode)
        .value("motionModeNotReady", motionModeNotReady)
        .export_values();

    py::enum_<ButtonDefine>(m, "ButtonDefine")
        .value("buttonBack",  buttonBack)
        .value("buttonStart", buttonStart)
        .value("buttonLB",    buttonLB)
        .value("buttonRB",    buttonRB)
        .value("buttonF1",    buttonF1)
        .value("buttonF2",    buttonF2)
        .value("buttonA",     buttonA)
        .value("buttonB",     buttonB)
        .value("buttonX",     buttonX)
        .value("buttonY",     buttonY)
        .value("buttonUp",    buttonUp)
        .value("buttonDown",  buttonDown)
        .value("buttonLeft",  buttonLeft)
        .value("buttonRight", buttonRight)
        .value("buttonLS",    buttonLS)
        .value("buttonRS",    buttonRS)
        .value("BUTTON_MAX",  BUTTON_MAX)
        .export_values();

    py::enum_<AxesDefine>(m, "AxesDefine")
        .value("axesLX",   axesLX)
        .value("axesLY",   axesLY)
        .value("axesRX",   axesRX)
        .value("axesRY",   axesRY)
        .value("axesLT",   axesLT)
        .value("axesRT",   axesRT)
        .value("AXES_MAX", AXES_MAX)
        .export_values();

    py::enum_<GPSSignalLevel>(m, "GPSSignalLevel")
        .value("gpsGre38db", gpsGre38db)
        .value("gpsGre30db", gpsGre30db)
        .value("gpsLes30db", gpsLes30db)
        .export_values();

    py::enum_<GEOGCoordMode>(m, "GEOGCoordMode")
        .value("gcj02",  gcj02)
        .value("wgs84",  wgs84)
        .value("bd09",   bd09)
        .value("mapBar", mapBar)
        .export_values();

    py::enum_<UWBPairState>(m, "UWBPairState")
        .value("uwbPairNone",    uwbPairNone)
        .value("uwbInPairing",   uwbInPairing)
        .value("uwbPairSuccess", uwbPairSuccess)
        .value("uwbPairFailed",  uwbPairFailed)
        .export_values();

    py::enum_<IMUDeviceErrno>(m, "IMUDeviceErrno")
        .value("imuNormal",           imuNormal)
        .value("imuInvalid",          imuInvalid)
        .value("imuControlOffline",   imuControlOffline)
        .value("imuControlNotReady",  imuControlNotReady)
        .value("imuControlUpgrade",   imuControlUpgrade)
        .value("imuControlNotParams", imuControlNotParams)
        .value("imuNotReady",         imuNotReady)
        .export_values();

    py::enum_<MotorDeviceErrno>(m, "MotorDeviceErrno")
        .value("motorNormal",          motorNormal)
        .value("motorPreDriver",       motorPreDriver)
        .value("motorEcodeError",      motorEcodeError)
        .value("motorOverSpeed",       motorOverSpeed)
        .value("motorOverTempe",       motorOverTempe)
        .value("motorOverCurrent",     motorOverCurrent)
        .value("motorOverVoltage",     motorOverVoltage)
        .value("motorPGAbnormality",   motorPGAbnormality)
        .value("motorHWUndervoltage",  motorHWUndervoltage)
        .value("motorCommError",      motorCommError)
        .value("motorControlOffline",  motorControlOffline)
        .value("controlMotorNotEnable",controlMotorNotEnable)
        .value("motorControlNotReady", motorControlNotReady)
        .value("motorControlUpgrade",  motorControlUpgrade)
        .value("motorNoCalibrated",    motorNoCalibrated)
        .value("motorURDFNotMapped",   motorURDFNotMapped)
        .export_values();

#if UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
    bindMediaFrameTypes(m);
#endif

    /// ───────────────────────────────────────────────────────
    /// 通用数据结构
    /// ───────────────────────────────────────────────────────
    py::class_<MediaLayout>(m, "MediaLayout")
        .def(py::init<>())
        .def_readonly("mic_num",           &MediaLayout::micNum)
        .def_readonly("camera_num",        &MediaLayout::cameraNum)
        .def_readonly("video_encoder_num", &MediaLayout::videoEncoderNum);

    py::class_<MotorCtrl>(m, "MotorCtrl")
        .def(py::init<>())
        .def_readwrite("position", &MotorCtrl::position)
        .def_readwrite("velocity", &MotorCtrl::velocity)
        .def_readwrite("kp_gain",  &MotorCtrl::kpGain)
        .def_readwrite("kd_gain",  &MotorCtrl::kdGain)
        .def_readwrite("torque",   &MotorCtrl::torque)
        .def_property("limb_no",
            [](const MotorCtrl& m) { return m.header.limbNo; },
            [](MotorCtrl& m, uint16_t v) { m.header.limbNo = v; })
        .def_property("joint_no",
            [](const MotorCtrl& m) { return m.header.jointNo; },
            [](MotorCtrl& m, uint16_t v) { m.header.jointNo = v; });

    py::class_<MotorCtrlAction>(m, "MotorCtrlAction")
        .def(py::init<>())
        .def_readwrite("motor_num", &MotorCtrlAction::motorNum)
        .def_property("motors",
            [](const MotorCtrlAction& a) {
                py::list lst;
                uint32_t n = a.motorNum > kLowLevelMaxMotorNum ? kLowLevelMaxMotorNum : a.motorNum;
                for (uint32_t i = 0; i < n; ++i) lst.append(a.motors[i]);
                return lst;
            },
            [](MotorCtrlAction& a, const py::list& lst) {
                size_t n = lst.size();
                if (n > kLowLevelMaxMotorNum) n = kLowLevelMaxMotorNum;
                a.motorNum = static_cast<uint32_t>(n);
                for (size_t i = 0; i < n; ++i) a.motors[i] = lst[i].cast<MotorCtrl>();
            });

    py::class_<LowLevelMotionCmd>(m, "LowLevelMotionCmd")
        .def(py::init<>())
        .def_readwrite("action",     &LowLevelMotionCmd::action)
        .def_property("ac_name",
            [](const LowLevelMotionCmd& cmd) {
                return std::string(cmd.acName, ::strnlen(cmd.acName, sizeof(cmd.acName)));
            },
            [](LowLevelMotionCmd& cmd, const std::string& name) {
                std::memset(cmd.acName, 0, sizeof(cmd.acName));
                std::strncpy(cmd.acName, name.c_str(), sizeof(cmd.acName) - 1);
            })
        .def_readwrite("velocity",   &LowLevelMotionCmd::velocity)
        .def_readwrite("velocity_x", &LowLevelMotionCmd::velocityX)
        .def_readwrite("velocity_y", &LowLevelMotionCmd::velocityY);

    py::class_<MotorInfo>(m, "MotorInfo")
        .def_readonly("limb_no",  &MotorInfo::limbNo)
        .def_readonly("joint_no", &MotorInfo::jointNo)
        .def_property_readonly("name", [](const MotorInfo& mi) {
            return std::string(mi.name, ::strnlen(mi.name, sizeof(mi.name)));
        });

    py::class_<MotorLayout>(m, "MotorLayout")
        .def(py::init<>())
        .def_readonly("motor_num", &MotorLayout::motorNum)
        .def_property_readonly("motors", [](const MotorLayout& l) {
            py::list lst;
            uint32_t n = l.motorNum > kLowLevelMaxMotorNum ? kLowLevelMaxMotorNum : l.motorNum;
            for (uint32_t i = 0; i < n; ++i) lst.append(l.motors[i]);
            return lst;
        });

    py::class_<MotorObserved>(m, "MotorObserved")
        .def_readonly("enable",    &MotorObserved::enable)
        .def_readonly("online",    &MotorObserved::online)
        .def_readonly("error",     &MotorObserved::error)
        .def_readonly("position",  &MotorObserved::position)
        .def_readonly("velocity",  &MotorObserved::velocity)
        .def_readonly("torque",    &MotorObserved::torque)
        .def_readonly("temp",      &MotorObserved::temp)
        .def_readonly("voltage",   &MotorObserved::voltage)
        .def_readonly("loss_rate", &MotorObserved::lossRate)
        .def_readonly("max_torque",&MotorObserved::maxTorque)
        .def_property_readonly("limb_no",  [](const MotorObserved& m) { return m.header.limbNo; })
        .def_property_readonly("joint_no", [](const MotorObserved& m) { return m.header.jointNo; });

    py::class_<Vector3f>(m, "Vector3f")
        .def_readonly("error", &Vector3f::error)
        .def_readonly("x",     &Vector3f::x)
        .def_readonly("y",     &Vector3f::y)
        .def_readonly("z",     &Vector3f::z);

    py::class_<Quaternionf>(m, "Quaternionf")
        .def_readonly("error", &Quaternionf::error)
        .def_readonly("w",     &Quaternionf::w)
        .def_readonly("x",     &Quaternionf::x)
        .def_readonly("y",     &Quaternionf::y)
        .def_readonly("z",     &Quaternionf::z);

    py::class_<IMUObserved>(m, "IMUObserved")
        .def_readonly("temp",       &IMUObserved::temp)
        .def_readonly("accel",      &IMUObserved::accel)
        .def_readonly("gyro",       &IMUObserved::gyro)
        .def_readonly("mag",        &IMUObserved::mag)
        .def_readonly("euler",      &IMUObserved::euler)
        .def_readonly("quaternion", &IMUObserved::quaternion);

    py::class_<PowerObserved>(m, "PowerObserved")
        .def(py::init<>())
        .def_readonly("power",          &PowerObserved::power)
        .def_readonly("health",         &PowerObserved::health)
        .def_readonly("temper",         &PowerObserved::temper)
        .def_readonly("charge_current", &PowerObserved::chargeCurrent)
        .def_readonly("charge_voltage", &PowerObserved::chargeVoltage);

    py::class_<GEOGPoint>(m, "GEOGPoint")
        .def_readonly("lat", &GEOGPoint::lat)
        .def_readonly("lng", &GEOGPoint::lng);

    py::class_<GPSFrame>(m, "GPSFrame")
        .def_readonly("valid", &GPSFrame::valid)
        .def_readonly("speed", &GPSFrame::speed)
        .def_readonly("level", &GPSFrame::level)
        .def_readonly("rssi",  &GPSFrame::rssi)
        .def_readonly("point", &GPSFrame::point);

    py::class_<UWBRawObserved>(m, "UWBRawObserved")
        .def_readonly("valid",      &UWBRawObserved::valid)
        .def_readonly("pair_state", &UWBRawObserved::pairState)
        .def_readonly("rssi",       &UWBRawObserved::rssi)
        .def_readonly("pitch",      &UWBRawObserved::pitch)
        .def_readonly("azimuth",    &UWBRawObserved::azimuth)
        .def_readonly("distance",   &UWBRawObserved::distance);

    py::class_<SensorObserved>(m, "SensorObserved")
        .def(py::init<>())
        .def_readonly("gps", &SensorObserved::gps)
        .def_readonly("uwb", &SensorObserved::uwb)
        .def_readonly("odom", &SensorObserved::odom);

    py::class_<TRCStickFrame>(m, "TRCStickFrame")
        .def(py::init<>())
        .def_readwrite("valid",      &TRCStickFrame::valid)
        .def_readwrite("control_id", &TRCStickFrame::controlId)
        .def_property("buttons",
            [](const TRCStickFrame& f) {
                py::list lst;
                for (int i = 0; i < BUTTON_MAX; ++i) lst.append(f.buttons[i]);
                return lst;
            },
            [](TRCStickFrame& f, const py::list& lst) {
                size_t n = lst.size();
                if (n > BUTTON_MAX) n = BUTTON_MAX;
                for (size_t i = 0; i < n; ++i) f.buttons[i] = lst[i].cast<uint8_t>();
                for (size_t i = n; i < BUTTON_MAX; ++i) f.buttons[i] = 0;
            })
        .def_property("axes",
            [](const TRCStickFrame& f) {
                py::list lst;
                for (int i = 0; i < AXES_MAX; ++i) lst.append(f.axes[i]);
                return lst;
            },
            [](TRCStickFrame& f, const py::list& lst) {
                size_t n = lst.size();
                if (n > AXES_MAX) n = AXES_MAX;
                for (size_t i = 0; i < n; ++i) f.axes[i] = lst[i].cast<float>();
                for (size_t i = n; i < AXES_MAX; ++i) f.axes[i] = 0.0f;
            });

    py::class_<LowLevelMotionObserved>(m, "LowLevelMotionObserved")
        .def_readonly("system_sta", &LowLevelMotionObserved::systemSta)
        .def_readonly("motor_num", &LowLevelMotionObserved::motorNum)
        .def_readonly("imu",       &LowLevelMotionObserved::imu)
        .def_readonly("trc",       &LowLevelMotionObserved::trc)
        .def_readonly("power",     &LowLevelMotionObserved::power)
        .def_property_readonly("motors", [](const LowLevelMotionObserved& o) {
            py::list lst;
            uint32_t n = o.motorNum > kLowLevelMaxMotorNum ? kLowLevelMaxMotorNum : o.motorNum;
            for (uint32_t i = 0; i < n; ++i) lst.append(o.motors[i]);
            return lst;
        });

    py::class_<MotionOdometry>(m,"MotionOdometry")
        .def(py::init<>())
        .def_property_readonly("position",[](const MotionOdometry& odometry) {
            return py::make_tuple(odometry.position[0],odometry.position[1],odometry.position[2]);
        })
        .def_property_readonly("velocity",[](const MotionOdometry& odometry) {
            return py::make_tuple(odometry.velocity[0],odometry.velocity[1],odometry.velocity[2]);
        })
        .def_readonly("yaw",&MotionOdometry::yaw)
        .def_readonly("yaw_speed",&MotionOdometry::yawSpeed)
        .def_readonly("epoch",&MotionOdometry::epoch)
        .def_property_readonly("valid",[](const MotionOdometry& odometry) {return odometry.valid != 0;});

    /// ───────────────────────────────────────────────────────
    /// MediaBusClient（音视频帧订阅；由 *Client.create_media_bus_client() 工厂分配）
    /// ───────────────────────────────────────────────────────
#if UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
    py::enum_<IMediaBusClient::MediaBusError>(m, "MediaBusError")
        .value("kNone",             IMediaBusClient::kNone)
        .value("kNotSetup",         IMediaBusClient::kNotSetup)
        .value("kConfigLoadFailed", IMediaBusClient::kConfigLoadFailed)
        .value("kConfigInvalid",    IMediaBusClient::kConfigInvalid)
        .value("kMediaInitFailed",  IMediaBusClient::kMediaInitFailed)
        .value("kMediaStartFailed", IMediaBusClient::kMediaStartFailed)
        .value("kInvalidChannel",   IMediaBusClient::kInvalidChannel)
        .value("kInvalidCallback",  IMediaBusClient::kInvalidCallback)
        .value("kSourceUnavailable",IMediaBusClient::kSourceUnavailable)
        .value("kSourceStartFailed",IMediaBusClient::kSourceStartFailed)
        .export_values();

    py::class_<IMediaBusClient, std::shared_ptr<IMediaBusClient>>(m, "MediaBusClient")
        .def("setup",    &IMediaBusClient::setup,
             py::call_guard<py::gil_scoped_release>())
        .def("shutdown", &IMediaBusClient::shutdown,
             py::call_guard<py::gil_scoped_release>())
        .def("get_last_error", &IMediaBusClient::getLastError)
        .def("get_media_layout", [](IMediaBusClient& self) -> py::object {
                MediaLayout layout = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getMediaLayout(layout);
                }
                if (!ok) return py::none();
                return py::cast(layout);
            })
        .def("start_raw_video_frame", [](IMediaBusClient& self, int32_t channel, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                return self.startRawVideoFrame(channel, [callback](int32_t ch, const VideoFrame& frame) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(ch, frame); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            }, py::arg("channel"), py::arg("callback"))
        .def("stop_raw_video_frame", &IMediaBusClient::stopRawVideoFrame, py::arg("channel"))
        .def("start_raw_audio_frame", [](IMediaBusClient& self, int32_t channel, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                return self.startRawAudioFrame(channel, [callback](int32_t ch, const AudioFrame& frame) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(ch, frame); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            }, py::arg("channel"), py::arg("callback"))
        .def("stop_raw_audio_frame", &IMediaBusClient::stopRawAudioFrame, py::arg("channel"))
        .def("start_encoded_video_frame", [](IMediaBusClient& self, int32_t channel, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                return self.startEncodedVideoFrame(channel, [callback](int32_t ch, const EncodedVideoFrame& frame) {
                    py::gil_scoped_acquire g;
                    try {
                        EncodedVideoFrame copy(frame);
                        (*callback)(ch, copy);
                    } catch (py::error_already_set& e) {
                        e.discard_as_unraisable(__func__);
                    }
                });
            }, py::arg("channel"), py::arg("callback"))
        .def("stop_encoded_video_frame", &IMediaBusClient::stopEncodedVideoFrame, py::arg("channel"));
#endif

    /// ───────────────────────────────────────────────────────
    /// LowLevel 枚举
    /// ───────────────────────────────────────────────────────
    py::enum_<IMotionLowLevelClient::LowLevelState>(m, "LowLevelState")
        .value("kDisconnected",   IMotionLowLevelClient::kDisconnected)
        .value("kConnecting",     IMotionLowLevelClient::kConnecting)
        .value("kConnected",      IMotionLowLevelClient::kConnected)
        .value("kPrepared",       IMotionLowLevelClient::kPrepared)
        .value("kConnectionLost", IMotionLowLevelClient::kConnectionLost)
        .export_values();

    py::enum_<IMotionLowLevelClient::LowLevelError>(m, "LowLevelError")
        .value("kNone",                 IMotionLowLevelClient::kNone)
        .value("kRpcConnectFailed",     IMotionLowLevelClient::kRpcConnectFailed)
        .value("kRpcAcquireRejected",   IMotionLowLevelClient::kRpcAcquireRejected)
        .value("kPrepareRejected",      IMotionLowLevelClient::kPrepareRejected)
        .value("kSessionExpired",       IMotionLowLevelClient::kSessionExpired)
        .value("kSessionReleased",      IMotionLowLevelClient::kSessionReleased)
        .value("kServerStop",           IMotionLowLevelClient::kServerStop)
        .value("kRpcCallFailed",        IMotionLowLevelClient::kRpcCallFailed)
        .value("kNotConnected",         IMotionLowLevelClient::kNotConnected)
        .value("kNotPrepared",          IMotionLowLevelClient::kNotPrepared)
        .value("kInvalidArgument",      IMotionLowLevelClient::kInvalidArgument)
        .value("kMasterSwitchFailed",   IMotionLowLevelClient::kMasterSwitchFailed)
        .export_values();

    /// ───────────────────────────────────────────────────────
    /// LowLevelClient（板内单例；实例由 IMotionLowLevelClient::create() 工厂分配）
    /// ───────────────────────────────────────────────────────
    py::class_<IMotionLowLevelClient, std::shared_ptr<IMotionLowLevelClient>>(m, "LowLevelClient")
        .def(py::init([]() { return IMotionLowLevelClient::create(); }))
        .def("connect",      &IMotionLowLevelClient::connect,
             py::arg("observed_hz") = 500, py::arg("lease_ms") = 0,
             py::call_guard<py::gil_scoped_release>())
        .def("disconnect",   &IMotionLowLevelClient::disconnect,
             py::call_guard<py::gil_scoped_release>())
        .def("get_state",    &IMotionLowLevelClient::getState)
        .def("get_last_error", &IMotionLowLevelClient::getLastError)
        .def("emergency_stop", &IMotionLowLevelClient::emergencyStop, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("set_motion_enable", &IMotionLowLevelClient::setMotionEnable, py::arg("enable"))
        .def("send_control", [](IMotionLowLevelClient& self, const MotorCtrlAction& action, const LowLevelMotionCmd* cmd) {
                return self.sendControl(action, cmd);
            }, py::arg("action"), py::arg("cmd") = nullptr,
             py::call_guard<py::gil_scoped_release>())
        .def("send_max_torque", &IMotionLowLevelClient::sendMaxTorque, py::arg("action"),
             py::call_guard<py::gil_scoped_release>())
#if UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
        .def("create_media_bus_client", &IMotionLowLevelClient::createMediaBusClient)
#else
        .def("create_media_bus_client", [](IMotionLowLevelClient&) {
                throw std::runtime_error("MediaBus is not available in this SDK build");
            })
#endif
        .def("get_latest_observation",[](IMotionLowLevelClient& self, uint32_t timeout) -> py::object {
                LowLevelMotionObserved obs = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getLatestObservation(&obs, timeout);
                }
                if (!ok) return py::none();
                return py::cast(obs);
            }, py::arg("timeout_ms") = 5)
        .def("get_sensor_observation",[](IMotionLowLevelClient& self, uint32_t timeout) -> py::object {
                SensorObserved sensor = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getSensorObservation(&sensor, timeout);
                }
                if (!ok) return py::none();
                return py::cast(sensor);
            }, py::arg("timeout_ms") = 5)
        .def("get_motor_layout",[](IMotionLowLevelClient& self, uint32_t timeout) -> py::object {
                MotorLayout layout = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getMotorLayout(layout, timeout);
                }
                if (!ok) return py::none();
                return py::cast(layout);
            }, py::arg("timeout_ms") = 5000)
        .def("set_connect_callback",[](IMotionLowLevelClient& self, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setConnectCallback([callback](IMotionLowLevelClient::LowLevelState state, IMotionLowLevelClient::LowLevelError err) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(state, err); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        .def("restore_motion_control_mode", &IMotionLowLevelClient::restoreMotionControlMode,
             py::arg("timeout_ms") = 5000, py::call_guard<py::gil_scoped_release>())
        ;

    /// ───────────────────────────────────────────────────────
    /// HighLevel 枚举
    /// ───────────────────────────────────────────────────────
    py::enum_<IMotionHighLevelClient::HighLevelState>(m, "HighLevelState")
        .value("kDisconnected", IMotionHighLevelClient::kDisconnected)
        .value("kConnected",    IMotionHighLevelClient::kConnected)
        .value("kControlled",   IMotionHighLevelClient::kControlled)
        .export_values();

    py::enum_<IMotionHighLevelClient::HighLevelError>(m, "HighLevelError")
        .value("kNone",                 IMotionHighLevelClient::kNone)
        .value("kRpcConnectFailed",     IMotionHighLevelClient::kRpcConnectFailed)
        .value("kRpcAcquireRejected",   IMotionHighLevelClient::kRpcAcquireRejected)
        .value("kRpcCallFailed",        IMotionHighLevelClient::kRpcCallFailed)
        .value("kSessionExpired",       IMotionHighLevelClient::kSessionExpired)
        .value("kSessionRevoked",       IMotionHighLevelClient::kSessionRevoked)
        .value("kNotConnected",         IMotionHighLevelClient::kNotConnected)
        .value("kNotControlled",        IMotionHighLevelClient::kNotControlled)
        .value("kActionRejected",       IMotionHighLevelClient::kActionRejected)
        .value("kDataNotUpdate",        IMotionHighLevelClient::kDataNotUpdate)
        .value("kInvalidParam",         IMotionHighLevelClient::kInvalidParam)
        .export_values();

    /// ───────────────────────────────────────────────────────
    /// HighLevelClient（板内单例 create(as_master) / 远端 create(device_id)）
    /// ───────────────────────────────────────────────────────
    py::class_<IMotionHighLevelClient, std::shared_ptr<IMotionHighLevelClient>>(m, "HighLevelClient")
        .def(py::init([](const std::string& deviceId, bool asMaster) {
                return deviceId.empty() ? IMotionHighLevelClient::create(asMaster)
                                        : IMotionHighLevelClient::create(deviceId);
            }), py::arg("device_id") = std::string(), py::arg("as_master") = false)
        .def("connect",         &IMotionHighLevelClient::connect, py::arg("lease_ms") = 0,
             py::call_guard<py::gil_scoped_release>())
        .def("disconnect",      &IMotionHighLevelClient::disconnect,
             py::call_guard<py::gil_scoped_release>())
        .def("get_state",       &IMotionHighLevelClient::getState)
        .def("get_last_error",  &IMotionHighLevelClient::getLastError)
        .def("start_control",   &IMotionHighLevelClient::startControl, py::arg("timeout_ms") = 10000,
             py::call_guard<py::gil_scoped_release>())
        .def("release_control", &IMotionHighLevelClient::releaseControl,
             py::call_guard<py::gil_scoped_release>())
#if UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA
        .def("create_media_bus_client", &IMotionHighLevelClient::createMediaBusClient)
#else
        .def("create_media_bus_client", [](IMotionHighLevelClient&) {
                throw std::runtime_error("MediaBus is not available in this SDK build");
            })
#endif
        /// ── 动作 ──
        .def("emergency_stop",  &IMotionHighLevelClient::emergencyStop, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("recovery_stand",  &IMotionHighLevelClient::recoveryStand, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("stop_action",     &IMotionHighLevelClient::stopAction, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("damp",            &IMotionHighLevelClient::damp, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("stand_up",        &IMotionHighLevelClient::standUp, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("lie_down",        &IMotionHighLevelClient::lieDown, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("move",            &IMotionHighLevelClient::move,
             py::arg("vx"), py::arg("vy"), py::arg("vyaw"), py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("start_action",
            [](IMotionHighLevelClient& self, const std::string& action, py::object params, uint32_t timeout) {
                std::string js = pyToJsonString(params);
                py::gil_scoped_release rel;
                return self.startAction(action, js, timeout);
            },
            py::arg("action"), py::arg("params") = py::none(), py::arg("timeout_ms") = 5000)
        .def("set_action_params",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) {
                std::string js = pyToJsonString(params);
                py::gil_scoped_release rel;
                return self.setActionParams(js, timeout);
            },py::arg("params") = py::none(), py::arg("timeout_ms") = 5000)
        /// ── 查询 ──
        .def("query_motion_state",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.queryMotionState(out, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            },py::arg("timeout_ms") = 5000)
        .def("get_motion_capabilities",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getMotionCapabilities(out, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            },py::arg("timeout_ms") = 5000)
        .def("query_system_status",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.querySystemStatus(out, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            },py::arg("timeout_ms") = 5000)
        .def("get_motor_layout",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                MotorLayout layout = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getMotorLayout(layout, timeout);
                }
                if (!ok) return py::none();
                return py::cast(layout);
            }, py::arg("timeout_ms") = 5000)
        /// ── 观测量数据面 ──
        .def("set_observed_enable",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) -> py::object {
                std::string js = pyToJsonString(params);
                std::string ret;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.setObservedEnable(js, ret, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(ret);
            }, py::arg("params") = py::none(), py::arg("timeout_ms") = 5000)
        .def("get_power_info",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                PowerObserved power = {};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getPowerInfo(&power, timeout);
                }
                if (!ok) return py::none();
                return py::cast(power);
            }, py::arg("timeout_ms") = 5)
        .def("get_sensor_observation",[](IMotionHighLevelClient& self,uint32_t timeout) -> py::object {
                SensorObserved sensor{};
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getSensorObservation(&sensor,timeout);
                }
                if (!ok) return py::none();
                return py::cast(sensor);
            },py::arg("timeout_ms") = 5000)
        .def("set_motion_observed_callback",[](IMotionHighLevelClient& self, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setMotionObservedCallback([callback](const LowLevelMotionObserved& obs) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(obs); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        .def("set_sensor_observed_callback",[](IMotionHighLevelClient& self,py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setSensorObservedCallback([callback](const SensorObserved& sensor) {
                    py::gil_scoped_acquire g;
                    try {(*callback)(sensor);} catch (py::error_already_set& e) {e.discard_as_unraisable(__func__);}
                });
            })
        /// ── 音频播放 / 灯光 ──
        .def("start_audio_play",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) {
                std::string js = pyToJsonString(params);
                py::gil_scoped_release rel;
                return self.startAudioPlay(js, timeout);
            }, py::arg("params"), py::arg("timeout_ms") = 5000)
        .def("stop_audio_play",  &IMotionHighLevelClient::stopAudioPlay, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("pause_audio_play", &IMotionHighLevelClient::pauseAudioPlay, py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        .def("add_audio_file",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) {
                std::string js = pyToJsonString(params);
                py::gil_scoped_release rel;
                return self.addAudioFile(js, timeout);
            }, py::arg("params"), py::arg("timeout_ms") = 30000)
        .def("delete_audio_file",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) {
                std::string js = pyToJsonString(params);
                py::gil_scoped_release rel;
                return self.deleteAudioFile(js, timeout);
            }, py::arg("params"), py::arg("timeout_ms") = 5000)
        .def("query_audio_play_detail",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.queryAudioPlayDetail(out, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            }, py::arg("timeout_ms") = 5000)
        .def("query_audio_play_list",[](IMotionHighLevelClient& self, py::object params, uint32_t timeout) -> py::object {
                std::string js = pyToJsonString(params);
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.queryAudioPlayList(out, js, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            }, py::arg("params") = py::none(), py::arg("timeout_ms") = 5000)
        .def("get_camera_light_brightness",[](IMotionHighLevelClient& self, uint32_t timeout) -> py::object {
                std::string out;
                bool ok;
                {
                    py::gil_scoped_release rel;
                    ok = self.getCameraLightBrightness(out, timeout);
                }
                if (!ok) return py::none();
                return jsonStringToPy(out);
            }, py::arg("timeout_ms") = 5000)
        .def("set_camera_light_brightness", &IMotionHighLevelClient::setCameraLightBrightness,
             py::arg("brightness"), py::arg("timeout_ms") = 5000,
             py::call_guard<py::gil_scoped_release>())
        /// ── 回调 ──
        .def("set_connect_callback",[](IMotionHighLevelClient& self, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setConnectCallback([callback](IMotionHighLevelClient::HighLevelState state,
                                             IMotionHighLevelClient::HighLevelError err) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(state, err); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        .def("set_event_callback",[](IMotionHighLevelClient& self, py::function cb) {
                PyCallback callback = makePyCallback(std::move(cb));
                self.setEventCallback([callback](const std::string& topic, const std::string& payload) {
                    py::gil_scoped_acquire g;
                    try { (*callback)(topic, payload); } catch (py::error_already_set& e) { e.discard_as_unraisable(__func__); }
                });
            })
        ;
}
