#!/usr/bin/env python3
r"""restest 数据链路 —— 平台 Ridge-SVD 冗余分析(冗余约束主判据)。

2026-08-20 平台更新后, ridge_svd 的唯一入口是 GPU 版 Submit restest(原 Submit GPU):
  - 表单含 alpha / lib_key / n_workers(默认 12) / transform_sweep, 不再有 mode/Feeds/日期;
  - 日期固定半年(20250101~20250630);
  - CPU 版 submit_restest / restest_1 已从导航隐藏(历史 URL 仍可访问), 本文件保留其
    提交逻辑仅作兼容/backfill, 新链路一律走 core/platform/gpu.py 的 GPU 提交。
把新因子对固定大库(qyshen/0727pass_v3, AG/AU 72 因子)做 Ridge-SVD 正交化, 输出:
  - R2_X:        库因子线性组合能解释新因子多少方差(X 空间冗余度)
  - res_IC:      去掉库冗余后的 pooled Pearson 增量预测力
平台只输出 R2_X + res_IC, 冗余判定只用这两个指标。

用法(供 run-factor-agent / assess 调用):
    from core.platform.restest import run_restest
    result = run_restest("factors/ImbalanceBase.h", "ImbalanceBase")  # 提交+轮询+下载+解析
    # result = {"ok": True, "feature": "...", "metrics": {"R2_X":..., "res_IC":..., "n":...}}

restest 提交 → 平台跑 Ridge-SVD DAG(活跃因子实测可达 ~17 分钟)→ 下载 ridge_svd CSV → 解析。
失败(提交失败/超时/下载失败)不抛, 返回 ok=False + reason, 调用方降级。
"""
from __future__ import annotations

import csv
import fcntl
import functools
import io
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.platform.featuretool_common import (
    base_url, ensure_cookie, fetch, COOKIE_NAME, HOST,
)
from core.stages.write_factor import extract_class_name_from_h, is_template_class

APP = "default_test"
RESTEST_TIMEOUT_SEC = 1200  # Ridge-SVD DAG 实测活跃因子可达 ~17 分钟(600s 会超时但任务仍在后台跑完), 给 20 分钟兜底
TASK_APPEAR_TIMEOUT_SEC = 300  # 提交后任务出现在主页的等待窗口。实测 303 后任务秒级建出(同秒就 running); 300s 足够, 主要兜底平台偶发排队。早期版本误判"超窗失败"的真正原因是匹配用裸类名漏了参数后缀(见 submit_restest 注释), 非窗口过小。
POLL_INTERVAL_SEC = 30
SUBMIT_LOCK_FILE = "/tmp/factor-autoloop-restest-submit.lock"


def _serialize_submit(func):
    """Serialize formkey acquisition and POST across MCP worker processes."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with open(SUBMIT_LOCK_FILE, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                return func(*args, **kwargs)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return wrapper


def _post_submit(cookie: str, url: str, factor_file: str, features: str,
                 extra_fields: dict | None = None) -> dict:
    """curl multipart POST 提交。返回 {ok, html}。

    303 重定向(跟随 -L 后落到 index)不代表提交成功——web2py 表单校验失败
    (formkey 过期/session 失效/字段错误)同样 303 回 index, 只是任务不建。
    所以返回 html 供上层在任务未出现时留诊断证据, 不再吞响应。
    """
    cmd = [
        "curl", "-s", "-L", "-k", "--connect-timeout", "10", "--max-time", "60",
        "-b", f"{COOKIE_NAME}={cookie}",
        "-F", f"uploaded_file=@{factor_file}",
        "-F", f"features={features}",
        "-w", "\n__CURL_META__%{http_code} %{url_effective}",
    ]
    for k, v in (extra_fields or {}).items():
        cmd += ["-F", f"{k}={v}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    html = r.stdout or ""
    http_code: str | None = None
    effective_url: str | None = None
    marker = "\n__CURL_META__"
    if marker in html:
        html, raw_meta = html.rsplit(marker, 1)
        parts = raw_meta.strip().split(" ", 1)
        http_code = parts[0] or None
        effective_url = parts[1] if len(parts) > 1 else None
    return {
        "ok": r.returncode == 0,
        "html": html,
        "returncode": r.returncode,
        "stderr": (r.stderr or "").strip()[-500:],
        "http_code": http_code,
        "effective_url": effective_url,
    }


@_serialize_submit
def submit_restest(factor_file: str, features: str) -> dict:
    """提交因子到 CPU submit_restest(Ridge-SVD 冗余分析, 已停用/兼容路径)。

    features 传类名即可(template 类内部自动加 <>), 与 submit.py 语义一致。
    平台 2026-08-20 起该入口从导航隐藏(历史 URL 仍可访问); 新链路请走
    core/platform/gpu.py submit_gpu_tasks(mode=ridge_svd)。
    """
    # template 类自动加 <> (与 submit.py 一致, 否则平台编译失败 → DAG failed)
    class_name = extract_class_name_from_h(factor_file) or features
    features = f"{class_name}<>" if is_template_class(factor_file) else class_name

    bu = base_url(APP)
    cookie = ensure_cookie(app=APP)
    if not cookie:
        return {"ok": False, "error": "无有效 cookie"}

    # 取 submit_restest 页面的 formkey
    html = fetch(f"{bu}/submit_restest?username=", cookie)
    fk = re.search(r'name="_formkey"[^>]*value="([^"]+)"', html)
    if not fk:
        return {"ok": False, "error": "submit_restest 页面无 formkey"}
    formkey = fk.group(1)

    post = _post_submit(cookie, f"{bu}/submit_restest", factor_file, features,
                        {"_formkey": formkey, "_formname": "default"})
    if not post.get("ok") or post.get("http_code") not in {"200", "201", "202", "204"}:
        return {
            "ok": False,
            "error": (
                f"restest POST 未成功: rc={post.get('returncode')} "
                f"http={post.get('http_code')} url={post.get('effective_url')} "
                f"stderr={post.get('stderr') or '-'} body={len(post.get('html') or '')}B"
            ),
        }
    # web2py 表单校验失败会带 flash 错误回 index(任务不建); 留证据 + 触发重新登录
    flash_err = re.search(r'class="flash"[^>]*>(.*?)</div>', post.get("html", ""), re.S)

    # 提交后从主页找 <stem>_restest_ 开头的任务。
    # ⚠️ 主页 feature 名用 .h 文件 stem(带参数后缀), 形如:
    #   DepthAsymBucketGate_W500G4_restest_SHFE_AG_SHFE_AG.1_SHFE_AU_SHFE_AU.1
    # 不是裸类名! 裸类名 "DepthAsymBucketGate_restest" 在主页不存在(中间隔着 _W500G4)→
    # 永远匹配不到 → 误判"超窗失败"而任务其实秒级就建出。必须用带参数的 stem, 与 check
    # (feature_key = Path(factor_file).stem, startswith 匹配)保持一致。
    # 主页 feature 名不含 <> (平台用 .h stem 注册)。
    stem = Path(factor_file).stem
    deadline = time.time() + TASK_APPEAR_TIMEOUT_SEC
    last_html_len = 0
    while time.time() < deadline:
        html = fetch(f"{bu}/index", cookie)
        last_html_len = len(html)
        m = re.search(rf"{re.escape(stem)}_restest_[A-Za-z0-9._,]+", html)
        if m:
            return {"ok": True, "feature": m.group(0)}
        # session 中途失效: index 不再含 submit 链接 → 强制重登录一次再试(POST 响应
        # set-cookie 会轮换 session_id, 旧 cookie 在长 run 中途可能被服务端弃用)
        if "submit?username=" not in html:
            from core.platform.featuretool_common import save_cookie, do_login, CREDS_FILE
            import json as _json, os as _os
            if _os.path.exists(CREDS_FILE):
                creds = _json.load(open(CREDS_FILE))
                new_cookie = do_login(creds["username"], creds["password"], app=APP)
                if new_cookie:
                    save_cookie(new_cookie)
                    cookie = new_cookie
                else:
                    return {"ok": False, "error": "轮询中发现 session 失效且自动重登录失败"}
        time.sleep(POLL_INTERVAL_SEC)
    diag = f"POST resp {len(post.get('html',''))}B flash={bool(flash_err)}"
    if flash_err:
        diag += f" flash_err={re.sub(r'<[^>]+>', '', flash_err.group(1)).strip()[:120]}"
    return {"ok": False, "error": f"提交后 {TASK_APPEAR_TIMEOUT_SEC} 秒内未在主页找到 {stem}_restest 任务({diag}; index {last_html_len}B; formkey {formkey[:8]}…)"}


def _latest_task(feature: str) -> dict | None:
    """从主页 index 找指定 feature 的【最新】任务(同名任务重复提交会并存/覆盖)。

    返回 {run_id, state} 或 None(未找到)。run_id 末尾含 ISO 时间戳, 取时间戳最大的 = 最新。
    """
    bu = base_url(APP)
    cookie = ensure_cookie(app=APP)
    if not cookie:
        return None
    html = fetch(f"{bu}/index", cookie)
    tasks = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        if feature not in row:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"<[^>]+>", "", t).strip() for t in tds]
        # cells = [feature, mode, job(run_id), state, download, time]
        if len(cells) >= 4:
            run_id = cells[2]
            state = cells[3]
            tasks.append({"run_id": run_id, "state": state})
    if not tasks:
        return None
    # run_id 时间戳越大越新(格式 ...-2026-08-13T16-45-00-08-00)
    return max(tasks, key=lambda t: t["run_id"])


def poll_restest(feature: str, timeout_sec: int = RESTEST_TIMEOUT_SEC) -> dict:
    """轮询 restest 任务直到 success/failed/超时。返回 {state, run_id?, error?}。"""
    elapsed = 0
    while elapsed < timeout_sec:
        task = _latest_task(feature)
        if task:
            if task["state"] == "success":
                return {"state": "success", "run_id": task["run_id"]}
            if task["state"] == "failed":
                return {"state": "failed", "run_id": task["run_id"]}
        # running / 未找到 → 继续等
        time.sleep(POLL_INTERVAL_SEC)
        elapsed += POLL_INTERVAL_SEC
    return {"state": "timeout"}


def download_ridge_svd(feature: str, run_id: str) -> dict:
    """下载 ridge_svd 结果包, 解析 CSV → {metrics: [{x_col, horizon, R2_X, res_IC, n}]}。"""
    bu = base_url(APP)
    cookie = ensure_cookie(app=APP)
    if not cookie:
        return {"ok": False, "error": "无有效 cookie"}
    url = f"{bu}/download_ridge_svd?feature={feature}&run_id={run_id}&username="
    r = subprocess.run(
        ["curl", "-s", "-L", "-k", "--max-time", "120",
         "-b", f"{COOKIE_NAME}={cookie}", "-o", "/tmp/ridge_svd.tar.gz", url],
        capture_output=True, text=True, timeout=180,
    )
    tar_path = Path("/tmp/ridge_svd.tar.gz")
    if not tar_path.exists() or tar_path.stat().st_size < 100:
        return {"ok": False, "error": "下载失败或结果包过小"}

    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            csv_name = next(n for n in tar.getnames() if n.endswith(".csv"))
            content = tar.extractfile(csv_name).read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"解压/解析失败: {e}"}

    rows = list(csv.DictReader(io.StringIO(content)))
    metrics = []
    for r in rows:
        def number(value, caster=float):
            if value is None or value == "":
                return None
            try:
                return caster(float(value))
            except (TypeError, ValueError):
                return None

        metrics.append({
            "x_col": r.get("x_col", ""),
            "horizon": number(r.get("horizon"), int),
            "R2_X": number(r.get("R2_X")),
            "res_IC": number(r.get("res_IC")),
            "n": number(r.get("n"), int),
        })
    return {"ok": True, "metrics": metrics}


def run_restest(factor_file: str, features: str) -> dict:
    """提交 + 轮询 + 下载 + 解析, 一步到位。返回 {ok, feature?, metrics?, error?}。

    提交重试: 平台 POST 成功(303)但任务偶发不出现在主页(管道抖动/排队丢失/session 失效),
    重提至多 3 次(每次间隔 60s)。实测大部分提交秒级建出, 重提常恢复。与 check 的有界重试同源。
    """
    sub = None
    errors = []
    for attempt in (1, 2, 3):
        sub = submit_restest(factor_file, features)
        if sub.get("ok"):
            break
        errors.append(f"attempt{attempt}: {sub.get('error')}")
        if attempt < 3:
            time.sleep(60)
    if not sub.get("ok"):
        return {"ok": False, "error": " | ".join(errors)}
    feature = sub["feature"]

    poll = poll_restest(feature)
    if poll["state"] != "success":
        return {"ok": False, "feature": feature, "error": f"restest 任务状态={poll['state']}"}

    dl = download_ridge_svd(feature, poll["run_id"])
    if not dl.get("ok"):
        return {"ok": False, "feature": feature, "error": dl.get("error")}
    return {"ok": True, "feature": feature, "metrics": dl["metrics"]}


def run_submitted_restest(feature: str, timeout_sec: int = RESTEST_TIMEOUT_SEC) -> dict:
    """Wait for an already-submitted ridge_svd task and parse its artifact."""
    poll = poll_restest(feature, timeout_sec=timeout_sec)
    if poll["state"] != "success":
        return {"ok": False, "feature": feature, "error": f"restest 任务状态={poll['state']}"}
    dl = download_ridge_svd(feature, poll["run_id"])
    if not dl.get("ok"):
        return {"ok": False, "feature": feature, "error": dl.get("error")}
    return {"ok": True, "feature": feature, "metrics": dl["metrics"]}


def aggregate_ridge_svd(metrics: list[dict], engine: str = "gpu") -> dict:
    """把 metrics 数组(每 x_col×horizon 一条)聚合成单一冗余判定。

    平台只输出 R2_X/res_IC, 一律按主力(非 @1)场景中 |res_IC| 最大那条聚合:
      - R2_X: 对应场景的库解释方差
      - res_IC: 对应场景的增量 IC
    返回 {R2_X, res_IC, horizon, x_col}。
    """
    if not metrics:
        return {"R2_X": None, "res_IC": None,
                "horizon": None, "x_col": None, "engine": engine}
    main = [m for m in metrics if "@1" not in (m.get("x_col") or "")]
    if not main:
        main = metrics
    best = max(main, key=lambda m: abs(m.get("res_IC") or 0))
    return {
        "R2_X": best.get("R2_X"),
        "res_IC": best.get("res_IC"),
        "horizon": best.get("horizon"),
        "x_col": best.get("x_col"),
        "engine": engine,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="restest Ridge-SVD 冗余分析")
    ap.add_argument("--file", required=True, help="因子 .h 文件")
    ap.add_argument("--features", required=True, help="因子类名")
    args = ap.parse_args()
    r = run_restest(args.file, args.features)
    import json
    print(json.dumps(r, ensure_ascii=False, indent=1))
