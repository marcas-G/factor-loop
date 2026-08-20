"""全局配置参数。

因子评估相关可调参数：
- 数据：CSV 路径、列前缀、时间/权重列名
- 分析：train/test 比例、rolling IC 窗口
- 输出：图片 DPI、尺寸
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """因子评估配置。"""

    # --- Data ---
    csv_path: Optional[Path] = None
    time_column: str = "receive_time"
    weight_column: str = "weight"
    x_prefix: str = "X."
    y_prefix: str = "Y."

    # --- Analysis ---
    train_ratio: float = 0.7
    train_cutoff_ns: Optional[int] = None

    # --- Output ---
    output_dir: Path = field(default_factory=lambda: Path("./feval_output"))
    dpi: int = 150
    figsize: tuple = (16, 10)
