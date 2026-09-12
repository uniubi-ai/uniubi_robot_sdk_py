"""Public media API validation; no device connection is made."""
import types
import unittest
import robot_motion_sdk as sdk

class MediaBindingTest(unittest.TestCase):
    def test_media_enabled_by_default(self):
        self.assertTrue(sdk.MEDIA_ENABLED)
        self.assertIn("AudioRawBackStream", sdk.__all__)
        self.assertFalse(hasattr(sdk, "AudioClient"))
        self.assertFalse(hasattr(sdk, "AudioPlaybackConfig"))
        self.assertTrue(hasattr(sdk.MediaBusError, "kNotSupported"))

    def frame(self):
        info = sdk.AudioFrameInfo()
        info.sample_rate, info.sample_format, info.channel_count = 16000, 16, 1
        info.timestamp, info.sequence = 123456, 17
        return sdk.AudioFrame(bytes([1, 2]) * 640, info)

    def test_local_and_remote_setup_host(self):
        hosts = []
        media = sdk.MediaBusClient(types.SimpleNamespace(setup=lambda host: hosts.append(host) or True))
        self.assertTrue(media.setup())
        self.assertTrue(media.setup("192.0.2.1"))
        self.assertEqual(hosts, ["", "192.0.2.1"])

    def test_capture_wraps_and_retains_frame(self):
        source = self.frame()
        retained = []
        impl = types.SimpleNamespace(start_raw_audio_frame=lambda ch, cb: cb(ch, source._impl) or True)
        self.assertTrue(sdk.MediaBusClient(impl).start_raw_audio_frame(3, lambda ch, frame: retained.append((ch, frame))))
        del source
        channel, frame = retained[0]
        self.assertEqual(channel, 3)
        self.assertIsInstance(frame, sdk.AudioFrame)
        self.assertEqual(frame.data(), bytes([1, 2]) * 640)
        self.assertEqual(frame.frame_info.timestamp, 123456)

    def test_rawback_lifecycle_and_frame_adapter(self):
        writes, events = [], []
        stream = types.SimpleNamespace(setup=lambda: events.append("setup") or True,
            ready=lambda: True, get_last_error=lambda: 0,
            write=lambda native: writes.append(native) or True,
            reset=lambda: events.append("reset") or True,
            set_volume=lambda volume: events.append(volume) or True,
            shutdown=lambda: events.append("shutdown"))
        media = sdk.MediaBusClient(types.SimpleNamespace(create_audio_raw_back=lambda: stream))
        raw = media.create_audio_raw_back()
        self.assertIsInstance(raw, sdk.AudioRawBackStream)
        self.assertTrue(raw.setup()); self.assertTrue(raw.ready())
        self.assertEqual(raw.get_last_error(), sdk.AudioRawBackError.kNone)
        frame = self.frame()
        self.assertTrue(raw.write(frame)); self.assertTrue(raw.reset()); self.assertTrue(raw.set_volume(20))
        raw.shutdown()
        self.assertEqual(writes, [frame._impl])
        self.assertEqual(events, ["setup", "reset", 20, "shutdown"])

    def test_missing_rawback_stays_none(self):
        media = sdk.MediaBusClient(types.SimpleNamespace(create_audio_raw_back=lambda: None))
        self.assertIsNone(media.create_audio_raw_back())

if __name__ == "__main__": unittest.main()
