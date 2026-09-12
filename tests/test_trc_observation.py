"""Run against a built SDK package; no robot connection is required."""
import unittest
import robot_motion_sdk as sdk


class TRCObservationTest(unittest.TestCase):
    def test_native_frame_round_trip(self):
        frame = sdk.TRCStickFrame()
        self.assertEqual(frame.valid, 0)
        frame.valid = 1
        frame.control_id = 17
        frame.buttons = [1, 0, 1]
        frame.axes = [0.25, -0.5]
        self.assertEqual(frame.valid, 1)
        self.assertEqual(frame.control_id, 17)
        self.assertEqual(frame.buttons[:3], [1, 0, 1])
        self.assertEqual(frame.axes[:2], [0.25, -0.5])
        self.assertTrue(all(value == 0 for value in frame.buttons[3:]))
        self.assertTrue(all(value == 0 for value in frame.axes[2:]))

    def test_motion_observation_exposes_trc(self):
        self.assertTrue(hasattr(sdk.LowLevelMotionObserved, "trc"))


if __name__ == "__main__":
    unittest.main()
