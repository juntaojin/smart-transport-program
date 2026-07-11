import threading
import time

from loguru import logger
from cloud_server.pipeline.context import FrameContext

class PipelineNode:
    def __init__(self, name: str):
        self.name = name
        self.enabled = False
        self._model = None

    def load_model(self):
        pass

    def unload_model(self):
        pass

    def toggle(self, state: bool):
        if state and not self.enabled:
            logger.info(f"Enabling node: {self.name}. Loading model...")
            self.load_model()
            self.enabled = True
        elif not state and self.enabled:
            logger.info(f"Disabling node: {self.name}. Unloading model...")
            self.unload_model()
            self.enabled = False

    def process(self, context: FrameContext, *, skip: bool = False) -> FrameContext:
        if skip or not self.enabled:
            return context
        try:
            return self._do_process(context)
        except Exception as e:
            logger.error(f"Error processing node {self.name}: {e}")
            return context

    def _do_process(self, context: FrameContext) -> FrameContext:
        raise NotImplementedError


class InferencePipeline:
    # Lightweight frames keep detection/tracking current. Expensive OCR and other
    # analysis nodes only run on full frames (currently one out of every 15).
    TRACK_ONLY_NODES = {"vehicle_detection", "tracking", "transform"}

    def __init__(self):
        self.nodes: dict[str, PipelineNode] = {}
        self._timing_lock = threading.Lock()
        self._timing_started_at = time.monotonic()
        self._node_elapsed: dict[str, float] = {}
        self._node_calls: dict[str, int] = {}

    def add_node(self, node: PipelineNode):
        self.nodes[node.name] = node
        logger.info(f"Added pipeline node: {node.name} (enabled={node.enabled})")

    def toggle_node(self, node_name: str, state: bool):
        if node_name in self.nodes:
            self.nodes[node_name].toggle(state)
        else:
            logger.warning(f"Pipeline node '{node_name}' not found for toggling.")

    def execute(self, context: FrameContext, mode: str = "full") -> FrameContext:
        if mode == "skip":
            return context

        for node in self.nodes.values():
            skip = (mode == "track" and node.name not in self.TRACK_ONLY_NODES)
            started_at = time.perf_counter()
            context = node.process(context, skip=skip)
            if node.enabled and not skip:
                elapsed = time.perf_counter() - started_at
                with self._timing_lock:
                    self._node_elapsed[node.name] = self._node_elapsed.get(node.name, 0.0) + elapsed
                    self._node_calls[node.name] = self._node_calls.get(node.name, 0) + 1

        self._log_timing_stats()
        return context

    def _log_timing_stats(self):
        now = time.monotonic()
        with self._timing_lock:
            elapsed = now - self._timing_started_at
            if elapsed < 5.0:
                return

            parts = []
            for name, total in self._node_elapsed.items():
                calls = self._node_calls.get(name, 0)
                if calls:
                    parts.append(f"{name}={total / calls * 1000:.1f}ms/{calls}")

            self._timing_started_at = now
            self._node_elapsed = {}
            self._node_calls = {}

        if parts:
            logger.info(f"[Pipeline Stats] window={elapsed:.1f}s, " + ", ".join(parts))
