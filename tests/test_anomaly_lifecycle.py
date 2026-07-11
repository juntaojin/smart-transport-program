import importlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

import cv2
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
        self.assertTrue(state.change_detector.is_ready)
        self.assertEqual(state.change_detector.bank_frames, 5)

    def _configure_fast_detector(self):
        self.module._bank_frames = 3
        self.module._alert_frames = 1
        self.module._max_age = 2
        self.module._min_area = 40
        self.module._diff_thresh = 20
        self.module._min_extent = 0.12
        self.module._min_box_size = 5
        self.module._stabilization_enabled = True
        self.module._max_jitter_px = 20
        self.module._alert_seconds = 0.2
        self.module._max_missing_seconds = 0.3
        self.module._static_edge_suppression_px = 3
        self.module._vehicle_mask_padding = 8
        self.module.reset_anomaly_state()

    def _road_frame(self, shift_x=0, shift_y=0, with_object=False):
        frame = np.full((120, 160, 3), 90, dtype=np.uint8)
        cv2.line(frame, (20 + shift_x, 25 + shift_y), (140 + shift_x, 25 + shift_y), (245, 245, 245), 4)
        cv2.line(frame, (30 + shift_x, 80 + shift_y), (130 + shift_x, 80 + shift_y), (230, 230, 230), 3)
        cv2.circle(frame, (35 + shift_x, 55 + shift_y), 3, (140, 140, 140), -1)
        cv2.circle(frame, (125 + shift_x, 55 + shift_y), 3, (140, 140, 140), -1)
        if with_object:
            cv2.rectangle(frame, (70, 52), (91, 73), (15, 15, 15), -1)
        return frame

    def test_jittered_road_markings_do_not_alert(self):
        with patch.object(self.module.os.path, "isfile", return_value=True), \
                patch.object(self.module._NormalDetector, "detect", return_value=[]):
            self._configure_fast_detector()
            timestamps = [0.0, 0.1, 0.2, 0.5, 0.8, 1.1]
            shifts = [(0, 0), (1, 0), (-1, 1), (2, 0), (-2, -1), (1, 1)]
            outputs = []
            for ts, (sx, sy) in zip(timestamps, shifts):
                outputs.append(self.module.detect_anomalies(
                    self._road_frame(sx, sy), "jitter", timestamp=ts
                ))

        self.assertTrue(all(output == [] for output in outputs))

    def test_synthetic_object_alerts_after_time_persistence(self):
        with patch.object(self.module.os.path, "isfile", return_value=True), \
                patch.object(self.module._NormalDetector, "detect", return_value=[]):
            self._configure_fast_detector()
            for ts in [0.0, 0.1, 0.2]:
                self.module.detect_anomalies(self._road_frame(), "object", timestamp=ts)
            self.assertEqual(
                self.module.detect_anomalies(
                    self._road_frame(with_object=True), "object", timestamp=0.3
                ),
                [],
            )
            alerts = self.module.detect_anomalies(
                self._road_frame(with_object=True), "object", timestamp=0.55
            )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["label"], "road_anomaly")
        self.assertGreaterEqual(alerts[0]["confidence"], 1.0)

    def test_vehicle_box_suppresses_object_alert(self):
        with patch.object(self.module.os.path, "isfile", return_value=True), \
                patch.object(self.module._NormalDetector, "detect", return_value=[]):
            self._configure_fast_detector()
            for ts in [0.0, 0.1, 0.2]:
                self.module.detect_anomalies(self._road_frame(), "vehicle", timestamp=ts)
            for ts in [0.3, 0.55, 0.8]:
                alerts = self.module.detect_anomalies(
                    self._road_frame(with_object=True),
                    "vehicle",
                    timestamp=ts,
                    normal_boxes=[[62, 44, 99, 81]],
                )
                self.assertEqual(alerts, [])

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
