#!/usr/bin/env python3
"""featuretool 共享工具 — factor-evaluate 和 featuretool 两个 skill 共用。

提供:
  - get_cookie(): 按 --cookie > 环境变量 > 文件 优先级获取 cookie
  - save_cookie(): 保存 cookie 到 ~/.featuretool_cookie
  - fetch(): 通过 curl 发起 HTTP GET 请求
  - parse_index(): 解析 featuretool 主页 HTML，提取因子列表
  - BASE_URL, COOKIE_FILE, COOKIE_NAME: 共享常量
"""

import json
import os
import re
import subprocess
from pathlib import Path

HOST = "https://tools.xyz.abc"
BASE_URL = f"{HOST}/featuretool/default_test"  # adapt/default-test: 新平台应用前缀(default_test),产物 csv_ic 非 dailyX
COOKIE_FILE = os.path.expanduser("~/.featuretool_cookie")
COOKIE_NAME = "session_id_featuretool"
CREDS_FILE = "/home/lgao/featuretool_creds.json"  # 自动登录用的账号密码 {username, password}


def get_cookie(cookie_arg=None):
    """按优先级获取 cookie: 参数 > 环境变量 > 文件。

    Args:
        cookie_arg: 可以是字符串或 argparse.Namespace（通过 args.cookie）。
    """
    # 支持直接传字符串或传 args namespace
    if cookie_arg is not None:
        if isinstance(cookie_arg, str):
            val = cookie_arg
        else:
            val = getattr(cookie_arg, "cookie", None)
        if val:
            return val

    env_cookie = os.environ.get("FEATURETOOL_COOKIE", "")
    if env_cookie:
        return env_cookie

    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r") as f:
            return f.read().strip()

    return None


def save_cookie(cookie):
    """保存 cookie 到文件"""
    Path(COOKIE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w") as f:
        f.write(cookie.strip())
    print(f"Cookie 已保存到 {COOKIE_FILE}")


def do_login(username, password):
    """账号密码登录，返回有效 cookie 或 None。移植自 factor-pipeline/factor_pipeline.py。"""
    import tempfile
    login_url = f"{BASE_URL}/user/login"  # BASE_URL 含 /featuretool/default 应用前缀；HOST/user/login 会 404 invalid application
    jar = tempfile.mktemp(suffix=".jar")
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-k", "--max-time", "30", "-c", jar, login_url],
            capture_output=True, text=True, timeout=60)
        m = re.search(r'name="_formkey"\s+type="hidden"\s+value="([^"]*)"', r.stdout)
        if not m:
            return None
        subprocess.run(
            ["curl", "-s", "-L", "-k", "--max-time", "30", "-b", jar, "-c", jar,
             "--data-urlencode", f"username={username}",
             "--data-urlencode", f"password={password}",
             "--data-urlencode", "_next=/featuretool/default_test/index",
             "--data-urlencode", f"_formkey={m.group(1)}",
             "--data-urlencode", "_formname=login", login_url],
            capture_output=True, text=True, timeout=60)
        if not os.path.exists(jar):
            return None
        cm = re.search(rf'{COOKIE_NAME}\s+(\S+)', open(jar).read())
        if not cm:
            return None
        cookie = cm.group(1)
        html = fetch(f"{BASE_URL}/index", cookie)
        if not re.search(r'submit\?username=([^"&]+)', html):
            return None
        return cookie
    except Exception:
        return None
    finally:
        try:
            os.unlink(jar)
        except OSError:
            pass


def ensure_cookie(cookie_arg=None):
    """确保返回有效 cookie：当前 cookie 失效则用 CREDS_FILE 自动登录刷新。

    替代 get_cookie 用于所有需要鉴权的入口（submit/check）。cookie 过期自动
    读 /home/lgao/featuretool_creds.json 登录，无需 agent/人工介入。
    返回有效 cookie 或 None（creds 缺失/登录失败）。
    """
    import sys
    cookie = get_cookie(cookie_arg)
    if cookie:
        try:
            html = fetch(f"{BASE_URL}/index", cookie)
            if re.search(r'submit\?username=([^"&]+)', html):
                return cookie
        except Exception:
            pass
    if not os.path.exists(CREDS_FILE):
        print(f"[ensure_cookie] cookie 失效且无 {CREDS_FILE}，无法自动登录", file=sys.stderr)
        return None
    try:
        creds = json.load(open(CREDS_FILE))
        new_cookie = do_login(creds["username"], creds["password"])
        if new_cookie:
            save_cookie(new_cookie)
            print(f"[ensure_cookie] cookie 已自动刷新（登录用户 {creds['username']}）")
            return new_cookie
        print("[ensure_cookie] 自动登录失败（用户名/密码错或平台异常）", file=sys.stderr)
    except Exception as e:
        print(f"[ensure_cookie] 自动登录异常: {e}", file=sys.stderr)
    return None


def fetch(url, cookie):
    """HTTP GET via curl（绕过 SSL 证书问题）"""
    result = subprocess.run(
        ["curl", "-s", "-L", "-k", "--max-time", "30", "-b", f"{COOKIE_NAME}={cookie}", url],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout


def parse_index(html):
    """解析 featuretool 主页 HTML，提取用户名和因子任务列表。

    返回:
        (username, factors) 其中 factors 是 dict 列表，每个 dict 包含:
        feature, job_id, job_url, state, download_url, download_label, run_id, submit_time
    """
    username_match = re.search(r'submit\?username=([^"&]+)', html)
    username = username_match.group(1) if username_match else ""

    factors = []
    row_pattern = re.compile(
        r'<tr>\s*'
        r'<td>([^<]+)</td>\s*'                                       # Feature
        r'<td>([^<]*)</td>\s*'                                       # Mode (csv_ic/dailyX, adapt 后新增列)
        r'<td>(?:<a\s+href="([^"]*)"[^>]*>([^<]*)</a>)?</td>\s*'    # Job (link + id)
        r'<td>([^<]+)</td>\s*'                                       # State
        r'<td>(.*?)</td>\s*'                                         # DownloadXs
        r'<td>([^<]+)</td>'                                          # LastSubmitTime
    )
    for m in row_pattern.finditer(html):
        feature = m.group(1).strip()
        # group2=Mode(csv_ic,忽略); group3/4=Job link/id; group5=State; group6=Download; group7=LastSubmitTime
        job_url = m.group(3) or ""
        job_id = m.group(4).strip() if m.group(4) else ""
        state = m.group(5).strip()
        download_raw = m.group(6).strip()

        dl_match = re.search(r'href="(/featuretool/default_test/download_ic\?[^"]*)"', download_raw)
        download_url = dl_match.group(1) if dl_match else ""
        run_id_match = re.search(r'run_id=([^&"]+)', download_url)
        run_id = run_id_match.group(1) if run_id_match else ""

        dl_label = re.search(r'>([^<]*)</a>', download_raw)
        dl_label = dl_label.group(1) if dl_label else download_raw

        factors.append({
            "feature": feature,
            "job_id": job_id,
            "job_url": job_url,
            "state": state,
            "download_url": download_url,
            "download_label": dl_label,
            "run_id": run_id,
            "submit_time": m.group(7).strip(),
        })

    return username, factors
