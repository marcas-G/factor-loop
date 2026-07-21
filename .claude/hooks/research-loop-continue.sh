#!/bin/bash
# Stop hook: research-loop 衔接硬规则的代码兜底。
#
# 问题:research-loop SKILL 写了"每 Step 完成立即下 tool call,禁纯文字回合断流",
# 但 LLM 经常不遵守,输出纯文字回合结束 turn → run 卡在 status=running(53/93)。
#
# 治法:claude 结束 turn 时触发本 hook,检测最新 run state.json
#   若 status==running 且 factors 有 pending/submitting → exit 2(block),
#   强制 claude 继续(把 reason 喂回去),禁止纯文字回合断流。
#   mtime 近 30 分钟才管,避免老 running run 误 block 普通对话。
#
# 真要停(平台卡死/人工干预):手动改 state.json status=paused(hook 放行)。

# 只在 research-loop session 生效(读 stdin transcript,非 research-loop 放行,避免误 block 交互对话)
INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import json,sys;print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)
[ -z "$TRANSCRIPT" ] && exit 0  # 无 transcript(stdin 异常/手动跑),保守放行
if ! grep -ql 'research-loop\|run-factor-agent\|persist_factor' "$TRANSCRIPT" 2>/dev/null; then
  exit 0  # 非 research-loop session(交互对话),放行
fi

RD="${QUANT_MCP_RUNS_ROOT:-$HOME/.quant-runs}"
LATEST=$(ls -1t "$RD"/*/state.json 2>/dev/null | head -1)
[ -z "$LATEST" ] && exit 0

# mtime 近 30 分钟才管(避免老 running run 误 block 普通对话)
find "$LATEST" -mmin -30 >/dev/null 2>&1 || exit 0

read -r STATUS PENDING <<EOF
$(python3 -c "
import json
s=json.load(open('$LATEST'))
print(s.get('status',''), sum(1 for f in s.get('factors',[]) if f.get('status') in (None,'pending','submitting')))
" 2>/dev/null)
EOF

[ "$STATUS" != "running" ] && exit 0
if [ "${PENDING:-0}" -gt 0 ]; then
  cat <<EOF >&2
research-loop 衔接硬规则:run status=running 且 ${PENDING} 个 factor 仍 pending/submitting。
按 SKILL 衔接规则,立即继续当前 Step 的下一个 tool call(禁止纯文字回合断流)。
若确需停(平台卡死/人工干预),手动改 state.json status=paused 后我再放行。
EOF
  exit 2  # block:claude 继续,stderr 作 reason 喂回
fi
exit 0
