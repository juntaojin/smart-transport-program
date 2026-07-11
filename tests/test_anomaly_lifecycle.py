import importlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

import numpy as np


MODULE_NAME = "model_api.detect_anomalies"


class AnomalyLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module(MODULE_NAME)

    def setUp(self):
        self.module.unload_anomaly_model()

    def tearDown(self):
        self.module.unload_anomaly_model()

    def test_legacy_call_and_invalid_frames_degrade_gracefully(self):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        self.assertEqual(self.module.detect_anomalies(frame), [])
        self.assertEqual(self.module.detect_anomalies(None), [])
        self.assertEqual(
            self.module.detect_anomalies(np.zeros((12, 16), dtype=np.uint8)), []
        )

    def test_state_is_isolated_per_device_and_resettable(self):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        self.module.detect_anomalies(frame, "camera-a")
        self.module.detect_anomalies(frame, "camera-b")

        states = self.module._device_states
        self.assertEqual(len(states["camera-a"].change_detector._warmup_buffer), 1)
        self.assertEqual(len(states["camera-b"].change_detector._warmup_buffer), 1)

        self.module.reset_anomaly_state("camera-a")
        self.assertNotIn("camera-a", states)
        self.assertIn("camera-b", states)

    def test_resolution_change_resets_only_that_device(self):
        small = np.zeros((12, 16, 3), dtype=np.uint8)
        large = np.zeros((24, 32, 3), dtype=np.uint8)
        self.module.detect_anomalies(small, "camera-a")
        original = self.module._device_states["camera-a"]
        self.module.detect_anomalies(small, "camera-b")
        other = self.module._device_states["camera-b"]

        self.module.detect_anomalies(large, "camera-a")

        self.assertIsNot(original, self.module._device_states["camera-a"])
        self.assertIs(other, self.module._device_states["camera-b"])
        self.assertEqual(self.module._device_states["camera-a"].frame_shape, (24, 32))

    def test_same_device_is_safe_across_threads(self):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        threads = [
            threading.Thread(
                target=self.module.detect_anomalies, args=(frame,),
                kwargs={"device_id": "camera-a"},
            )
            for _ in range(10)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        state = self.module._device_states["camera-a"]
        self.assertEqual(len(state.change_detector._warmup_buffer), 10)

    def test_lazy_model_load_and_inference_are_serialized(self):
        calls = []

        class FakeBoxes:
            def __len__(self):
                return 0

        class FakeModel:
            def __call__(self, frame, **kwargs):
                calls.append(kwargs)
                return [types.SimpleNamespace(boxes=FakeBoxes())]

        fake_ultralytics = types.SimpleNamespace(YOLO=lambda path: FakeModel())
        with patch.dict(sys.modules, {"ultralytics": fake_ultralytics}), \
                patch.object(self.module.os.path, "isfile", return_value=True):
            self.assertTrue(self.module.load_anomaly_model("fake.pt", "cpu"))
            detector = self.module._NormalDetector()
            self.assertEqual(detector.detect(np.zeros((8, 8, 3), dtype=np.uint8)), [])

        self.assertEqual(calls[0]["device"], "cpu")


if __name__ == "__main__":
    unittest.main()
