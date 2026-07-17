#!/usr/bin/env bash
# auto-loops.sh —— 每轮 research-loop 跑在全新 claude session,跑完销毁,开下一个
# 完成检测:读 quant run 的 state.json status==done(程序级铁信号,不猜屏幕文字)
#
# ============ 用法 ============
#   启动(N=车道数,默认1,后台推荐):
#       nohup bash auto-loops.sh 1 > logs/loops/auto.out 2>&1 &
#       tail -f logs/loops/auto.out        # 驱动日志
#       tmux attach -t rloop1               # 看当前 session(Ctrl-b d 退出)
#
#   优雅关闭(跑完当前轮再停,不中断正在跑的研究):
#       bash auto-loops.sh stop
#
#   查状态:
#       bash auto-loops.sh status
#
#   强制清理(不等当前轮,慎用):
#       pkill -f auto-loops.sh
#       for s in $(tmux ls -F '#{session_name}' 2>/dev/null | grep '^rloop'); do tmux kill-session -t "$s"; done
#
# ============ 优雅关闭机制 ============
#   stop 只创建 STOP 标志文件,【不杀进程】 ->
#   当前 tmux 里的 research-loop 继续跑到 done(轮询循环不检查标志,保证当前轮必跑完) ->
#   run_lane 检测到 done 后 kill-session -> 回循环见 STOP 标志 -> 不开下一轮,脚本自然退出。
#   即:关闭后必定跑完当前轮次。
#
# ============ 备注 ============
#   ROUNDS 环境变量:每车道跑几轮(0=无限默认;ROUNDS=10 跑10轮自停,cron 定时用)。
#   N=1 检测完美可靠;N>=2 两路并发有小竞态(可能认错 run 提前 kill 一路),建议 N=1。

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # 脚本所在目录 = 项目根
WORKDIR="$SCRIPT_DIR"
RUNDIR="${RUNDIR:-$HOME/.quant-runs}"      # research run state 目录
LOGROOT="$WORKDIR/logs/loops"
PIDFILE="$LOGROOT/auto.pid"
STOPFILE="$LOGROOT/STOP"
MAXWAIT="${MAXWAIT:-2880}"                  # 单轮最多 2880*30s = 24h(平台排队不该放弃,给足兜底别误杀)
ROUNDS="${ROUNDS:-0}"                       # 0=无限;ROUNDS=K 跑 K 轮自停

mkdir -p "$LOGROOT"
command -v tmux >/dev/null   || { echo "需要 tmux: sudo apt install tmux"; exit 1; }
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }

get_status()  { python3 -c "import json;print(json.load(open('$RUNDIR/$1/state.json')).get('status',''))" 2>/dev/null; }
latest_run()  { ls -1t "$RUNDIR" 2>/dev/null | head -1; }

# ---------------- 子命令: stop ----------------
do_stop() {
  if [ ! -f "$PIDFILE" ]; then
    echo "未运行(无 $PIDFILE)。若确有残留: pkill -f auto-loops.sh + 清 rloop tmux"
    exit 1
  fi
  local pid; pid=$(cat "$PIDFILE" 2>/dev/null)
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "主进程 pid=$pid 已不在,清理 pidfile/STOP"
    rm -f "$PIDFILE" "$STOPFILE"
    exit 0
  fi
  touch "$STOPFILE"
  local cur; cur=$(latest_run)
  echo "已请求优雅关闭(主进程 pid=$pid)。"
  echo "当前轮 run=$cur 会跑完到 done,之后不开下一轮、tmux 自动关闭、脚本退出。"
  echo "进度: tail -f $LOGROOT/auto.out"
}

# ---------------- 子命令: status ----------------
do_status() {
  echo "=== auto-loops 状态 ==="
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "主进程: pid=$(cat "$PIDFILE") 运行中"
  else
    echo "主进程: 未运行"
  fi
  if [ -f "$STOPFILE" ]; then
    echo "STOP 标志: 存在(关闭中——跑完当前轮即停)"
  else
    echo "STOP 标志: 无(正常循环)"
  fi
  echo "--- tmux rloop* ---"
  tmux ls 2>/dev/null | grep '^rloop' || echo "(无 rloop session)"
  echo "--- 最新 run ---"
  local cur; cur=$(latest_run)
  [ -n "$cur" ] && echo "run=$cur status=$(get_status "$cur")" || echo "(无 run)"
}

# ---------------- 子命令分发 ----------------
case "${1:-1}" in
  stop)   do_stop; exit 0 ;;
  status) do_status; exit 0 ;;
esac

# ---------------- 正常启动 ----------------
N="${1:-1}"
case "$N" in
  ''|*[!0-9]*) echo "用法: bash auto-loops.sh [N|stop|status]   (N=正整数车道数,默认1)"; exit 1 ;;
esac
cd "$WORKDIR" || { echo "cd $WORKDIR 失败"; exit 1; }

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "已在运行(pid=$(cat "$PIDFILE"))。先 bash auto-loops.sh stop 再启动。"; exit 1
fi
rm -f "$STOPFILE"
echo $$ > "$PIDFILE"

cleanup() {
  rm -f "$PIDFILE"
  for s in $(tmux ls -F '#{session_name}' 2>/dev/null | grep '^rloop'); do
    tmux kill-session -t "$s" 2>/dev/null
  done
}
trap cleanup EXIT

# 单车道循环:每轮一个全新 session,跑完销毁,开下一个
run_lane() {
  local lane="$1" sess="rloop$1" round=0 hit st before latest
  # while 条件含 STOP 检查:收到 stop 后跑完当前轮回此处即退出,不开下一轮
  while [ ! -f "$STOPFILE" ] && { [ "$ROUNDS" -eq 0 ] || [ "$round" -lt "$ROUNDS" ]; }; do
    round=$((round+1))
    echo "[$(date +%H:%M:%S)] 车道$lane === 第 $round 轮:开新 session ==="
    tmux kill-session -t "$sess" 2>/dev/null
    tmux new-session -d -s "$sess" -c "$WORKDIR" "claude --permission-mode bypassPermissions"
    sleep 5
    before=$(latest_run)                       # 启动前最新 run(基准)
    tmux send-keys -t "$sess" "/research-loop" Enter
    # 轮询:等"比 before 新的 run"出现 且 status 变 done/paused
    # 注意:此循环【不检查 STOP】——保证当前轮必跑完,这是 graceful 关闭的核心
    hit=0; st=""
    for ((t=0; t<MAXWAIT; t++)); do
      sleep 30
      latest=$(latest_run)
      if [ "$latest" != "$before" ] && [ -n "$latest" ]; then
        st=$(get_status "$latest")
        case "$st" in
          done|paused) hit=1; echo "[$(date +%H:%M:%S)] 车道$lane 检测到 run=$latest status=$st"; break ;;
        esac
      fi
    done
    tmux kill-session -t "$sess" 2>/dev/null
    echo "[$(date +%H:%M:%S)] 车道$lane 第 $round 轮结束($([ $hit = 1 ] && echo "完成 status=$st" || echo "超时兜底"))→ session 销毁"
    [ -f "$STOPFILE" ] && { echo "[$(date +%H:%M:%S)] 车道$lane 检测到 STOP 标志,跑完本轮后退出"; break; }
    sleep 6
  done
  echo "[$(date +%H:%M:%S)] 车道$lane 退出(共 $round 轮)"
}

for ((i=1; i<=N; i++)); do
  run_lane "$i" &
  sleep 20   # 车道间错开
done
echo "[$(date +%H:%M:%S)] 已起 $N 条车道,state.json 检测循环中。"
echo "  停止(跑完当前轮): bash auto-loops.sh stop"
echo "  状态:             bash auto-loops.sh status"
echo "  日志:             tail -f $LOGROOT/auto.out"
wait
echo "[$(date +%H:%M:%S)] 所有车道退出,脚本结束"
