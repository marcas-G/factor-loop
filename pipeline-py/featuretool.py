#!/usr/bin/env python
"""
featuretool CLI - 因子计算平台命令行工具

通过浏览器登录后获取 cookie，即可在命令行完成因子任务的查看、下载、提交等操作。

用法:
  python featuretool.py list                          查看所有因子任务状态
  python featuretool.py download --names hawkes_oc    下载指定因子
  python featuretool.py download --all                下载全部成功因子
  python featuretool.py submit --file factor.h --features "ClassA|ClassB"  提交因子
  python featuretool.py save-cookie <cookie_value>    保存 cookie 供后续使用

Cookie 优先级: --cookie > 环境变量 FEATURETOOL_COOKIE > ~/.featuretool_cookie 文件

示例:
  # 首次使用，保存 cookie
  python featuretool.py save-cookie 10.10.1.240-xxxx-xxxx

  # 之后直接使用
  python featuretool.py list
  python featuretool.py download --names hawkes_oc_super,hawkes_oc --output D:/0413
  python featuretool.py download --all --output D:/0413
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# 同目录模块（featuretool_common / factor_logger）即可 import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ==================== 通用工具 ====================
from featuretool_common import HOST, BASE_URL, COOKIE_FILE, COOKIE_NAME, get_cookie, ensure_cookie, fetch, parse_index, save_cookie

import json

# ==================== 自动重登 ====================
CREDENTIALS_FILE = os.path.expanduser("~/featuretool_creds.json")


def _read_credentials():
    """读取凭证文件，返回 (username, password) 或 (None, None)。"""
    if not os.path.exists(CREDENTIALS_FILE):
        return None, None
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            data = json.load(f)
        return data.get("username"), data.get("password")
    except Exception:
        return None, None


def _save_credentials(username, password):
    """保存凭证到 JSON 文件，权限 600。"""
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"username": username, "password": password}, f, indent=2)
    os.chmod(CREDENTIALS_FILE, 0o600)


def _do_login(username, password):
    """核心登录逻辑。返回 (cookie, logged_in_user) 或 (None, None)。"""
    cookie_jar = tempfile.mktemp(suffix=".jar")
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-k", "--max-time", "30", "-c", cookie_jar,
             f"{BASE_URL}/user/login"],
            capture_output=True, text=True, timeout=60
        )
        m = re.search(r'name="_formkey"\s+type="hidden"\s+value="([^"]*)"', r.stdout)
        if not m:
            return None, None

        subprocess.run([
            "curl", "-s", "-L", "-k", "--max-time", "30",
            "-b", cookie_jar, "-c", cookie_jar,
            "--data-urlencode", f"username={username}",
            "--data-urlencode", f"password={password}",
            "--data-urlencode", "_next=/featuretool/default_test/index",
            "--data-urlencode", f"_formkey={m.group(1)}",
            "--data-urlencode", "_formname=login",
            f"{BASE_URL}/user/login",
        ], capture_output=True, text=True, timeout=60)

        if not os.path.exists(cookie_jar):
            return None, None
        with open(cookie_jar) as f:
            content = f.read()
        cm = re.search(rf'{COOKIE_NAME}\s+(\S+)', content)
        if not cm:
            return None, None

        new_cookie = cm.group(1)
        html = fetch(f"{BASE_URL}/index", new_cookie)
        um = re.search(r'submit\?username=([^"&]+)', html)
        if not um:
            return None, None

        return new_cookie, um.group(1)
    except Exception:
        return None, None
    finally:
        try:
            os.unlink(cookie_jar)
        except OSError:
            pass


def auto_login():
    """用存储的凭证自动登录。返回新 cookie 或 None。"""
    username, password = _read_credentials()
    if not username or not password:
        return None
    cookie, _ = _do_login(username, password)
    if cookie:
        save_cookie(cookie)
        print("[自动重登成功]")
        return cookie
    return None

def cmd_list(args):
    """列出所有因子任务"""
    cookie = ensure_cookie(args)
    if not cookie:
        cookie = auto_login()
    if not cookie:
        print("错误: 未提供 cookie。请用 --cookie <value> 或先运行 login 命令。")
        sys.exit(1)

    html = fetch(f"{BASE_URL}/index", cookie)
    username, factors = parse_index(html)

    if not username:
        cookie = auto_login()
        if cookie:
            html = fetch(f"{BASE_URL}/index", cookie)
            username, factors = parse_index(html)
    if not username:
        print("错误: cookie 无效或已过期，请重新获取。")
        sys.exit(1)

    success = sum(1 for f in factors if f["state"] == "success")
    failed = sum(1 for f in factors if f["state"] == "failed")

    if getattr(args, "json", False):
        print(json.dumps({"username": username, "total": len(factors), "success": success, "failed": failed, "factors": factors}))
        return

    print(f"用户: {username}  |  共 {len(factors)} 个因子任务\n")
    print(f"{'#':<4} {'Feature':<25} {'State':<10} {'SubmitTime':<22} {'RunID'}")
    print("-" * 110)
    for i, f in enumerate(factors, 1):
        state_icon = "OK" if f["state"] == "success" else "FAIL" if f["state"] == "failed" else f["state"]
        run_short = f["run_id"].split("-")[-1] if f["run_id"] else ""
        print(f"{i:<4} {f['feature']:<25} {state_icon:<10} {f['submit_time']:<22} {run_short}")

    print(f"\n成功: {success}  |  失败: {failed}")


def cmd_download(args):
    """下载因子计算结果"""
    cookie = ensure_cookie(args)
    if not cookie:
        cookie = auto_login()
    if not cookie:
        print("错误: 未提供 cookie。请用 --cookie <value> 或先运行 login 命令。")
        sys.exit(1)

    html = fetch(f"{BASE_URL}/index", cookie)
    username, factors = parse_index(html)

    if not username:
        cookie = auto_login()
        if cookie:
            html = fetch(f"{BASE_URL}/index", cookie)
            username, factors = parse_index(html)
    if not username:
        print("错误: cookie 无效或已过期，请重新获取。")
        sys.exit(1)

    # 筛选要下载的因子
    if args.names:
        target_names = [n.strip() for n in args.names.split(",")]
        to_download = [f for f in factors if f["feature"] in target_names]
        not_found = set(target_names) - {f["feature"] for f in factors}
        if not_found:
            print(f"警告: 未找到因子: {', '.join(not_found)}")
    elif args.all:
        to_download = [f for f in factors if f["state"] == "success" and f["download_url"]]
    else:
        print("错误: 请指定 --names <因子名> 或 --all")
        sys.exit(1)

    if not to_download:
        print("没有可下载的因子。")
        sys.exit(0)

    output_dir = Path(args.output or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"准备下载 {len(to_download)} 个因子到: {output_dir}\n")

    for f in to_download:
        fname = f["feature"]
        dl_url = f"{HOST}{f['download_url']}"
        tar_path = output_dir / f"{fname}.tar.gz"
        extract_dir = output_dir / fname

        print(f"  [{f['state']}] {fname} ... ", end="", flush=True)

        if f["state"] not in ("success", "OK"):
            print("跳过（未成功）")
            continue

        if not f["download_url"]:
            print("跳过（无下载链接）")
            continue

        try:
            # 下载
            subprocess.run(
                ["curl", "-s", "-L", "-k", "--max-time", "600", "-o", str(tar_path),
                 "-b", f"{COOKIE_NAME}={cookie}", dl_url],
                check=True, timeout=900
            )
            size_mb = tar_path.stat().st_size / 1024 / 1024

            # 解压
            extract_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)

            # 清理 tar.gz
            tar_path.unlink()

            # 验证
            dailyx = extract_dir / "dailyX"
            if dailyx.exists():
                file_count = len(list(dailyx.iterdir()))
                print(f"OK ({size_mb:.0f}MB, {file_count} files)")
            else:
                print(f"OK ({size_mb:.0f}MB, 解压完成)")

        except Exception as e:
            print(f"失败: {e}")
            if tar_path.exists():
                tar_path.unlink()

    print("\n完成！")

    # 日志
    try:
        from factor_logger import append_submission_log
        downloaded_names = []
        for f in to_download:
            if f["state"] in ("success", "OK") and f["download_url"]:
                downloaded_names.append(f["feature"])
        if downloaded_names:
            append_submission_log("featuretool", "下载", {
                "因子": ", ".join(downloaded_names) if len(downloaded_names) <= 5 else f"{len(downloaded_names)} 个",
                "输出": str(output_dir),
            })
    except Exception:
        pass


def cmd_submit(args):
    """提交因子计算任务"""
    cookie = ensure_cookie(args)
    if not cookie:
        cookie = auto_login()
    if not cookie:
        print("错误: 未提供 cookie。请用 --cookie <value> 或先运行 login 命令。")
        sys.exit(1)

    if not args.file:
        print("错误: 请用 --file <path> 指定因子代码文件")
        sys.exit(1)
    if not args.features:
        print("错误: 请用 --features <class_names> 指定因子类名")
        sys.exit(1)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误: 文件不存在 {file_path}")
        sys.exit(1)

    # 1. 获取 submit 页面，提取 formkey
    print("获取提交页面...")
    html = fetch(f"{BASE_URL}/submit?username=", cookie)

    # cookie 过期时页面可能重定向到登录页，检查并自动重登
    if 'login' in html.lower() or '_formkey' not in html:
        new_cookie = auto_login()
        if new_cookie:
            cookie = new_cookie
            html = fetch(f"{BASE_URL}/submit?username=", cookie)
        else:
            print("错误: cookie 已过期且自动重登失败，请手动运行 login 命令。")
            sys.exit(1)

    formkey_match = re.search(r'name="_formkey"\s+type="hidden"\s+value="([^"]*)"', html)
    if not formkey_match:
        print("错误: 无法获取 CSRF token，cookie 可能已过期。")
        sys.exit(1)
    formkey = formkey_match.group(1)

    # 2. 构建 multipart POST（用 curl -F 实现）
    feeds = args.feeds or "SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1"
    start_date = args.start_date or "2024-01-02"
    end_date = args.end_date or "2024-06-30"
    generate_xs = args.generate_xs

    print(f"提交因子: {args.features}")
    print(f"文件: {file_path.name}")
    print(f"品种: {feeds}")
    print(f"日期: {start_date} ~ {end_date}")
    print(f"生成Xs: {'是' if generate_xs else '否'}")

    try:
        curl_cmd = [
            "curl", "-s", "-L", "-k", "--max-time", "60",
            "-b", f"{COOKIE_NAME}={cookie}",
            "-F", f"uploaded_file=@{file_path}",
            "-F", f"features={args.features}",
            "-F", f"Feeds={feeds}",
            "-F", f"start_date={start_date}",
            "-F", f"end_date={end_date}",
        ]
        # adapt/default-test: 新平台删 GenerateXs; ComputeCsvIc 默认 on(平台端算 csv_ic 替代 dailyX 本地算)
        curl_cmd += ["-F", "ComputeCsvIc=on"]
        curl_cmd += [
            "-F", "_next=/featuretool/default_test/index",
            "-F", f"_formkey={formkey}",
            "-F", "_formname=default",
            f"{BASE_URL}/submit",
        ]

        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=120)
        result_html = result.stdout

        # 成功标志: 响应中包含 index 页面的 submit?username= 链接（说明已重定向回主页）
        # 注意: 页面 JS 中的 ajax_error_500 包含 "error"，不能直接匹配
        submit_success = 'submit?username=' in result_html

        if submit_success:
            try:
                from factor_logger import append_submission_log
                append_submission_log("featuretool", "提交", {
                    "因子": args.features,
                    "文件": str(file_path),
                    "品种": feeds,
                    "日期": f"{start_date} ~ {end_date}",
                })
            except Exception:
                pass
            if getattr(args, "json", False):
                print(json.dumps({"ok": True, "features": args.features, "feeds": feeds, "file": str(file_path)}))
            else:
                print("\n提交成功！")
        else:
            err_match = re.search(r'<div class="error"[^>]*>(.*?)</div>', result_html, re.DOTALL)
            if err_match:
                err_msg = re.sub(r'<[^>]+>', '', err_match.group(1)).strip()
            elif 'Invalid' in result_html or 'invalid' in result_html:
                err_msg = "表单验证错误（请检查类名是否正确，template 类需带 <>）"
            else:
                err_msg = "已发送但未确认（无重定向也无报错），请到网页确认"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": err_msg, "stage": "submit", "features": args.features}))
                sys.exit(2)
            else:
                print(f"\n提交失败: {err_msg}")
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(e), "stage": "submit_exception", "features": getattr(args, "features", None)}))
            sys.exit(2)
        else:
            print(f"\n提交失败: {e}")


def cmd_login(args):
    """通过用户名密码登录，获取并保存 cookie"""
    if not args.username or not args.password:
        print("错误: 请提供 --username 和 --password")
        print("用法: python featuretool.py login --username <user> --password <pwd>")
        sys.exit(1)

    print(f"登录用户: {args.username} ...")
    cookie, logged_in_user = _do_login(args.username, args.password)
    if not cookie:
        print("登录失败: 请检查用户名和密码")
        sys.exit(1)

    with open(COOKIE_FILE, "w") as f:
        f.write(cookie)
    _save_credentials(args.username, args.password)

    print(f"登录成功! 用户: {logged_in_user}")
    print(f"Cookie 已保存到 {COOKIE_FILE}")
    print("凭证已保存，下次 cookie 过期将自动重登")


def cmd_save_cookie(args):
    """保存 cookie 到文件"""
    if not args.cookie_value:
        print("错误: 请提供 cookie 值")
        print("用法: python featuretool.py save-cookie <cookie_value>")
        sys.exit(1)

    with open(COOKIE_FILE, "w") as f:
        f.write(args.cookie_value.strip())
    print(f"Cookie 已保存到 {COOKIE_FILE}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="featuretool",
        description="featuretool CLI - 因子计算平台命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
登录方式:
  1. 用户名密码登录（推荐）: python featuretool.py login --username <user> --password <pwd>
  2. 手动获取 cookie: 浏览器 F12 -> Cookies -> session_id_featuretool，然后 save-cookie

示例:
  # 登录（推荐，自动保存 cookie）
  python featuretool.py login --username qyshen --password yourpwd

  # 手动保存 cookie
  python featuretool.py save-cookie 10.10.1.240-xxxx-xxxx

  # 查看因子列表
  python featuretool.py list

  # 下载指定因子
  python featuretool.py download --names hawkes_oc_super,hawkes_oc --output D:/0413

  # 下载全部成功因子
  python featuretool.py download --all --output D:/0413

  # 提交新因子（template 类必须带 <> 尖括号！）
  python featuretool.py submit --file factor.h --features "MyClass<>"
  python featuretool.py submit --file factor.h --features "MyClass<20>" --generate-xs
  python featuretool.py submit --file factor.h --features "ClassA<>|ClassB<>" --feeds "SHFE-AG" --start-date 2024-01-02 --end-date 2024-06-30
"""
    )

    # 全局选项
    p.add_argument("--cookie", help="session cookie 值（也可通过 FEATURETOOL_COOKIE 环境变量设置）")

    sub = p.add_subparsers(dest="command")

    # login
    lg = sub.add_parser("login", help="通过用户名密码登录（自动保存 cookie）")
    lg.add_argument("--username", "-u", required=True, help="用户名")
    lg.add_argument("--password", "-p", required=True, help="密码")

    # list
    lp = sub.add_parser("list", help="查看所有因子任务状态")
    lp.add_argument("--json", action="store_true", help="输出 JSON（便于程序化解析）")

    # download
    dl = sub.add_parser("download", help="下载因子计算结果")
    dl.add_argument("--names", help="指定因子名，逗号分隔（如 hawkes_oc,hawkes_oc_freq）")
    dl.add_argument("--all", action="store_true", help="下载全部成功的因子")
    dl.add_argument("--output", "-o", help="输出目录（默认当前目录）")

    # submit
    sb = sub.add_parser("submit", help="提交新因子计算任务")
    sb.add_argument("--file", "-f", required=True, help="因子代码文件路径（.h）")
    sb.add_argument("--features", required=True, help='因子类名，| 分隔（如 "ClassA|ClassB<10,14>"）')
    sb.add_argument("--feeds", help="交易品种，逗号分隔（默认 SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1）")
    sb.add_argument("--start-date", help="起始日期 YYYY-MM-DD（默认 2024-01-02）")
    sb.add_argument("--end-date", help="结束日期 YYYY-MM-DD（默认 2024-06-30）")
    sb.add_argument("--generate-xs", action="store_true", help="生成 Xs")
    sb.add_argument("--json", action="store_true", help="输出 JSON（便于程序化解析）")

    # save-cookie
    sc = sub.add_parser("save-cookie", help="保存 cookie 到本地文件")
    sc.add_argument("cookie_value", help="cookie 值")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "login":
        cmd_login(args)
    elif args.command == "save-cookie":
        cmd_save_cookie(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "download":
        cmd_download(args)
    elif args.command == "submit":
        cmd_submit(args)


if __name__ == "__main__":
    main()
