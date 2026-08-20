#!/usr/bin/env python3
"""下载 default 平台的 Raw 探针 .xy + 解压 + 放 xycache 路径。

流程: index 取 download_file URL → curl 下载 tar.gz → 解压到
/home/lgao/tmp/factor-vec-cache/<Probe>/dailyX/ → xycache 可读。

平台: default(.xy 原始数据)。featuretool_common.base_url(app='default') 显式指定,
无需 reload hack(base_url 已函数化)。

未就绪(success 但打包中 / 还在 running)的跳过, 不报错。
"""
import sys, re, os, tarfile, io, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # 项目根
from core.platform.featuretool_common import ensure_cookie, fetch, base_url, HOST

from core.config import CACHE_ROOT  # noqa: E402  单一真相缓存路径
PROBES = [
    "RawBidSize0", "RawBidSize1", "RawBidSize2", "RawBidSize3", "RawBidSize4",
    "RawAskSize0", "RawAskSize1", "RawAskSize2", "RawAskSize3", "RawAskSize4",
    "RawBidPrice0", "RawAskPrice0",
    "RawOI", "RawTotalVolume",
]

APP = "default"
cookie = ensure_cookie(app=APP)
bu = base_url(APP)
html = fetch(f"{bu}/index", cookie)

ready = []
for feat in PROBES:
    m = re.search(rf'href="(/featuretool/{APP}/download_file\?[^"]*feature={feat}[^"]*)"', html)
    if not m:
        print(f"  {feat}: index 无 dailyXs 链接(未 success)")
        continue
    url = HOST + m.group(1)
    subprocess.run(
        ["curl", "-skL", "--max-time", "180", "-b", f"session_id_featuretool={cookie}",
         "-o", "/tmp/_probe_dl", url], capture_output=True)
    data = open("/tmp/_probe_dl", "rb").read()
    if b"File not found" in data or len(data) < 1000:
        print(f"  {feat}: File not found(打包中, 稍后重试)")
        continue
    dest = f"{CACHE_ROOT}/{feat}"
    os.makedirs(dest, exist_ok=True)
    # 清旧
    import shutil
    dx = f"{dest}/dailyX"
    if os.path.isdir(dx):
        shutil.rmtree(dx)
    tarfile.open(fileobj=io.BytesIO(data), mode="r:gz").extractall(dest)
    n = len(os.listdir(dx)) if os.path.isdir(dx) else 0
    # 看列名确认
    first_xy = sorted(os.listdir(dx))[0] if n else None
    cols = ""
    if first_xy:
        with open(f"{dx}/{first_xy}") as f:
            cols = ",".join(c.strip() for c in f.readline().split(",") if c.strip().startswith("X."))
    print(f"  {feat}: ✓ {n} .xy | {cols}")
    ready.append(feat)

print(f"\n就绪: {len(ready)}/{len(PROBES)} → {ready}")
