import unittest
from unittest.mock import patch

import numpy as np

from cloud_server.pipeline.context import FrameContext
from cloud_server.pipeline.nodes.anomaly_node import AnomalyDetectionNode


class AnomalyNodeTests(unittest.TestCase):
    def test_node_passes_device_id(self):
        node = AnomalyDetectionNode()
        context = FrameContext(
            frame_data=np.zeros((8, 8, 3), dtype=np.uint8),
            timestamp=0.0,
            device_id="camera-7",
        )
        with patch(
            "cloud_server.pipeline.nodes.anomaly_node.detect_anomalies",
            return_value=[],
        ) as detect:
            result = node._do_process(context)

        detect.assert_called_once_with(
            context.frame,
            device_id="camera-7",
            timestamp=0.0,
            normal_boxes=None,
        )
        self.assertEqual(result.properties["road_anomalies"], [])

    def test_node_passes_vehicle_boxes_as_normal_context(self):
        node = AnomalyDetectionNode()
        context = FrameContext(
            frame_data=np.zeros((8, 8, 3), dtype=np.uint8),
            timestamp=12.5,
            device_id="camera-8",
        )
        context.properties["vehicle_boxes"] = [[1, 2, 3, 4]]
        with patch(
            "cloud_server.pipeline.nodes.anomaly_node.detect_anomalies",
            return_value=[],
        ) as detect:
            node._do_process(context)

        detect.assert_called_once_with(
            context.frame,
            device_id="camera-8",
            timestamp=12.5,
            normal_boxes=[[1, 2, 3, 4]],
        )

    def test_node_lifecycle_uses_portable_configuration(self):
        node = AnomalyDetectionNode()
        with patch(
            "cloud_server.pipeline.nodes.anomaly_node.reset_anomaly_state"
        ) as reset, patch(
            "cloud_server.pipeline.nodes.anomaly_node.load_anomaly_model",
            return_value=True,
        ) as load, patch(
            "cloud_server.pipeline.nodes.anomaly_node.unload_anomaly_model"
        ) as unload:
            node.load_model()
            node.unload_model()

        reset.assert_called_once_with()
        load.assert_called_once()
        _, args, kwargs = load.mock_calls[0]
        self.assertEqual(kwargs["bank_frames"], 5)
        self.assertEqual(kwargs["alert_frames"], 2)
        self.assertEqual(kwargs["max_age"], 6)
        self.assertEqual(kwargs["min_area"], 160)
        self.assertEqual(kwargs["diff_thresh"], 26)
        self.assertEqual(kwargs["min_extent"], 0.18)
        self.assertEqual(kwargs["min_box_size"], 8)
        self.assertTrue(kwargs["stabilization_enabled"])
        self.assertEqual(kwargs["max_jitter_px"], 20)
        self.assertEqual(kwargs["alert_seconds"], 0.8)
        self.assertEqual(kwargs["max_missing_seconds"], 0.5)
        self.assertEqual(kwargs["static_edge_suppression_px"], 3)
        self.assertEqual(kwargs["vehicle_mask_padding"], 8)
        unload.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
