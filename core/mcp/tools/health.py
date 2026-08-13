"""health 工具(吸收 runtime/mcp/tools/health.mjs)。"""
from datetime import datetime, timezone


def health() -> dict:
    """检查 quant-mcp server 是否存活,返回当前时间戳"""
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


TOOLS = [("health", health)]
