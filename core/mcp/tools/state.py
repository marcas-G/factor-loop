"""state 工具(吸收 runtime/mcp/tools/state.mjs)。转发 run_store。"""
from core.mcp import run_store


def run_init(idea: str = None, factors: list = None, parentSession: str = None) -> dict:
    """创建新的研究 run(含 run_id 和 state.json)。"""
    return run_store.run_init(idea=idea, factors=factors, parent_session=parentSession)


def run_load(run_id: str) -> dict:
    """读取某个 run 的完整 state(用于断点续传)。"""
    return run_store.run_load(run_id)


def run_save(run_id: str, patch: dict) -> dict:
    """原子 merge patch 写 state。支持顶级字段或点分路径(如 'factors.0.failure_layer')。不允许整体覆盖 factors 数组。"""
    return run_store.run_save(run_id, patch)


def run_list() -> list:
    """列所有历史 run(按 started_at 倒序),返回摘要信息。"""
    return run_store.run_list()


TOOLS = [
    ("run_init", run_init),
    ("run_load", run_load),
    ("run_save", run_save),
    ("run_list", run_list),
]
