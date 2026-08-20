#!/usr/bin/env python3
"""Platform submission helpers for paired CPU csv_ic and GPU ridge_svd jobs."""
from __future__ import annotations

import concurrent.futures
import html
import re
import subprocess
import time
from pathlib import Path

from core.platform.featuretool_common import (
    COOKIE_NAME,
    base_url,
    ensure_cookie,
    fetch,
)

APP = "default_test"
TASK_APPEAR_TIMEOUT_SEC = 300
POLL_INTERVAL_SEC = 5
GPU_SUBMIT_LOCK_FILE = "/tmp/factor-autoloop-gpu-submit.lock"


def _serialize_submit(func):
    """Keep GPU formkey acquisition and paired POSTs atomic across workers."""
    import fcntl
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with open(GPU_SUBMIT_LOCK_FILE, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                return func(*args, **kwargs)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return wrapper


def _plain_cell(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


def _parse_tasks(page_html: str) -> list[dict]:
    """Parse index rows while accepting newer Mode labels such as '[GPU] csv_ic'."""
    tasks = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 6:
            continue
        feature = _plain_cell(cells[0])
        if not feature:
            continue
        job_match = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', cells[2], re.S)
        tasks.append({
            "feature": feature,
            "mode": _plain_cell(cells[1]),
            "job_url": html.unescape(job_match.group(1)) if job_match else "",
            "job_id": _plain_cell(job_match.group(2)) if job_match else "",
            "state": _plain_cell(cells[3]),
            "download_url": "",
        })
    return tasks


def _gpu_formkey(cookie: str) -> str:
    html = fetch(f"{base_url(APP)}/submit_gpu?username=", cookie)
    match = re.search(r'name="_formkey"[^>]*value="([^"]+)"', html)
    if not match:
        raise RuntimeError("submit_gpu 页面无 formkey")
    return match.group(1)


def _post_gpu(
    cookie: str,
    factor_file: str,
    features: str,
    mode: str,
    formkey: str,
    feeds: str,
    start_date: str,
    end_date: str,
) -> dict:
    fields = {
        "features": features,
        "mode": mode,
        "Feeds": feeds,
        "start_date": start_date,
        "end_date": end_date,
        "alpha": "0.1",
        "lib_key": "AG_AU",
        "date_key": "YEAR",
        "_next": f"/featuretool/{APP}/index",
        "_formkey": formkey,
        "_formname": "default",
    }
    cmd = [
        "curl", "-s", "-L", "-k", "--connect-timeout", "10", "--max-time", "60",
        "-b", f"{COOKIE_NAME}={cookie}",
        "-F", f"uploaded_file=@{factor_file}",
    ]
    for key, value in fields.items():
        cmd += ["-F", f"{key}={value}"]
    cmd += [
        "-w", "\n__CURL_META__%{http_code} %{url_effective}",
        f"{base_url(APP)}/submit_gpu",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    html = result.stdout or ""
    http_code = None
    effective_url = None
    marker = "\n__CURL_META__"
    if marker in html:
        html, metadata = html.rsplit(marker, 1)
        parts = metadata.strip().split(" ", 1)
        http_code = parts[0] or None
        effective_url = parts[1] if len(parts) > 1 else None
    return {
        "ok": result.returncode == 0 and http_code in {"200", "201", "202", "204"},
        "mode": mode,
        "http_code": http_code,
        "effective_url": effective_url,
        "returncode": result.returncode,
        "stderr": (result.stderr or "").strip()[-500:],
        "html": html,
    }


def _tasks(cookie: str) -> list[dict]:
    html = fetch(f"{base_url(APP)}/index", cookie)
    return _parse_tasks(html)


def _gpu_tasks(cookie: str, stem: str, mode: str) -> list[dict]:
    prefix = f"{stem}_gpu_{mode}_"
    return [task for task in _tasks(cookie) if task.get("feature", "").startswith(prefix)]


def _wait_new_gpu_tasks(cookie: str, stem: str, mode: str, before: set[str], timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    latest = None
    while time.time() < deadline:
        tasks = _gpu_tasks(cookie, stem, mode)
        new_tasks = [task for task in tasks if task.get("job_id") not in before]
        if new_tasks:
            latest = max(new_tasks, key=lambda task: task.get("job_id") or "")
            return {
                "feature": latest["feature"],
                "run_id": latest.get("job_id") or latest.get("run_id"),
                "state": latest.get("state"),
                "job_url": latest.get("job_url"),
            }
        time.sleep(POLL_INTERVAL_SEC)
    return {
        "ok": False,
        "mode": mode,
        "error": f"提交后 {timeout_sec}s 未找到 {prefix} GPU 任务",
    }


def _cpu_formkey(cookie: str) -> str:
    page = fetch(f"{base_url(APP)}/submit?username=", cookie)
    match = re.search(r'name="_formkey"[^>]*value="([^"]+)"', page)
    if not match:
        raise RuntimeError("submit 页面无 formkey")
    return match.group(1)


def _post_cpu(cookie: str, factor_file: str, features: str, formkey: str,
              feeds: str, start_date: str, end_date: str) -> dict:
    fields = {
        "features": features,
        "ComputeCsvIc": "on",
        "Feeds": feeds,
        "start_date": start_date,
        "end_date": end_date,
        "_next": f"/featuretool/{APP}/index",
        "_formkey": formkey,
        "_formname": "default",
    }
    cmd = [
        "curl", "-s", "-L", "-k", "--connect-timeout", "10", "--max-time", "60",
        "-b", f"{COOKIE_NAME}={cookie}",
        "-F", f"uploaded_file=@{factor_file}",
    ]
    for key, value in fields.items():
        cmd += ["-F", f"{key}={value}"]
    cmd += [
        "-w", "\n__CURL_META__%{http_code} %{url_effective}",
        f"{base_url(APP)}/submit",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    body = result.stdout or ""
    http_code = None
    effective_url = None
    marker = "\n__CURL_META__"
    if marker in body:
        body, metadata = body.rsplit(marker, 1)
        parts = metadata.strip().split(" ", 1)
        http_code = parts[0] or None
        effective_url = parts[1] if len(parts) > 1 else None
    return {
        "ok": result.returncode == 0 and http_code in {"200", "201", "202", "204"},
        "mode": "csv_ic",
        "http_code": http_code,
        "effective_url": effective_url,
        "returncode": result.returncode,
        "stderr": (result.stderr or "").strip()[-500:],
        "html": body,
    }


def _wait_new_cpu_tasks(cookie: str, stem: str, before: set[str], timeout_sec: int) -> dict:
    prefix = f"{stem}_test_"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        tasks = [
            task for task in _tasks(cookie)
            if task.get("feature", "").startswith(prefix) and task.get("job_id") not in before
        ]
        if tasks:
            latest = max(tasks, key=lambda task: task.get("job_id") or "")
            return {
                "feature": latest["feature"],
                "run_id": latest.get("job_id"),
                "state": latest.get("state"),
                "job_url": latest.get("job_url"),
            }
        time.sleep(POLL_INTERVAL_SEC)
    return {"ok": False, "error": f"提交后 {timeout_sec}s 未找到 {prefix} CPU csv_ic 任务"}


@_serialize_submit
def submit_gpu_tasks(
    factor_file: str,
    features: str,
    modes: list[str],
    feeds: str,
    start_date: str = "2024-01-02",
    end_date: str = "2024-06-30",
) -> dict:
    """Submit selected GPU modes first, then wait for both platform rows.

    The two POSTs are issued concurrently after their formkeys are fetched. Waiting
    for task creation happens only after both requests have been sent.
    """
    if not modes:
        return {"ok": False, "error": "GPU modes 为空"}
    invalid = set(modes) - {"csv_ic", "ridge_svd"}
    if invalid:
        return {"ok": False, "error": f"非法 GPU mode: {', '.join(sorted(invalid))}"}

    cookie = ensure_cookie(app=APP)
    if not cookie:
        return {"ok": False, "error": "无有效 cookie"}
    factor_file = str(Path(factor_file))
    if not Path(factor_file).exists():
        return {"ok": False, "error": f"文件不存在: {factor_file}"}

    stem = Path(factor_file).stem
    try:
        before = {
            mode: {task.get("job_id") for task in _gpu_tasks(cookie, stem, mode)}
            for mode in modes
        }
    except Exception as exc:
        return {"ok": False, "error": f"读取 GPU 任务基线失败: {exc}"}

    try:
        formkeys = {mode: _gpu_formkey(cookie) for mode in modes}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(modes)) as pool:
        futures = {
            mode: pool.submit(
                _post_gpu, cookie, factor_file, features, mode, formkeys[mode],
                feeds, start_date, end_date,
            )
            for mode in modes
        }
        posts = {mode: future.result() for mode, future in futures.items()}

    failed_posts = {mode: post for mode, post in posts.items() if not post.get("ok")}
    if failed_posts:
        details = []
        for mode, post in failed_posts.items():
            details.append(
                f"{mode}: rc={post.get('returncode')} http={post.get('http_code')} "
                f"url={post.get('effective_url')} stderr={post.get('stderr') or '-'}"
            )
        return {"ok": False, "error": "GPU POST 未成功 | " + " | ".join(details), "posts": posts}

    found = {}
    for mode in modes:
        task = _wait_new_gpu_tasks(cookie, stem, mode, before[mode], TASK_APPEAR_TIMEOUT_SEC)
        if not task.get("feature"):
            return {
                "ok": False,
                "error": task.get("error"),
                "posts": posts,
                "tasks": found,
            }
        task["mode"] = mode
        task["engine"] = "gpu"
        found[mode] = task

    return {
        "ok": True,
        "engine": "gpu",
        "features": features,
        "modes": modes,
        "tasks": found,
    }


@_serialize_submit
def submit_csv_and_gpu_ridge(factor_file: str, features: str, feeds: str,
                             start_date: str = "2024-01-02",
                             end_date: str = "2024-06-30") -> dict:
    """Keep csv_ic on its CPU entry and submit GPU ridge_svd beside it."""
    cookie = ensure_cookie(app=APP)
    if not cookie:
        return {"ok": False, "error": "无有效 cookie"}
    factor_file = str(Path(factor_file))
    if not Path(factor_file).exists():
        return {"ok": False, "error": f"文件不存在: {factor_file}"}

    stem = Path(factor_file).stem
    try:
        tasks = _tasks(cookie)
        before_cpu = {
            task.get("job_id") for task in tasks
            if task.get("feature", "").startswith(f"{stem}_test_")
        }
        before_gpu = {
            task.get("job_id") for task in tasks
            if task.get("feature", "").startswith(f"{stem}_gpu_restest_")
        }
        cpu_formkey = _cpu_formkey(cookie)
        gpu_formkey = _gpu_formkey(cookie)
    except Exception as exc:
        return {"ok": False, "error": f"提交前读取平台状态失败: {exc}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        cpu_future = pool.submit(
            _post_cpu, cookie, factor_file, features, cpu_formkey, feeds,
            start_date, end_date,
        )
        gpu_future = pool.submit(
            _post_gpu, cookie, factor_file, features, "ridge_svd", gpu_formkey,
            feeds, start_date, end_date,
        )
        posts = {"csv_ic": cpu_future.result(), "ridge_svd": gpu_future.result()}

    failed = {mode: post for mode, post in posts.items() if not post.get("ok")}
    if failed:
        details = [
            f"{mode}: rc={post.get('returncode')} http={post.get('http_code')} "
            f"url={post.get('effective_url')} stderr={post.get('stderr') or '-'}"
            for mode, post in failed.items()
        ]
        return {"ok": False, "error": "双入口 POST 未成功 | " + " | ".join(details), "posts": posts}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        csv_future = pool.submit(
            _wait_new_cpu_tasks, cookie, stem, before_cpu, TASK_APPEAR_TIMEOUT_SEC,
        )
        ridge_future = pool.submit(
            _wait_new_gpu_tasks, cookie, stem, "restest", before_gpu,
            TASK_APPEAR_TIMEOUT_SEC,
        )
        csv_task = csv_future.result()
        ridge_task = ridge_future.result()

    if not csv_task.get("feature"):
        return {"ok": False, "error": csv_task.get("error"), "posts": posts}
    csv_task.update({"mode": "csv_ic", "engine": "cpu"})

    if not ridge_task.get("feature"):
        return {
            "ok": False,
            "error": ridge_task.get("error"),
            "posts": posts,
            "tasks": {"csv_ic": csv_task},
        }
    ridge_task.update({"mode": "ridge_svd", "engine": "gpu"})

    return {
        "ok": True,
        "engines": {"csv_ic": "cpu", "ridge_svd": "gpu"},
        "features": features,
        "modes": ["csv_ic", "ridge_svd"],
        "tasks": {"csv_ic": csv_task, "ridge_svd": ridge_task},
    }
