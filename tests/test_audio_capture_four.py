"""Offline checks for four-channel PCM capture and partial-start cleanup."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('capture_four', Path(__file__).parents[1] / 'examples/example_audio_capture.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def frame(timestamp=1, pcm=b'\x00' * 32000, rate=16000):
    return types.SimpleNamespace(frame_info=types.SimpleNamespace(
        data_type=0, sample_rate=rate, sample_format=16, channel_count=1,
        timestamp=timestamp), data=lambda: pcm)


class CaptureTest(unittest.TestCase):
    def test_four_independent_files_and_exact_length(self):
        capture = module.Capture(1)
        with tempfile.TemporaryDirectory() as directory:
            for channel in range(4):
                capture.callback(channel)(channel, frame(pcm=bytes([channel]) * 33000))
            self.assertEqual(capture.save(Path(directory), []), 0)
            for channel in range(4):
                self.assertEqual((Path(directory) / f'channel{channel}.pcm').read_bytes(), bytes([channel]) * 32000)

    def test_missing_channel_fails(self):
        capture = module.Capture(1)
        for channel in range(3):
            capture.callback(channel)(channel, frame())
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(capture.save(Path(directory), []), 2)

    def test_bad_format_and_repeated_timestamp_fail(self):
        capture = module.Capture(1)
        receive = capture.callback(0)
        receive(0, frame(rate=8000))
        receive(0, frame(pcm=b'\x00\x00'))
        receive(0, frame(pcm=b'\x00\x00'))
        for channel in range(4):
            capture.callback(channel)(channel, frame(timestamp=2))
        self.assertTrue(capture.complete())
        self.assertEqual(capture.stats[0]['format_errors'], 1)
        self.assertEqual(capture.stats[0]['timestamp_errors'], 1)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(capture.save(Path(directory), []), 2)

    def test_partial_subscription_stops_all_started_channels(self):
        events = []
        def start(ch, cb):
            events.append(('start', ch))
            return ch < 2
        media = types.SimpleNamespace(setup=lambda host: True,
            start_raw_audio_frame=start,
            stop_raw_audio_frame=lambda ch: events.append(('stop', ch)),
            shutdown=lambda: events.append('media shutdown'))
        client = types.SimpleNamespace(connect=lambda: True,
            get_state=lambda: 'connected', create_media_bus_client=lambda: media,
            disconnect=lambda: events.append('disconnect'))
        fake = types.SimpleNamespace(MEDIA_ENABLED=True,
            HighLevelState=types.SimpleNamespace(kConnected='connected'),
            MotionHighLevelClient=lambda device: client,
            service=types.SimpleNamespace(initial=lambda *args: True,
                is_multi_device=lambda: False, shutdown=lambda: events.append('sdk shutdown')))
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'sdk', fake):
            self.assertEqual(module.main(['--seconds', '1', '--output', str(Path(directory) / 'capture')]), 2)
        self.assertEqual(events, [('start', 0), ('start', 1), ('start', 2),
            ('stop', 1), ('stop', 0), 'media shutdown', 'disconnect', 'sdk shutdown'])


if __name__ == '__main__':
    unittest.main()
