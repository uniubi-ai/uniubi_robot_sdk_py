"""Exercise the real playback example with a one-frame PCM input and a stub SDK."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class RawBackExampleTest(unittest.TestCase):
    def test_local_short_input(self):
        self.run_example(False)

    def test_remote_short_input(self):
        self.run_example(True)

    def run_example(self, remote):
        frames = []
        events = []
        readiness = iter([False, False, True])
        playback = types.SimpleNamespace(
            ready=lambda: next(readiness, True),
            write=lambda frame: frames.append(frame) or True,
            setup=lambda: True,
            set_volume=lambda value: True,
            shutdown=lambda: events.append("shutdown"),
        )
        media = types.SimpleNamespace(
            setup=lambda host: self.assertEqual(host, "192.0.2.1" if remote else "") or True,
            create_audio_raw_back=lambda: playback,
            shutdown=lambda: events.append("media_shutdown"),
        )
        client = types.SimpleNamespace(
            connect=lambda: True, get_state=lambda: 1,
            create_media_bus_client=lambda: media,
            disconnect=lambda: events.append("disconnect"),
        )
        sdk = types.ModuleType("robot_motion_sdk")
        sdk.MEDIA_ENABLED = True
        sdk.HighLevelState = types.SimpleNamespace(kConnected=1)
        sdk.MotionHighLevelClient = lambda sn: client
        sdk.AudioFrameInfo = types.SimpleNamespace
        sdk.AudioFrame = lambda data, info: data
        sdk.service = types.SimpleNamespace(
            initial=lambda *args: True, is_multi_device=lambda: remote,
            shutdown=lambda: events.append("service_shutdown"),
        )
        path = Path(__file__).resolve().parents[1] / "examples/example_audio_rawback.py"
        spec = importlib.util.spec_from_file_location("rawback_example", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, robot_motion_sdk=sdk):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            pcm = Path(folder) / "short.pcm"
            pcm.write_bytes(bytes([1, 2]) * 320)
            with patch.object(sys, "argv", [str(path), str(pcm)] + (["--host", "192.0.2.1", "--device-id", "test-sn"] if remote else [])), patch.object(module.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0], bytes([1, 2]) * 320 + bytes(640))
        self.assertEqual(frames[1:], [bytes(1280), bytes(1280)])
        self.assertEqual(events, ["shutdown", "media_shutdown", "disconnect", "service_shutdown"])


if __name__ == "__main__":
    unittest.main()
