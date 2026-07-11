"""Media frame subscription example for Motion SDK.

Usage:
  python3 example_media_frames.py [config|-] [client_id] [device_id|-] \
      [video_channel] [audio_channel] [seconds] [network_iface|-]

Examples:
  python3 example_media_frames.py
  python3 example_media_frames.py - mediaFramePythonExample - 0 0 10 eth0

Media frame subscription is supported only on aarch64 local board deployment.
The config argument may be omitted or set to "-" to use the SDK built-in
mediaBusDemo streamDefine. The first 10 frames of each type are saved under
/tmp/media_frame_dump.

帧订阅统一走 MediaBusClient：先 connect() 一个 LowLevel/High 客户端，
再 client.create_media_bus_client() 拿到 MediaBusClient，setup() 后即可
start_raw_video_frame / start_raw_audio_frame / start_encoded_video_frame。
回调签名分别为 (channel, VideoFrame) / (channel, AudioFrame) /
(channel, EncodedVideoFrame)。

Raw video frames must be accessed by plane and stride. On NVIDIA platforms
the image planes may be non-contiguous, so do not treat frame.data() as a
complete packed image. This example saves raw video with plane_view().row_view()
and writes only the valid bytes of each row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import platform
import signal
import sys
import threading
import time
from typing import List, Optional, Tuple

try:
    import robot_motion_sdk as sdk
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import robot_motion_sdk as sdk


DUMP_LIMIT = 10
DUMP_DIR = Path("/tmp/media_frame_dump")

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


@dataclass
class Options:
    config_file: Optional[str] = None
    client_id: str = "mediaFramePythonExample"
    device_id: str = ""
    video_channel: int = 0
    audio_channel: int = 0
    seconds: int = 10
    network_interface: str = ""


@dataclass
class Counter:
    frames: int = 0
    bytes: int = 0
    dumped: int = 0


@dataclass
class Stats:
    video_raw: Counter = field(default_factory=Counter)
    video_encoded: Counter = field(default_factory=Counter)
    audio_raw: Counter = field(default_factory=Counter)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, counter: Counter, size: int) -> Tuple[int, Optional[int]]:
        with self.lock:
            counter.frames += 1
            counter.bytes += size
            count = counter.frames
            dump_index = None
            if counter.dumped < DUMP_LIMIT:
                dump_index = counter.dumped
                counter.dumped += 1
        return count, dump_index


def _parse_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _parse_args(argv: List[str]) -> Options:
    options = Options()
    if len(argv) > 1 and argv[1] != "-":
        options.config_file = argv[1]
    if len(argv) > 2:
        options.client_id = argv[2]
    if len(argv) > 3 and argv[3] != "-":
        options.device_id = argv[3]
    if len(argv) > 4:
        options.video_channel = _parse_int(argv[4], options.video_channel)
    if len(argv) > 5:
        options.audio_channel = _parse_int(argv[5], options.audio_channel)
    if len(argv) > 6:
        options.seconds = max(0, _parse_int(argv[6], options.seconds))
    if len(argv) > 7 and argv[7] != "-":
        options.network_interface = argv[7]
    return options


def _print_usage(program: str) -> None:
    print(
        "usage: "
        f"{program} [config|-] [client_id] [device_id|-] "
        "[video_channel] [audio_channel] [seconds] [network_iface|-]"
    )
    print("       config omitted or '-' uses the SDK built-in mediaBusDemo streamDefine.")
    print(f"example: {program} - mediaFramePythonExample - 0 0 10 eth0")


def _is_aarch64_local_media_target() -> bool:
    return platform.machine().lower() in {"aarch64", "arm64"}


def _enum_int(enum_cls, name: str) -> Optional[int]:
    value = getattr(enum_cls, name, None)
    return None if value is None else int(value)


def _enum_int_set(enum_cls, names: List[str]) -> set:
    return {value for value in (_enum_int(enum_cls, name) for name in names) if value is not None}


PF = sdk.MediaPixelFormat
VIDEO_ENCODE = sdk.VideoEncode
FRAME_TYPE = sdk.FrameType

PIXEL_FORMAT_NAMES = {
    _enum_int(PF, "mediaPixelFormatNV12"): "NV12",
    _enum_int(PF, "mediaPixelFormatNV21"): "NV21",
    _enum_int(PF, "mediaPixelFormatNV16"): "NV16",
    _enum_int(PF, "mediaPixelFormatNV61"): "NV61",
    _enum_int(PF, "mediaPixelFormatRGB888"): "RGB888",
    _enum_int(PF, "mediaPixelFormatBGR888"): "BGR888",
    _enum_int(PF, "mediaPixelFormatARGB8888"): "ARGB8888",
    _enum_int(PF, "mediaPixelFormatABGR8888"): "ABGR8888",
    _enum_int(PF, "mediaPixelFormatYUYV422"): "YUYV422",
    _enum_int(PF, "mediaPixelFormatUYVY422"): "UYVY422",
    _enum_int(PF, "mediaPixelFormatYUV420P"): "YUV420P",
    _enum_int(PF, "mediaPixelFormatYUV422P"): "YUV422P",
    _enum_int(PF, "mediaPixelFormatYUV444P"): "YUV444P",
    _enum_int(PF, "mediaPixelFormatYUV400"): "YUV400",
    _enum_int(PF, "mediaPixelFormatYUV420M"): "YUV420M",
    _enum_int(PF, "mediaPixelFormatYUV422RM"): "YUV422RM",
    _enum_int(PF, "mediaPixelFormatYUV422M"): "YUV422M",
    _enum_int(PF, "mediaPixelFormatYUV444M"): "YUV444M",
    _enum_int(PF, "mediaPixelFormatRGBA8888"): "RGBA8888",
    _enum_int(PF, "mediaPixelFormatBGRA8888"): "BGRA8888",
    _enum_int(PF, "mediaPixelFormatRGB565"): "RGB565",
    _enum_int(PF, "mediaPixelFormatRGB888Planar"): "RGB888P",
    _enum_int(PF, "mediaPixelFormatBGR888Planar"): "BGR888P",
    _enum_int(PF, "mediaPixelFormatS16C1"): "S16C1",
    _enum_int(PF, "mediaPixelFormatU16C1"): "U16C1",
}
PIXEL_FORMAT_NAMES = {key: value for key, value in PIXEL_FORMAT_NAMES.items() if key is not None}

VIDEO_CODEC_NAMES = {
    _enum_int(VIDEO_ENCODE, "videoH264"): "H264",
    _enum_int(VIDEO_ENCODE, "videoH265"): "H265",
    _enum_int(VIDEO_ENCODE, "videoMpeg4"): "MPEG4",
    _enum_int(VIDEO_ENCODE, "videoMJpeg"): "MJPEG",
    _enum_int(VIDEO_ENCODE, "videoJpeg"): "JPEG",
}
VIDEO_CODEC_NAMES = {key: value for key, value in VIDEO_CODEC_NAMES.items() if key is not None}

FRAME_TYPE_NAMES = {
    _enum_int(FRAME_TYPE, "audioFrame"): "audio",
    _enum_int(FRAME_TYPE, "videoFrame"): "video",
    _enum_int(FRAME_TYPE, "auxFrame"): "aux",
    _enum_int(FRAME_TYPE, "imageFrame"): "image",
    _enum_int(FRAME_TYPE, "videoBFrame"): "B",
    _enum_int(FRAME_TYPE, "videoIFrame"): "I",
    _enum_int(FRAME_TYPE, "videoPFrame"): "P",
    _enum_int(FRAME_TYPE, "waterFrame"): "water",
    _enum_int(FRAME_TYPE, "auxMetaFrame"): "meta",
}
FRAME_TYPE_NAMES = {key: value for key, value in FRAME_TYPE_NAMES.items() if key is not None}

PF_NV12 = _enum_int(PF, "mediaPixelFormatNV12")
PF_NV21 = _enum_int(PF, "mediaPixelFormatNV21")
PF_NV16 = _enum_int(PF, "mediaPixelFormatNV16")
PF_NV61 = _enum_int(PF, "mediaPixelFormatNV61")
PF_YUV400 = _enum_int(PF, "mediaPixelFormatYUV400")

PF_YUV420_PLANAR = _enum_int_set(PF, ["mediaPixelFormatYUV420P", "mediaPixelFormatYUV420M"])
PF_YUV422_PLANAR = _enum_int_set(PF, ["mediaPixelFormatYUV422P", "mediaPixelFormatYUV422M", "mediaPixelFormatYUV422RM"])
PF_3_PLANE_FULL = _enum_int_set(
    PF,
    [
        "mediaPixelFormatYUV444P",
        "mediaPixelFormatYUV444M",
        "mediaPixelFormatRGB888Planar",
        "mediaPixelFormatBGR888Planar",
    ],
)
PF_PACKED_3 = _enum_int_set(PF, ["mediaPixelFormatRGB888", "mediaPixelFormatBGR888"])
PF_PACKED_4 = _enum_int_set(
    PF,
    [
        "mediaPixelFormatRGBA8888",
        "mediaPixelFormatBGRA8888",
        "mediaPixelFormatARGB8888",
        "mediaPixelFormatABGR8888",
    ],
)
PF_PACKED_2 = _enum_int_set(
    PF,
    [
        "mediaPixelFormatRGB565",
        "mediaPixelFormatARGB1555",
        "mediaPixelFormatABGR1555",
        "mediaPixelFormatYUYV422",
        "mediaPixelFormatUYVY422",
        "mediaPixelFormatS16C1",
        "mediaPixelFormatU16C1",
    ],
)


def _pixel_format_name(fmt) -> str:
    return PIXEL_FORMAT_NAMES.get(int(fmt), f"UNKNOWN_{int(fmt)}")


def _video_codec_name(codec: int) -> str:
    return VIDEO_CODEC_NAMES.get(int(codec), "unknown")


def _frame_type_name(frame_type: int) -> str:
    return FRAME_TYPE_NAMES.get(int(frame_type), "unknown")


def _encoded_video_ext(codec: int) -> str:
    if codec == _enum_int(VIDEO_ENCODE, "videoH264"):
        return "h264"
    if codec == _enum_int(VIDEO_ENCODE, "videoH265"):
        return "h265"
    if codec in {
        _enum_int(VIDEO_ENCODE, "videoMJpeg"),
        _enum_int(VIDEO_ENCODE, "videoJpeg"),
    }:
        return "jpg"
    return "bin"


def _write_bytes(path: Path, data: bytes) -> bool:
    if not data:
        return False
    path.write_bytes(data)
    return True


def _write_plane_rows(fp, frame: sdk.VideoFrame, plane: int, row_bytes: int, rows: int) -> bool:
    """Write one video plane row by row, honoring the plane stride."""
    if rows <= 0:
        return True
    if row_bytes <= 0:
        return False

    view = frame.plane_view(plane)
    for row in range(rows):
        row_view = memoryview(view.row_view(row))
        if len(row_view) < row_bytes:
            print(
                f"skip video raw dump row: plane={plane} row={row} "
                f"need={row_bytes} got={len(row_view)}"
            )
            return False
        fp.write(row_view[:row_bytes])
    return True


def _dump_video_frame_payload(path: Path, frame: sdk.VideoFrame) -> bool:
    info = frame.frame_info
    width = int(info.width)
    height = int(info.height)
    fmt = int(info.pixel_format)

    known_format = (
        fmt in {PF_NV12, PF_NV21, PF_NV16, PF_NV61, PF_YUV400}
        or fmt in PF_YUV420_PLANAR
        or fmt in PF_YUV422_PLANAR
        or fmt in PF_3_PLANE_FULL
        or fmt in PF_PACKED_3
        or fmt in PF_PACKED_4
        or fmt in PF_PACKED_2
    )
    if not known_format:
        return _write_bytes(path, frame.data())

    ok = False
    try:
        with path.open("wb") as fp:
            if fmt in {PF_NV12, PF_NV21}:
                ok = (
                    _write_plane_rows(fp, frame, 0, width, height)
                    and _write_plane_rows(fp, frame, 1, width, (height + 1) // 2)
                )
            elif fmt in {PF_NV16, PF_NV61}:
                ok = (
                    _write_plane_rows(fp, frame, 0, width, height)
                    and _write_plane_rows(fp, frame, 1, width, height)
                )
            elif fmt == PF_YUV400:
                ok = _write_plane_rows(fp, frame, 0, width, height)
            elif fmt in PF_YUV420_PLANAR:
                chroma_width = (width + 1) // 2
                chroma_height = (height + 1) // 2
                ok = (
                    _write_plane_rows(fp, frame, 0, width, height)
                    and _write_plane_rows(fp, frame, 1, chroma_width, chroma_height)
                    and _write_plane_rows(fp, frame, 2, chroma_width, chroma_height)
                )
            elif fmt in PF_YUV422_PLANAR:
                chroma_width = (width + 1) // 2
                ok = (
                    _write_plane_rows(fp, frame, 0, width, height)
                    and _write_plane_rows(fp, frame, 1, chroma_width, height)
                    and _write_plane_rows(fp, frame, 2, chroma_width, height)
                )
            elif fmt in PF_3_PLANE_FULL:
                ok = (
                    _write_plane_rows(fp, frame, 0, width, height)
                    and _write_plane_rows(fp, frame, 1, width, height)
                    and _write_plane_rows(fp, frame, 2, width, height)
                )
            elif fmt in PF_PACKED_3:
                ok = _write_plane_rows(fp, frame, 0, width * 3, height)
            elif fmt in PF_PACKED_4:
                ok = _write_plane_rows(fp, frame, 0, width * 4, height)
            elif fmt in PF_PACKED_2:
                ok = _write_plane_rows(fp, frame, 0, width * 2, height)
    except Exception as exc:  # noqa: BLE001
        print(f"dump video raw failed: {path}: {exc}")
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return False

    if not ok:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return ok


def _dump_video_frame(dump_index: int, channel: int, frame: sdk.VideoFrame) -> None:
    info = frame.frame_info
    path = DUMP_DIR / (
        f"video_raw_ch{channel}_{dump_index:02d}_"
        f"{int(info.width)}x{int(info.height)}_"
        f"{_pixel_format_name(info.pixel_format)}_seq{int(info.sequence)}.yuv"
    )
    if _dump_video_frame_payload(path, frame):
        stride = list(info.stride)
        print(f"[dump] {path} raw_size={frame.size()} stride={stride[0]}/{stride[1]}/{stride[2]}")


def _dump_audio_frame(dump_index: int, channel: int, frame: sdk.AudioFrame) -> None:
    info = frame.frame_info
    path = DUMP_DIR / (
        f"audio_raw_ch{channel}_{dump_index:02d}_"
        f"rate{int(info.sample_rate)}_bit{int(info.sample_format)}_"
        f"ch{int(info.channel_count)}_seq{int(info.sequence)}.pcm"
    )
    if _write_bytes(path, frame.data()):
        print(f"[dump] {path} size={frame.size()}")


def _dump_encoded_frame(dump_index: int, channel: int, frame: sdk.EncodedVideoFrame) -> None:
    video = frame.video_info
    codec = int(video.encode) if video is not None else 0
    width = int(video.width) if video is not None else 0
    height = int(video.height) if video is not None else 0
    path = DUMP_DIR / (
        f"video_encoded_ch{channel}_{dump_index:02d}_"
        f"{width}x{height}_type0x{int(frame.frame_type):02x}_"
        f"seq{int(frame.sequence)}.{_encoded_video_ext(codec)}"
    )
    if _write_bytes(path, frame.data()):
        print(f"[dump] {path} size={frame.size()}")


def _on_video_frame(stats: Stats, channel: int, frame: sdk.VideoFrame) -> None:
    try:
        count, dump_index = stats.update(stats.video_raw, int(frame.size()))
        if dump_index is not None:
            _dump_video_frame(dump_index, channel, frame)

        if count != 1 and count % 30 != 0:
            return
        info = frame.frame_info
        print(
            f"[video-raw] ch={channel} count={count} size={frame.size()} fd={frame.get_fd()} "
            f"{int(info.width)}x{int(info.height)} fmt={int(info.pixel_format)} "
            f"ts={int(info.timestamp)} seq={int(info.sequence)}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[video-raw] callback failed: {exc}")


def _on_audio_frame(stats: Stats, channel: int, frame: sdk.AudioFrame) -> None:
    try:
        count, dump_index = stats.update(stats.audio_raw, int(frame.size()))
        if dump_index is not None:
            _dump_audio_frame(dump_index, channel, frame)

        if count != 1 and count % 30 != 0:
            return
        info = frame.frame_info
        print(
            f"[audio-raw] ch={channel} count={count} size={frame.size()} fd={frame.get_fd()} "
            f"rate={int(info.sample_rate)} bit={int(info.sample_format)} "
            f"channels={int(info.channel_count)} type={int(info.data_type)} "
            f"ts={int(info.timestamp)} seq={int(info.sequence)}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[audio-raw] callback failed: {exc}")


def _on_encoded_frame(stats: Stats, channel: int, frame: sdk.EncodedVideoFrame) -> None:
    try:
        count, dump_index = stats.update(stats.video_encoded, int(frame.size()))
        if dump_index is not None:
            _dump_encoded_frame(dump_index, channel, frame)

        if count != 1 and count % 30 != 0:
            return
        info = frame.frame_info
        video = frame.video_info
        if info is None or video is None:
            print(
                f"[video-encoded] ch={channel} "
                f"count={count} size={frame.size()} no frame info"
            )
            return
        print(
            f"[video-encoded] ch={channel} count={count} size={frame.size()} "
            f"codec={_video_codec_name(int(video.encode))}({int(video.encode)}) "
            f"type={_frame_type_name(int(frame.frame_type))}(0x{int(frame.frame_type):02x}) "
            f"{int(video.width)}x{int(video.height)} fps={int(video.fps_num)}/{int(video.fps_den)} "
            f"pts={int(frame.pts)} seq={int(frame.sequence)} utc={int(frame.utc)} "
            f"change={int(info.change)}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[video-encoded] callback failed: {exc}")


def _print_summary(stats: Stats) -> None:
    print(f"[summary] video_raw frames={stats.video_raw.frames} bytes={stats.video_raw.bytes}")
    print(f"[summary] video_encoded frames={stats.video_encoded.frames} bytes={stats.video_encoded.bytes}")
    print(f"[summary] audio_raw frames={stats.audio_raw.frames} bytes={stats.audio_raw.bytes}")
    print(
        "[summary] dumped files: "
        f"video_raw={stats.video_raw.dumped} "
        f"video_encoded={stats.video_encoded.dumped} "
        f"audio_raw={stats.audio_raw.dumped} dir={DUMP_DIR}"
    )


def main() -> int:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help"}:
        _print_usage(sys.argv[0])
        return 0

    options = _parse_args(sys.argv)
    _print_usage(sys.argv[0])
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"dump dir: {DUMP_DIR}")

    if options.network_interface:
        sdk.service.set_network_interface(options.network_interface)

    def _on_log(level: sdk.LogLevel, msg: str) -> None:
        print(f"[sdk-log][{int(level)}] {msg}", end="" if msg.endswith("\n") else "\n")

    sdk.service.set_log_callback(_on_log)

    client: Optional[sdk.MotionLowLevelClient] = None
    media = None
    subscribed_video_raw = False
    subscribed_video_encoded = False
    subscribed_audio_raw = False
    stats = Stats()

    try:
        if not _is_aarch64_local_media_target():
            print("media frame subscription is only supported on aarch64 local board deployment")
            return 1

        if not sdk.service.initial(options.config_file, options.client_id):
            print("SDK initial failed")
            return 1

        # MediaBus 仅支持 aarch64 板内本地部署；多设备/远端模式不提供帧订阅。
        if sdk.service.is_multi_device():
            print("media bus frame subscription is only supported on local board deployment")
            return 1

        # MediaBusClient 由已 connect 的客户端工厂分配；这里只取音视频帧，
        # 用板内 LowLevel 客户端 connect 即可，无需 set_motion_enable。
        client = sdk.MotionLowLevelClient()
        if not client.connect():
            print(f"connect failed: {client.get_last_error()}")
            return 1

        deadline = time.monotonic() + 5.0
        while client.get_state() != sdk.LowLevelState.kConnected:
            if _stop or time.monotonic() > deadline:
                print("wait connected timeout")
                return 1
            time.sleep(0.05)

        media = client.create_media_bus_client()
        if media is None or not media.setup():
            print("create/setup media bus client failed")
            return 1

        layout = media.get_media_layout()
        if layout is not None:
            print(
                f"media layout: mic={layout.mic_num} "
                f"camera={layout.camera_num} encoder={layout.video_encoder_num}"
            )

        subscribed_video_raw = media.start_raw_video_frame(
            options.video_channel,
            lambda ch, frame: _on_video_frame(stats, ch, frame),
        )
        subscribed_video_encoded = media.start_encoded_video_frame(
            options.video_channel,
            lambda ch, frame: _on_encoded_frame(stats, ch, frame),
        )
        subscribed_audio_raw = media.start_raw_audio_frame(
            options.audio_channel,
            lambda ch, frame: _on_audio_frame(stats, ch, frame),
        )

        print(
            "subscribe result: "
            f"video_raw={int(subscribed_video_raw)} "
            f"video_encoded={int(subscribed_video_encoded)} "
            f"audio_raw={int(subscribed_audio_raw)}"
        )

        for i in range(options.seconds):
            if _stop:
                break
            time.sleep(1)
            print(f"[tick] {i + 1}/{options.seconds}")

        return 0

    finally:
        if media is not None:
            try:
                if subscribed_video_encoded:
                    media.stop_encoded_video_frame(options.video_channel)
                if subscribed_video_raw:
                    media.stop_raw_video_frame(options.video_channel)
                if subscribed_audio_raw:
                    media.stop_raw_audio_frame(options.audio_channel)
            except Exception as exc:  # noqa: BLE001
                print(f"stop media subscription raised: {exc}")

            try:
                media.shutdown()
            except Exception as exc:  # noqa: BLE001
                print(f"media shutdown raised: {exc}")

        _print_summary(stats)

        if client is not None:
            try:
                client.disconnect()
            except Exception as exc:  # noqa: BLE001
                print(f"disconnect raised: {exc}")

        try:
            sdk.service.shutdown()
        except Exception as exc:  # noqa: BLE001
            print(f"shutdown raised: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
