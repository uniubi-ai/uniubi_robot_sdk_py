"""Capture four PCM sources concurrently on the brain or an external host."""
import argparse
import json
from pathlib import Path
import threading
import time

import robot_motion_sdk as sdk


class Capture:
    def __init__(self, seconds):
        self.target = seconds * 16000 * 2
        self.lock = threading.Lock()
        self.buffers = [bytearray() for _ in range(4)]
        self.stats = [dict(frames=0, bytes=0, format_errors=0,
                           timestamp_errors=0, first_timestamp=None,
                           last_timestamp=None) for _ in range(4)]

    def callback(self, expected):
        def receive(channel, frame):
            with self.lock:
                data = self.buffers[expected]
                if len(data) >= self.target:
                    return
                stat = self.stats[expected]
                info = frame.frame_info
                pcm = frame.data()
                if (channel != expected or int(info.data_type) != 0 or
                        int(info.sample_rate) != 16000 or
                        int(info.sample_format) != 16 or
                        int(info.channel_count) != 1 or not pcm or len(pcm) % 2):
                    stat['format_errors'] += 1
                    return
                timestamp = int(info.timestamp)
                last = stat['last_timestamp']
                if last is not None and timestamp <= last:
                    stat['timestamp_errors'] += 1
                    return
                if stat['first_timestamp'] is None:
                    stat['first_timestamp'] = timestamp
                stat['last_timestamp'] = timestamp
                stat['frames'] += 1
                data.extend(pcm[:self.target - len(data)])
                stat['bytes'] = len(data)
        return receive

    def complete(self):
        with self.lock:
            return all(len(data) == self.target for data in self.buffers)

    def save(self, directory, errors):
        # Called only after every subscription and the media client are closed.
        channels = []
        for channel, (data, stat) in enumerate(zip(self.buffers, self.stats)):
            filename = f'channel{channel}.pcm'
            (directory / filename).write_bytes(data)
            channels.append(dict(channel=channel, file=filename, **stat))
        passed = (not errors and self.complete() and
                  all(s['frames'] and not s['format_errors'] and
                      not s['timestamp_errors'] for s in self.stats))
        summary = dict(result='PASS' if passed else 'FAIL',
                       format='16000 Hz, signed 16-bit little-endian, mono',
                       target_bytes_per_channel=self.target,
                       errors=errors, channels=channels)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2))
        return 0 if passed else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='', help='Robot address for remote audio')
    parser.add_argument('--device-id', default='', help='Robot SN for external hosts')
    parser.add_argument('--interface', default='', help='Network interface reaching the robot')
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 60:
        parser.error('--seconds must be 1..60')
    if bool(args.host) != bool(args.device_id):
        parser.error('--host and --device-id must be supplied together')
    if args.host and not args.interface:
        parser.error('External hosts require --interface')
    if not sdk.MEDIA_ENABLED:
        parser.error('The installed SDK must include media support')
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(str(error))
    capture = Capture(args.seconds)
    errors = []
    client = media = None
    subscribed = []
    initialized = False
    try:
        if args.interface:
            sdk.service.set_network_interface(args.interface)
        initialized = True
        if not sdk.service.initial(None, 'audioCaptureFour'):
            raise RuntimeError('SDK initialization failed')
        remote = sdk.service.is_multi_device()
        if remote != bool(args.host):
            raise ValueError('External hosts require --host and --device-id; brain local mode omits both')
        client = sdk.MotionHighLevelClient(args.device_id)
        if not client.connect():
            raise RuntimeError('Robot connection failed')
        deadline = time.monotonic() + 5
        while client.get_state() != sdk.HighLevelState.kConnected:
            if time.monotonic() >= deadline:
                raise RuntimeError('Robot connection timed out')
            time.sleep(0.02)
        media = client.create_media_bus_client()
        if media is None or not media.setup(args.host):
            raise RuntimeError('Audio setup failed')
        # Keep all four subscriptions active on one client.
        for channel in range(4):
            if not media.start_raw_audio_frame(channel, capture.callback(channel)):
                raise RuntimeError(f'Channel {channel}: subscription failed')
            subscribed.append(channel)
        deadline = time.monotonic() + args.seconds + 5
        while not capture.complete() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not capture.complete():
            errors.append('Capture timed out before all four channels were complete')
    except KeyboardInterrupt:
        errors.append('Interrupted by user')
    except Exception as error:
        errors.append(str(error))
    finally:
        def cleanup(label, operation):
            try:
                if operation() is False:
                    errors.append(label + ' failed')
            except Exception as error:
                errors.append(label + ': ' + str(error))
        if media is not None:
            for channel in reversed(subscribed):
                cleanup(f'Stop channel {channel}', lambda ch=channel: media.stop_raw_audio_frame(ch))
            cleanup('Media shutdown', media.shutdown)
        if client is not None:
            cleanup('Disconnect', client.disconnect)
        if initialized:
            cleanup('SDK shutdown', sdk.service.shutdown)
    try:
        return capture.save(args.output, errors)
    except OSError as error:
        print('Saving capture failed:', error)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
