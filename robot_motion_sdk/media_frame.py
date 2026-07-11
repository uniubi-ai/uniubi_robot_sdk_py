"""
MediaBus frame-format wrappers exported by Motion SDK.

This module wraps the private pybind11 native module and keeps the public
Python API independent from the internal uniubi_mediabus Python package.
"""

from __future__ import annotations

from typing import Any, Optional

from . import _uniubi_robot_motion_py_native as _native

if not bool(getattr(_native, "MEDIA_ENABLED", False)):
    raise ImportError("MediaBus is not available in this SDK build")


MediaPixelFormat = _native.MediaPixelFormat
VideoStreamType = _native.VideoStreamType
VideoEncode = _native.VideoEncode
AudioEncode = _native.AudioEncode
MediaBufferMetaType = _native.MediaBufferMetaType
ImuCoordFrame = _native.ImuCoordFrame
ImuFrameStatus = _native.ImuFrameStatus
StreamType = _native.StreamType
StreamTrack = _native.StreamTrack
FrameType = _native.FrameType
StreamChange = _native.StreamChange

FIRST_PKT = _native.FIRST_PKT
LAST_PKT = _native.LAST_PKT
IMU_FRAME_META_HEADER_SIZE = _native.IMU_FRAME_META_HEADER_SIZE
IMU_SAMPLE_SIZE = _native.IMU_SAMPLE_SIZE

MediaBufferView = _native.MediaBufferView
CMediaFrameView = _native.CMediaFrameView
VideoFramePlaneView = _native.VideoFramePlaneView
VideoFrameRowView = _native.VideoFrameRowView

_MISSING = object()


def _unwrap_native(value: Any) -> Any:
    return value._impl if isinstance(value, _NativeWrapper) else value


class _NativeWrapper:
    """Small Python-side public wrapper around a private native object."""

    __slots__ = ("_impl",)
    _native_type = None

    def __init__(self, *, _impl: Any = None) -> None:
        if _impl is None:
            if self._native_type is None:
                raise TypeError("native type is not configured")
            _impl = self._native_type()
        object.__setattr__(self, "_impl", _impl)

    @classmethod
    def _from_native(cls, impl: Any):
        if isinstance(impl, cls):
            return impl
        obj = cls.__new__(cls)
        object.__setattr__(obj, "_impl", impl)
        return obj

    @property
    def native(self) -> Any:
        """Return the private pybind11 object for SDK internals."""
        return self._impl

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_impl":
            object.__setattr__(self, name, value)
            return
        setattr(self._impl, name, _unwrap_native(value))

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._impl!r})"


class VideoFrameInfo(_NativeWrapper):
    _native_type = _native.VideoFrameInfo


class AudioFrameInfo(_NativeWrapper):
    _native_type = _native.AudioFrameInfo


class EncodedVideoFrameInfo(_NativeWrapper):
    _native_type = _native.EncodedVideoFrameInfo


class EncodedAudioFrameInfo(_NativeWrapper):
    _native_type = _native.EncodedAudioFrameInfo


class EncodedFrameInfo(_NativeWrapper):
    _native_type = _native.EncodedFrameInfo

    @property
    def video_info(self) -> EncodedVideoFrameInfo:
        return EncodedVideoFrameInfo._from_native(self._impl.video_info)

    @video_info.setter
    def video_info(self, info: EncodedVideoFrameInfo) -> None:
        self._impl.video_info = _unwrap_native(info)

    @property
    def audio_info(self) -> EncodedAudioFrameInfo:
        return EncodedAudioFrameInfo._from_native(self._impl.audio_info)

    @audio_info.setter
    def audio_info(self, info: EncodedAudioFrameInfo) -> None:
        self._impl.audio_info = _unwrap_native(info)


class MediaBuffer(_NativeWrapper):
    _native_type = _native.MediaBuffer

    def __init__(self, data: Any = _MISSING, extra_size: int = 0, *, _impl: Any = None) -> None:
        if _impl is not None:
            super().__init__(_impl=_impl)
        elif data is _MISSING:
            super().__init__()
        else:
            super().__init__(_impl=_native.MediaBuffer(bytes(data), extra_size))

    def valid(self) -> bool:
        return self._impl.valid()

    def reset(self) -> None:
        self._impl.reset()

    def size(self) -> int:
        return self._impl.size()

    def extra_size(self) -> int:
        return self._impl.extra_size()

    def data(self) -> bytes:
        return self._impl.data()

    def extra_data(self) -> bytes:
        return self._impl.extra_data()

    def view(self) -> MediaBufferView:
        return self._impl.view()

    def set_size(self, size: int) -> bool:
        return self._impl.set_size(size)

    def get_fd(self) -> int:
        return self._impl.get_fd()

    def set_fd(self, fd: int) -> None:
        self._impl.set_fd(fd)

    def metadata(self) -> bytes:
        return self._impl.metadata()

    def get_metadata(self, type: int) -> Optional[bytes]:
        return self._impl.get_metadata(type)

    def has_metadata(self, type: int) -> bool:
        return self._impl.has_metadata(type)

    def metadata_items(self) -> list:
        return self._impl.metadata_items()

    def metadata_dict(self) -> dict:
        return self._impl.metadata_dict()

    def get_imu_metadata(self) -> Optional[dict]:
        return self._impl.get_imu_metadata()

    def set_metadata(self, type: int, data: bytes) -> bool:
        return self._impl.set_metadata(type, bytes(data))

    def remove_metadata(self, type: int) -> bool:
        return self._impl.remove_metadata(type)

    def clear_metadata(self) -> None:
        self._impl.clear_metadata()

    def copy_metadata(self, other: "MediaBuffer") -> bool:
        return self._impl.copy_metadata(_unwrap_native(other))


class VideoFrame(MediaBuffer):
    _native_type = _native.VideoFrame

    def __init__(
        self,
        data: Any = _MISSING,
        info: Optional[VideoFrameInfo] = None,
        extra_size: int = 0,
        *,
        _impl: Any = None,
    ) -> None:
        if _impl is not None:
            _NativeWrapper.__init__(self, _impl=_impl)
        elif data is _MISSING:
            _NativeWrapper.__init__(self, _impl=_native.VideoFrame())
        else:
            native_info = _unwrap_native(info) if info is not None else _native.VideoFrameInfo()
            _NativeWrapper.__init__(self, _impl=_native.VideoFrame(bytes(data), native_info, extra_size))

    @property
    def frame_info(self) -> VideoFrameInfo:
        return VideoFrameInfo._from_native(self._impl.frame_info)

    @frame_info.setter
    def frame_info(self, info: VideoFrameInfo) -> None:
        self._impl.frame_info = _unwrap_native(info)

    def plane_view(self, plane: int = 0) -> VideoFramePlaneView:
        return self._impl.plane_view(plane)


class CMediaFrame(_NativeWrapper):
    _native_type = _native.CMediaFrame

    def __init__(
        self,
        data: Any = _MISSING,
        *,
        capacity: Optional[int] = None,
        _impl: Any = None,
    ) -> None:
        if _impl is not None:
            _NativeWrapper.__init__(self, _impl=_impl)
        elif data is _MISSING:
            if capacity is None:
                _NativeWrapper.__init__(self, _impl=_native.CMediaFrame())
            else:
                _NativeWrapper.__init__(self, _impl=_native.CMediaFrame(capacity))
        else:
            _NativeWrapper.__init__(self, _impl=_native.CMediaFrame(bytes(data)))

    @property
    def frame_info(self) -> Optional[EncodedFrameInfo]:
        info = self._impl.frame_info
        return None if info is None else EncodedFrameInfo._from_native(info)

    @frame_info.setter
    def frame_info(self, info: EncodedFrameInfo) -> None:
        self._impl.frame_info = _unwrap_native(info)

    @property
    def video_info(self) -> Optional[EncodedVideoFrameInfo]:
        info = self._impl.video_info
        return None if info is None else EncodedVideoFrameInfo._from_native(info)

    @video_info.setter
    def video_info(self, info: EncodedVideoFrameInfo) -> None:
        self._impl.video_info = _unwrap_native(info)

    @property
    def audio_info(self) -> Optional[EncodedAudioFrameInfo]:
        info = self._impl.audio_info
        return None if info is None else EncodedAudioFrameInfo._from_native(info)

    @audio_info.setter
    def audio_info(self, info: EncodedAudioFrameInfo) -> None:
        self._impl.audio_info = _unwrap_native(info)

    def valid(self) -> bool:
        return self._impl.valid()

    def reset(self) -> None:
        self._impl.reset()

    def size(self) -> int:
        return self._impl.size()

    def capacity(self) -> int:
        return self._impl.capacity()

    def data(self) -> bytes:
        return self._impl.data()

    def view(self) -> CMediaFrameView:
        return self._impl.view()

    def resize(self, size: int) -> bool:
        return self._impl.resize(size)


EncodedVideoFrame = CMediaFrame
EncodedVideoFrameView = CMediaFrameView


class AudioFrame(MediaBuffer):
    _native_type = _native.AudioFrame

    def __init__(
        self,
        data: Any = _MISSING,
        info: Optional[AudioFrameInfo] = None,
        extra_size: int = 0,
        *,
        _impl: Any = None,
    ) -> None:
        if _impl is not None:
            _NativeWrapper.__init__(self, _impl=_impl)
        elif data is _MISSING:
            _NativeWrapper.__init__(self, _impl=_native.AudioFrame())
        else:
            native_info = _unwrap_native(info) if info is not None else _native.AudioFrameInfo()
            _NativeWrapper.__init__(self, _impl=_native.AudioFrame(bytes(data), native_info, extra_size))

    @property
    def frame_info(self) -> AudioFrameInfo:
        return AudioFrameInfo._from_native(self._impl.frame_info)

    @frame_info.setter
    def frame_info(self, info: AudioFrameInfo) -> None:
        self._impl.frame_info = _unwrap_native(info)


def frame_bytes(frame: Any) -> bytes:
    """返回 MediaBuffer/Frame/EncodedVideoFrame 的数据拷贝。"""
    return frame.data()


def frame_extra_bytes(frame: MediaBuffer) -> bytes:
    """返回 MediaBuffer extra data 的数据拷贝。"""
    return frame.extra_data()


def frame_view(frame: Any) -> Any:
    """返回 MediaBuffer/EncodedVideoFrame 的只读 buffer view，可用于 memoryview(frame_view(frame))。"""
    return frame.view()


def video_plane_view(frame: VideoFrame, plane: int = 0) -> VideoFramePlaneView:
    """返回 VideoFrame 指定平面的只读 buffer view。"""
    return frame.plane_view(plane)


__all__ = [
    "MediaPixelFormat",
    "VideoStreamType",
    "VideoEncode",
    "AudioEncode",
    "MediaBufferMetaType",
    "ImuCoordFrame",
    "ImuFrameStatus",
    "StreamType",
    "StreamTrack",
    "FrameType",
    "StreamChange",
    "FIRST_PKT",
    "LAST_PKT",
    "IMU_FRAME_META_HEADER_SIZE",
    "IMU_SAMPLE_SIZE",
    "MediaBuffer",
    "MediaBufferView",
    "CMediaFrameView",
    "EncodedVideoFrameView",
    "VideoFrameInfo",
    "AudioFrameInfo",
    "EncodedVideoFrameInfo",
    "EncodedAudioFrameInfo",
    "EncodedFrameInfo",
    "VideoFrame",
    "CMediaFrame",
    "EncodedVideoFrame",
    "AudioFrame",
    "VideoFramePlaneView",
    "VideoFrameRowView",
    "frame_bytes",
    "frame_extra_bytes",
    "frame_view",
    "video_plane_view",
]
