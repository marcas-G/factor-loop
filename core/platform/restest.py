#!/usr/bin/env python3
r"""restest 数据链路 —— 平台 Ridge-SVD 冗余分析(冗余约束主判据)。

平台 default_test 的 Submit restest: 把新因子对固定大库(qyshen/0727pass_v3, AG/AU 72 因子)
做 Ridge-SVD 正交化, 输出:
  - R2_X:        库因子线性组合能解释新因子多少方差(X 空间冗余度)
  - res_IC:      去掉库冗余后的 pooled Pearson 增量预测力
  - dLOOCV_pct:  Ridge 近似 Lasso 的 LOOCV 下降%(对线性模型的净增益, 主判据)

判据(平台文档 + 实测):
  dLOOCV_pct > 1%  → 对线性模型显著增益(不冗余)
  dLOOCV_pct ≈ 0   → 没贡献(冗余)
  dLOOCV_pct < 0   → 过拟合(更差)

用法(供 run-factor-agent / assess 调用):
    from core.platform.restest import run_restest
    result = run_restest("factors/ImbalanceBase.h", "ImbalanceBase")  # 提交+轮询+下载+解析
    # result = {"ok": True, "feature": "...", "metrics": {"R2_X":..., "res_IC":..., "dLOOCV_pct":...}}

restest 提交 → 平台跑 Ridge-SVD DAG(约 6.5 分钟)→ 下载 ridge_svd CSV → 解析。
失败(提交失败/超时/下载失败)不抛, 返回 ok=False + reason, 调用方降级。
"""
from __future__ import annotations

import csv
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
RESTEST_TIMEOUT_SEC = 600   # Ridge-SVD DAG 约 6.5 分钟, 给 10 分钟兜底
POLL_INTERVAL_SEC = 30


def _post_submit(cookie: str, url: str, factor_file: str, features: str,
                 extra_fields: dict | None = None) -> str:
    """curl multipart POST 提交, 返回响应 HTML。"""
    cmd = [
        "curl", "-s", "-L", "-k", "--max-time", "60",
        "-b", f"{COOKIE_NAME}={cookie}",
        "-F", f"uploaded_file=@{factor_file}",
        "-F", f"features={features}",
    ]
    for k, v in (extra_fields or {}).items():
        cmd += ["-F", f"{k}={v}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout or ""


def submit_restest(factor_file: str, features: str) -> dict:
    """提交因子到 restest(Ridge-SVD 冗余分析)。返回 {ok, feature?, error?}。

    features 传类名即可(template 类内部自动加 <>), 与 submit.py 语义一致。
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

    _post_submit(cookie, f"{bu}/submit_restest", factor_file, features,
                 {"_formkey": formkey, "_formname": "default"})

    # 提交后从主页找 <factor>_restest_ 开头的任务(web2py 建 DAG run 需几秒, 重试几次)
    # feature 名形如 ImbalanceBase_restest_SHFE_AG_SHFE_AG.1_SHFE_AU_SHFE_AU.1
    # 注意: 主页 feature 名不含 <> (平台用 .h stem), 匹配用裸类名
    stem = class_name
    for _ in range(10):
        html = fetch(f"{bu}/index", cookie)
        m = re.search(rf"{re.escape(stem)}_restest_[A-Za-z0-9._,]+", html)
        if m:
            return {"ok": True, "feature": m.group(0)}
        time.sleep(2)
    return {"ok": False, "error": f"提交后 20 秒内未在主页找到 {features}_restest 任务"}


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
    """下载 ridge_svd 结果包, 解析 CSV → {metrics: [{x_col, horizon, R2_X, res_IC, n, dLOOCV_pct}]}。"""
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
        metrics.append({
            "x_col": r.get("x_col", ""),
            "horizon": int(float(r["horizon"])) if r.get("horizon") else None,
            "R2_X": float(r["R2_X"]) if r.get("R2_X") else None,
            "res_IC": float(r["res_IC"]) if r.get("res_IC") else None,
            "n": int(float(r["n"])) if r.get("n") else None,
            "dLOOCV_pct": float(r["dLOOCV_pct"]) if r.get("dLOOCV_pct") else None,
        })
    return {"ok": True, "metrics": metrics}


def run_restest(factor_file: str, features: str) -> dict:
    """提交 + 轮询 + 下载 + 解析, 一步到位。返回 {ok, feature?, metrics?, error?}。"""
    sub = submit_restest(factor_file, features)
    if not sub.get("ok"):
        return sub
    feature = sub["feature"]

    poll = poll_restest(feature)
    if poll["state"] != "success":
        return {"ok": False, "feature": feature, "error": f"restest 任务状态={poll['state']}"}

    dl = download_ridge_svd(feature, poll["run_id"])
    if not dl.get("ok"):
        return {"ok": False, "feature": feature, "error": dl.get("error")}
    return {"ok": True, "feature": feature, "metrics": dl["metrics"]}


def aggregate_ridge_svd(metrics: list[dict]) -> dict:
    """把 metrics 数组(每 x_col×horizon 一条)聚合成单一冗余判定。

    取主力(非 @1 次主力)场景中 dLOOCV_pct 最大的(最乐观增量), 作主判据:
      - max_dLOOCV_pct: 所有主力场景的最大 LOOCV 下降%(最乐观)
      - R2_X: 对应场景的库解释方差
      - res_IC: 对应场景的增量 IC
    返回 {max_dLOOCV_pct, R2_X, res_IC, horizon, x_col}。
    """
    if not metrics:
        return {"max_dLOOCV_pct": None, "R2_X": None, "res_IC": None, "horizon": None, "x_col": None}
    main = [m for m in metrics if "@1" not in (m.get("x_col") or "")]
    if not main:
        main = metrics
    best = max(main, key=lambda m: m.get("dLOOCV_pct") if m.get("dLOOCV_pct") is not None else -1)
    return {
        "max_dLOOCV_pct": best.get("dLOOCV_pct"),
        "R2_X": best.get("R2_X"),
        "res_IC": best.get("res_IC"),
        "horizon": best.get("horizon"),
        "x_col": best.get("x_col"),
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
