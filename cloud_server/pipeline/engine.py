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
    TRACK_ONLY_NODES = {"vehicle_detection", "tracking", "transform"}

    def __init__(self):
        self.nodes: dict[str, PipelineNode] = {}

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
            context = node.process(context, skip=skip)
        return context
