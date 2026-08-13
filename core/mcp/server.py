#!/usr/bin/env python3
"""quant-mcp server(官方 mcp 2.0 SDK,吸收 runtime/mcp/server.mjs)。

通过 stdio 跟 Claude Code 通信。注册 45 个 tool(来自 8 个 tools 模块)。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 直接跑 core/mcp/server.py 时 sys.path[0]=core/mcp/,需把项目根加进去才能 import core.*
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server.mcpserver.server import MCPServer

from core.mcp.tools import (
    health, state, discover, factor_db, graph_traversal, hypothesis_chain, persist, platform,
)

server = MCPServer(name="quant-mcp", version="0.1.0")

TOOL_MODULES = [health, state, discover, factor_db, graph_traversal, hypothesis_chain, persist, platform]


def _register_all() -> None:
    n = 0
    for mod in TOOL_MODULES:
        for name, fn in getattr(mod, "TOOLS", []):
            server.add_tool(fn, name=name, description=(fn.__doc__ or "").strip())
            n += 1
    return n


if __name__ == "__main__":
    _register_all()
    server.run(transport="stdio")
