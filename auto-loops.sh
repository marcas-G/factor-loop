#!/usr/bin/env bash
# auto-loops.sh [N] —— 每轮 research-loop 跑在全新 claude session,跑完销毁,开下一个
# 完成检测:读 quant run 的 state.json status==done(程序级铁信号,不猜屏幕文字)
#
# 用法:
#   nohup bash auto-loops.sh 1 > /home/lgao/work/quant/logs/loops/auto.out 2>&1 &
#   tail -f /home/lgao/work/quant/logs/loops/auto.out     # 驱动日志
#   tmux attach -t rloop1                                  # 看当前 session(Ctrl-b d 退出)
#
# 停止:
#   pkill -f auto-loops.sh
#   for s in $(tmux ls -F '#{session_name}' 2>/dev/null|grep rloop); do tmux kill-session -t "$s"; done
#
# 注意:N=1 检测完美可靠;N≥2 两路并发有小竞态(可能认错 run 提前 kill 一路),建议 N=1。

set -uo pipefail
N="${1:-1}"
WORKDIR="/home/lgao/work/quant"
RUNDIR="/home/lgao/.quant-runs"           # research run state 目录(每个 run_id 一个子目录)
MAXWAIT="${MAXWAIT:-1440}"                 # 单轮最多 1440×30s = 12h;check 等 DAG 一直轮询(平台排队不该放弃),这里给足兜底别误杀
LOGROOT="$WORKDIR/logs/loops"

command -v tmux >/dev/null || { echo "需要 tmux: sudo apt install tmux"; exit 1; }
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
cd "$WORKDIR" || { echo "cd $WORKDIR 失败"; exit 1; }
mkdir -p "$LOGROOT"

# 读某 run 的 state.json status
get_status() {
  python3 -c "import json;print(json.load(open('$RUNDIR/$1/state.json')).get('status',''))" 2>/dev/null
}

# 单车道循环:每轮一个全新 session,跑完销毁,开下一个
run_lane() {
  local lane="$1" sess="rloop$1" round=0 hit t before latest st
  while true; do
    round=$((round+1))
    echo "[$(date +%H:%M:%S)] 车道$lane === 第 $round 轮:开新 session ==="
    tmux kill-session -t "$sess" 2>/dev/null
    tmux new-session -d -s "$sess" -c "$WORKDIR" "claude --permission-mode bypassPermissions"
    sleep 5
    before=$(ls -1t "$RUNDIR" 2>/dev/null | head -1)   # 启动前最新 run(基准)
    tmux send-keys -t "$sess" "/research-loop" Enter
    # 轮询:等"比 before 新的 run"出现 且 status 变 done/paused
    hit=0; st=""
    for ((t=0; t<MAXWAIT; t++)); do
      sleep 30
      latest=$(ls -1t "$RUNDIR" 2>/dev/null | head -1)
      if [ "$latest" != "$before" ] && [ -n "$latest" ]; then
        st=$(get_status "$latest")
        case "$st" in
          done|paused) hit=1; echo "[$(date +%H:%M:%S)] 车道$lane 检测到 run=$latest status=$st"; break;;
        esac
      fi
    done
    tmux kill-session -t "$sess" 2>/dev/null
    echo "[$(date +%H:%M:%S)] 车道$lane 第 $round 轮结束($([ $hit = 1 ] && echo "完成 status=$st" || echo "超时兜底"))→ session 销毁,开下一个"
    sleep 6
  done
}

for ((i=1; i<=N; i++)); do
  run_lane "$i" &
  sleep 20   # 车道间错开
done
echo "[$(date +%H:%M:%S)] 已起 $N 条车道,state.json 检测循环中。tail -f $LOGROOT/auto.out"
wait
