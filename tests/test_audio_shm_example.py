"""Test the onboard Python example without a robot or native extension."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class AudioExampleTest(unittest.TestCase):
    def run_example(self, *, frames=True, enabled=True):
        events = []
        sdk = types.ModuleType("robot_motion_sdk")
        sdk.MEDIA_ENABLED = enabled
        sdk.LowLevelState = types.SimpleNamespace(kConnected=1)
        sdk.service = types.SimpleNamespace(
            initial=lambda *args: events.append("initial") or True,
            is_multi_device=lambda: False,
            shutdown=lambda: events.append("shutdown_service"),
        )
        frame = types.SimpleNamespace(
            frame_info=types.SimpleNamespace(sample_rate=16000, sample_format=16, channel_count=1, timestamp=123),
            size=lambda: 4, data=lambda: b"\x01\x02\x03\x04",
        )

        def subscribe(channel, callback):
            events.append("shm_subscribe")
            self.assertEqual(channel, 0)
            if frames:
                callback(channel, frame)
            return True

        media = types.SimpleNamespace(
            setup=lambda: events.append("setup_media") or True,
            get_media_layout=lambda: types.SimpleNamespace(mic_num=4),
            start_raw_audio_frame=subscribe,
            stop_raw_audio_frame=lambda channel: events.append("stop_audio"),
            shutdown=lambda: events.append("shutdown_media"),
        )
        client = types.SimpleNamespace(
            connect=lambda: events.append("connect") or True,
            get_state=lambda: 1,
            create_media_bus_client=lambda: media,
            disconnect=lambda: events.append("disconnect"),
        )
        sdk.MotionLowLevelClient = lambda: client
        # There is deliberately no AudioClient/TCP interface or motion-enable method.
        path = Path(__file__).resolve().parents[1] / "examples/example_audio.py"
        spec = importlib.util.spec_from_file_location("audio_example", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, robot_motion_sdk=sdk):
            spec.loader.exec_module(module)
        tick = iter(i * 0.2 for i in range(100))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "test.pcm"
            argv = [str(path), "--seconds", "1", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(module.time, "monotonic", side_effect=lambda: next(tick)), \
                    patch.object(module.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                result = module.main()
            data = output.read_bytes() if output.exists() else None
        return result, data, events

    def test_shared_memory_capture_and_cleanup(self):
        result, data, events = self.run_example()
        self.assertEqual(result, 0)
        self.assertEqual(data, b"\x01\x02\x03\x04")
        self.assertEqual(events[-4:], ["stop_audio", "shutdown_media", "disconnect", "shutdown_service"])

    def test_no_frames_is_failure(self):
        result, data, events = self.run_example(frames=False)
        self.assertNotEqual(result, 0)
        self.assertEqual(data, b"")
        self.assertEqual(events[-1], "shutdown_service")

    def test_media_disabled_exits_without_connecting(self):
        result, data, events = self.run_example(enabled=False)
        self.assertNotEqual(result, 0)
        self.assertIsNone(data)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
