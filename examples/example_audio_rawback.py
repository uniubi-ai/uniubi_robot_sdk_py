"""Play 16 kHz/s16le/mono PCM through onboard or Remote MediaBus."""
import argparse
import time
import robot_motion_sdk as sdk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcm")
    parser.add_argument("--volume", type=int, default=20)
    parser.add_argument("--capture-channel", type=int, help="Also capture PCM on the same MediaBus client")
    parser.add_argument("--host", default="", help="DV500 address for Remote mode")
    parser.add_argument("--device-id", default="", help="Target robot SN for Remote mode")
    parser.add_argument("--interface", default="", help="DDS network interface")
    args = parser.parse_args()
    if args.capture_channel is not None and args.capture_channel < 0:
        parser.error("capture channel must be nonnegative")
    if not 0 <= args.volume <= 100:
        parser.error("volume must be 0..100")
    if not sdk.MEDIA_ENABLED:
        print("This SDK was built without media support")
        return 1
    client = media = playback = None
    capturing = False
    captured = 0

    def capture(channel, frame):
        nonlocal captured
        captured += 1

    try:
        if args.interface:
            sdk.service.set_network_interface(args.interface)
        if not sdk.service.initial(None, "audioRawBackExample"):
            raise RuntimeError("SDK initialization failed")
        remote = sdk.service.is_multi_device()
        if remote and (not args.host or not args.device_id):
            raise ValueError("Remote mode requires --host and --device-id")
        if not remote and (args.host or args.device_id):
            raise ValueError("Local mode does not use --host or --device-id")
        client = sdk.MotionHighLevelClient(args.device_id)
        if not client.connect():
            raise RuntimeError("Connection failed")
        deadline = time.monotonic() + 5
        while client.get_state() != sdk.HighLevelState.kConnected:
            if time.monotonic() >= deadline:
                raise RuntimeError("Connection timeout")
            time.sleep(0.02)
        media = client.create_media_bus_client()
        if media is None or not media.setup(args.host):
            raise RuntimeError("MediaBus setup failed; check /etc/robot/sdk_config.json")
        if args.capture_channel is not None:
            capturing = media.start_raw_audio_frame(args.capture_channel, capture)
            if not capturing:
                raise RuntimeError(f"Capture failed: {media.get_last_error()}")
        playback = media.create_audio_raw_back()
        if playback is None:
            raise RuntimeError(f"RawBack creation failed: {media.get_last_error()}")
        if not playback.setup():
            raise RuntimeError(f"RawBack setup failed: {playback.get_last_error()}")
        deadline = time.monotonic() + 5
        while not playback.ready():
            if time.monotonic() >= deadline:
                raise RuntimeError(f"RawBack ready timeout: {playback.get_last_error()}")
            time.sleep(0.02)
        if not playback.set_volume(args.volume):
            raise RuntimeError(f"RawBack volume failed: {playback.get_last_error()}")
        info = sdk.AudioFrameInfo()
        info.sample_rate, info.sample_format, info.channel_count = 16000, 16, 1
        sent = 0
        tail_frames = 0
        deadline = time.monotonic()
        with open(args.pcm, "rb") as pcm:
            while True:
                data = pcm.read(1280)
                if not data:
                    if not sent:
                        raise ValueError("PCM file is empty")
                    if tail_frames == 2:
                        break
                    tail_frames += 1  # Flush the two-frame prebuffer, also after underrun.
                if len(data) % 2:
                    raise ValueError("PCM byte count must be even")
                time.sleep(max(0, deadline - time.monotonic()))
                info.timestamp = int(time.monotonic() * 1_000_000)
                info.sequence = sent
                frame = sdk.AudioFrame(data.ljust(1280, b"\0"), info)
                ready_until = time.monotonic() + 2
                ok = playback.write(frame)
                while not ok and not sent and time.monotonic() < ready_until:
                    time.sleep(0.02)
                    ok = playback.write(frame)
                if not ok:
                    raise RuntimeError("RawBack write failed")
                sent += 1
                deadline = max(deadline + 0.04, time.monotonic())
        # Protocol has no drain acknowledgement; allow the mixer tail to finish.
        time.sleep(0.3)
        if capturing and not captured:
            raise RuntimeError("No audio capture frames received")
        print(f"Published {sent} PCM frames; captured={captured}; mode={'remote' if remote else 'local'}")
        return 0
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(error)
        return 1
    finally:
        if playback is not None:
            playback.shutdown()
        if media is not None:
            if capturing:
                media.stop_raw_audio_frame(args.capture_channel)
            media.shutdown()
        if client is not None:
            client.disconnect()
        sdk.service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
