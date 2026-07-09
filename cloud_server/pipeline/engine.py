from loguru import logger
from cloud_server.pipeline.context import FrameContext

class PipelineNode:
    """流水线节点基类，支持动态开关与延迟加载"""

    def __init__(self, name: str):
        self.name = name          # 节点唯一标识，用于 API 动态控制
        self.enabled = False      # 默认关闭，不占用算力
        self._model = None        # 模型实例占位符

    def load_model(self):
        """加载模型到显存/内存（由子类实现）"""
        pass

    def unload_model(self):
        """释放模型与显存（由子类实现）"""
        pass

    def toggle(self, state: bool):
        """控制节点开关与显存动态管理"""
        if state and not self.enabled:
            logger.info(f"Enabling node: {self.name}. Loading model...")
            self.load_model()
            self.enabled = True
        elif not state and self.enabled:
            logger.info(f"Disabling node: {self.name}. Unloading model...")
            self.unload_model()
            self.enabled = False

    def process(self, context: FrameContext) -> FrameContext:
        """数据处理入口，关闭时直接放行实现 0 算力开销"""
        if not self.enabled:
            return context
        try:
            return self._do_process(context)
        except Exception as e:
            logger.error(f"Error processing node {self.name}: {e}")
            return context

    def _do_process(self, context: FrameContext) -> FrameContext:
        """实际的推理逻辑（由子类实现）"""
        raise NotImplementedError


class InferencePipeline:
    """流水线调度器：按添加顺序依次执行，支持运行时动态管控"""

    def __init__(self):
        self.nodes: dict[str, PipelineNode] = {}

    def add_node(self, node: PipelineNode):
        self.nodes[node.name] = node
        logger.info(f"Added pipeline node: {node.name} (enabled={node.enabled})")

    def toggle_node(self, node_name: str, state: bool):
        """API 触发此方法，动态控制节点的算力分配"""
        if node_name in self.nodes:
            self.nodes[node_name].toggle(state)
        else:
            logger.warning(f"Pipeline node '{node_name}' not found for toggling.")

    def execute(self, context: FrameContext) -> FrameContext:
        for node in self.nodes.values():
            context = node.process(context)
        return context
