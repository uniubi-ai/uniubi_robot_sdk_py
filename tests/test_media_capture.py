"""Offline capture-contract tests; no native SDK or robot is required.

Run: python3 -m unittest discover -s tests -p test_media_capture.py
"""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class Frame:
    def __init__(self, pts, bad=False, short_row=False):
        self.frame_info = types.SimpleNamespace(
            data_type=0, sample_rate=8000 if bad else 16000,
            sample_format=16, channel_count=1, timestamp=pts,
            width=4, height=2, pixel_format=1)
        self.short_row = short_row

    def size(self):
        return 10000  # Deliberately does not divide the 32000-byte target.

    def view(self):
        return bytes(self.size())  # Silence is a valid capture.

    def plane_view(self, plane):
        rows = [b'abcdXX', b'efghYY'] if plane == 0 else [b'ijklZZ']
        return types.SimpleNamespace(row_view=lambda row: rows[row][:2] if self.short_row else rows[row])


class Media:
    def __init__(self, mode):
        self.mode = mode
        self.audio, self.video = {}, {}
        self.closed = False
        self.now = 0.0
        self.tick = 0

    def start_raw_audio_frame(self, ch, cb):
        if self.mode == 'subscribe-fail' and ch == 3:
            return False
        self.audio[ch] = cb
        return True

    def start_raw_video_frame(self, ch, cb):
        self.video[ch] = cb
        return True

    def stop_raw_audio_frame(self, ch):
        del self.audio[ch]

    def stop_raw_video_frame(self, ch):
        del self.video[ch]

    def shutdown(self):
        self.closed = True

    def sleep(self, _):
        self.now += 0.2
        self.tick += 1
        for ch, cb in self.audio.items():
            if self.mode == 'missing' and ch == 3:
                continue
            pts = 1 if self.mode == 'duplicate' else self.tick
            cb(ch, Frame(pts, bad=self.mode == 'bad-format'))
        for ch, cb in self.video.items():
            cb(ch, Frame(self.tick, short_row=self.mode == 'bad-stride'))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        stub = types.ModuleType('robot_motion_sdk')
        stub.MediaPixelFormat = types.SimpleNamespace(mediaPixelFormatNV21=1)
        with patch.dict(sys.modules, robot_motion_sdk=stub):
            self.mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples/example_media_frames.py'))

    def capture(self, mode='ok'):
        media = Media(mode)
        fn = self.mod['_capture_all']
        fn.__globals__['time'] = types.SimpleNamespace(monotonic=lambda: media.now, sleep=media.sleep)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            if mode == 'save-fail':
                (output / 'dmic_ch0.pcm').mkdir()
            options = self.mod['Options'](seconds=1, capture_dir=output)
            with contextlib.redirect_stdout(io.StringIO()):
                ok = fn(media, options)
            if mode == 'ok':
                self.assertEqual([p.stat().st_size for p in sorted(output.glob('*.pcm'))], [32000] * 4)
                images = list(output.glob('*.nv21'))
                self.assertEqual(len(images), 10)
                self.assertTrue(all(p.read_bytes() == b'abcdefghijkl' for p in images))
        self.assertTrue(media.closed)
        self.assertFalse(media.audio)
        self.assertFalse(media.video)
        return ok

    def test_silence_exact_length_and_separate_padded_planes(self):
        self.assertTrue(self.capture())

    def test_missing_stream_times_out(self):
        self.assertFalse(self.capture('missing'))

    def test_duplicate_timestamps_fail(self):
        self.assertFalse(self.capture('duplicate'))

    def test_wrong_audio_format_fails(self):
        self.assertFalse(self.capture('bad-format'))

    def test_short_video_row_fails(self):
        self.assertFalse(self.capture('bad-stride'))

    def test_partial_subscription_cleans_up(self):
        self.assertFalse(self.capture('subscribe-fail'))

    def test_save_error_fails(self):
        self.assertFalse(self.capture('save-fail'))

    def test_capture_arguments(self):
        parse = self.mod['_parse_args']
        self.assertEqual(parse(['example', '--capture-all', '/tmp/new']).seconds, 20)
        self.assertEqual(parse(['example', '--pcm4', '/tmp/new', '60', '-']).network_interface, '')
        for args in (['--capture-all'], ['--pcm4', '/tmp/new', '0'],
                     ['--pcm4', '/tmp/new', '61'], ['--pcm4', '/tmp/new', '20x']):
            with self.assertRaises(ValueError):
                parse(['example'] + args)


if __name__ == '__main__':
    unittest.main()
