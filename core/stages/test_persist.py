"""persist 层测试:GPU ridge_svd 聚合键名归一化(R2_X/res_IC → r2_x/res_ic)。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.stages.persist import _aggregate_ridge_svd, _normalize_ridge_agg  # noqa: E402


def test_normalize_gpu_agg_keys():
    """platform_restest_factor 写入的 R2_X/res_IC 应归一为 r2_x/res_ic。"""
    agg = {
        "R2_X": 0.3446,
        "res_IC": -0.001189,
        "horizon": 10,
        "x_col": "X.SHFE-AG@x",
        "engine": "gpu",
    }
    normalized = _normalize_ridge_agg(agg)
    assert normalized is not None
    assert normalized["r2_x"] == 0.3446
    assert normalized["res_ic"] == -0.001189
    assert normalized["engine"] == "gpu"
    assert "dloocv_pct" not in normalized
    assert "dloocv_available" not in normalized


def test_aggregate_uses_strongest_res_ic():
    """聚合按主力场景 |res_IC| 最大那条, 不再依赖 dLOOCV。"""
    metrics = [{
        "x_col": "X.SHFE-AG@x", "horizon": 10,
        "R2_X": 0.5, "res_IC": 0.02, "n": 100,
    }, {
        "x_col": "X.SHFE-AG@x", "horizon": 60,
        "R2_X": 0.7, "res_IC": 0.08, "n": 100,
    }, {
        "x_col": "X.SHFE-AG@1@x", "horizon": 10,
        "R2_X": 0.3, "res_IC": 0.2, "n": 100,
    }]
    agg = _aggregate_ridge_svd(metrics)
    normalized = _normalize_ridge_agg(agg)
    assert normalized["r2_x"] == 0.7
    assert normalized["res_ic"] == 0.08
    assert normalized["engine"] == "gpu"


def main() -> None:
    test_normalize_gpu_agg_keys()
    test_aggregate_uses_strongest_res_ic()
    print("persist tests passed")


if __name__ == "__main__":
    main()
