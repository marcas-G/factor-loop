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
import sys
from pathlib import Path

# featuretool.py 裸 `from featuretool_common import` 时,core 包不在 path → 补项目根
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.config import CREDS_FILE  # noqa: E402  自动登录账号密码,单一真相

HOST = "https://tools.xyz.abc"
# 双平台分工:
#   default      → 下载 .xy 原始数据(dailyX, GenerateXs=on, download_file)
#   default_test → 跑 IC + 残差评估(csv_ic, ComputeCsvIc=on, download_ic)
# 按需使用: 调用 base_url(app) 取 URL; CLI 按子命令推断(submit→default_test, xy→default)。
# 环境变量 FEATURETOOL_APP 仍可全局覆盖(向后兼容)。
VALID_APPS = ("default", "default_test")
DEFAULT_APP = os.environ.get("FEATURETOOL_APP", "default_test")

# 向后兼容: 暴露 BASE_URL 常量(= 默认 app)。新代码用 base_url(app)。
BASE_URL = f"{HOST}/featuretool/{DEFAULT_APP}"
COOKIE_FILE = os.path.expanduser("~/.featuretool_cookie")
COOKIE_NAME = "session_id_featuretool"


def base_url(app: str | None = None) -> str:
    """返回指定 app 的 BASE_URL。app=None 用环境变量/默认(default_test)。

    app 语义:
      'default'      → .xy 原始数据平台(download_file, GenerateXs)
      'default_test' → IC/残差评估平台(download_ic, ComputeCsvIc)
    """
    if app is None:
        app = DEFAULT_APP
    if app not in VALID_APPS:
        raise ValueError(f"app 必须是 {VALID_APPS} 之一, 得到 {app!r}")
    return f"{HOST}/featuretool/{app}"


def app_of_url(url: str) -> str:
    """从 URL 反推 app(default / default_test)。供 cmd_submit 判断平台用。"""
    if "/featuretool/default_test/" in url:
        return "default_test"
    return "default"


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


def do_login(username, password, app=None):
    """账号密码登录，返回有效 cookie 或 None。移植自 factor-pipeline/factor_pipeline.py。

    cookie 跨平台共享(session 同一个), app 只决定登录后校验访问哪个 index。"""
    import tempfile
    bu = base_url(app)
    login_url = f"{bu}/user/login"  # BASE_URL 含 /featuretool/<app> 应用前缀；HOST/user/login 会 404 invalid application
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
             f"--data-urlencode", f"_next=/featuretool/{app or DEFAULT_APP}/index",
             "--data-urlencode", f"_formkey={m.group(1)}",
             "--data-urlencode", "_formname=login", login_url],
            capture_output=True, text=True, timeout=60)
        if not os.path.exists(jar):
            return None
        cm = re.search(rf'{COOKIE_NAME}\s+(\S+)', open(jar).read())
        if not cm:
            return None
        cookie = cm.group(1)
        html = fetch(f"{bu}/index", cookie)
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


def ensure_cookie(cookie_arg=None, app=None):
    """确保返回有效 cookie：当前 cookie 失效则用 CREDS_FILE 自动登录刷新。

    替代 get_cookie 用于所有需要鉴权的入口（submit/check）。cookie 过期自动
    读 /home/lgao/featuretool_creds.json 登录，无需 agent/人工介入。
    cookie 跨平台共享, app 只决定校验时访问哪个 index。
    返回有效 cookie 或 None（creds 缺失/登录失败）。
    """
    import sys
    cookie = get_cookie(cookie_arg)
    bu = base_url(app)
    if cookie:
        try:
            html = fetch(f"{bu}/index", cookie)
            if re.search(r'submit\?username=([^"&]+)', html):
                return cookie
        except Exception:
            pass
    if not os.path.exists(CREDS_FILE):
        print(f"[ensure_cookie] cookie 失效且无 {CREDS_FILE}，无法自动登录", file=sys.stderr)
        return None
    try:
        creds = json.load(open(CREDS_FILE))
        new_cookie = do_login(creds["username"], creds["password"], app=app)
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


def parse_index(html, app=None):
    """解析 featuretool 主页 HTML，提取用户名和因子任务列表。

    app 决定 download_url 解析方式:
      default_test → /featuretool/default_test/download_ic (csv_ic)
      default      → /featuretool/default/download_file    (dailyX/.xy)
    app=None 时自动从 URL 前缀推断。

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
    # download_url 正则: 兼容两种平台(default_test/download_ic | default/download_file)
    dl_re_test = re.compile(r'href="(/featuretool/default_test/download_ic\?[^"]*)"')
    dl_re_default = re.compile(r'href="(/featuretool/default/download_file\?[^"]*)"')

    for m in row_pattern.finditer(html):
        feature = m.group(1).strip()
        job_url = m.group(3) or ""
        job_id = m.group(4).strip() if m.group(4) else ""
        state = m.group(5).strip()
        download_raw = m.group(6).strip()

        # 按 app 选正则; app=None 时两个都试, 谁匹配用谁
        download_url = ""
        if app == "default_test" or app is None:
            dlm = dl_re_test.search(download_raw)
            if dlm:
                download_url = dlm.group(1)
        if not download_url and (app == "default" or app is None):
            dlm = dl_re_default.search(download_raw)
            if dlm:
                download_url = dlm.group(1)

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
