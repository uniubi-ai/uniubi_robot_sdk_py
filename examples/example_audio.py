"""Onboard brain: subscribe to PCM through local MediaBus shared memory."""
import argparse
import queue
import threading
import time

import robot_motion_sdk as sdk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, default=0, help="streamDefine.aiStream array index")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--output", help="Optional PCM output file (overwritten)")
    args = parser.parse_args()
    if args.channel < 0 or args.seconds <= 0:
        parser.error("channel must be non-negative and seconds must be positive")
    if not sdk.MEDIA_ENABLED:
        print("This SDK build has no MediaBus support; run on the onboard brain.")
        return 1

    client = media = output = None
    subscribed = False
    lock = threading.Lock()
    pending = queue.Queue(maxsize=64)
    stats = {"frames": 0, "bytes": 0, "dropped": 0, "rate": 0, "bits": 0, "channels": 0, "timestamp": 0}

    def capture(channel, frame):
        info = frame.frame_info
        size = frame.size()
        if not size:
            return
        with lock:
            stats["frames"] += 1
            stats["bytes"] += size
            stats.update(rate=int(info.sample_rate), bits=int(info.sample_format),
                         channels=int(info.channel_count), timestamp=int(info.timestamp))
        if output:
            # 复制 PCM 后交给主线程写盘，回调不执行阻塞 I/O。
            try:
                pending.put_nowait(frame.data())
            except queue.Full:
                with lock:
                    stats["dropped"] += 1

    def flush():
        while True:
            try:
                data = pending.get_nowait()
            except queue.Empty:
                return
            output.write(data)

    try:
        if not sdk.service.initial(None, "audioShmExample"):
            raise RuntimeError("SDK initialization failed")
        if sdk.service.is_multi_device():
            raise RuntimeError("Run on the onboard brain; MediaBus reads /etc/robot/sdk_config.json")
        client = sdk.MotionLowLevelClient()
        if not client.connect():
            raise RuntimeError(f"Connect failed: {client.get_last_error()}")
        deadline = time.monotonic() + 5
        while client.get_state() != sdk.LowLevelState.kConnected:
            if time.monotonic() >= deadline:
                raise RuntimeError("Connection timeout")
            time.sleep(0.02)
        media = client.create_media_bus_client()
        if media is None or not media.setup():
            error = media.get_last_error() if media else -1
            raise RuntimeError(f"MediaBus setup failed ({error}); check /etc/robot/sdk_config.json")
        layout = media.get_media_layout()
        if layout is None or args.channel >= layout.mic_num:
            raise ValueError(f"Audio channel {args.channel} is not configured")
        if args.output:
            output = open(args.output, "wb")
        subscribed = media.start_raw_audio_frame(args.channel, capture)
        if not subscribed:
            raise RuntimeError(f"Audio subscription failed: {media.get_last_error()}")
        end = time.monotonic() + args.seconds
        report = time.monotonic() + 1
        try:
            while time.monotonic() < end:
                if output:
                    flush()
                if time.monotonic() >= report:
                    with lock:
                        snapshot = dict(stats)
                    print(f"shm audio ch={args.channel} {snapshot}", flush=True)
                    report += 1
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        media.stop_raw_audio_frame(args.channel)
        subscribed = False
        if output:
            flush()
        if not stats["frames"]:
            raise RuntimeError("No PCM frames: check MediaServer input and aiStream channel mapping")
        if stats["dropped"]:
            raise RuntimeError("PCM output incomplete: consumer queue overflow")
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(error)
        return 1
    finally:
        if media:
            if subscribed:
                media.stop_raw_audio_frame(args.channel)
            media.shutdown()
        if output:
            output.close()
        if client:
            client.disconnect()
        sdk.service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
