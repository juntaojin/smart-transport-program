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

        detect.assert_called_once_with(context.frame, device_id="camera-7")
        self.assertEqual(result.properties["road_anomalies"], [])

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
        unload.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
