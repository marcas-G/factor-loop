"""CSV 数据加载。

读取特征 CSV，完成：
1. 自动识别 X/Y/时间/权重列
2. 时间戳解析为 int64 纳秒
3. 按时间严格划分 train/test（防止未来信息泄漏）
4. 返回 LoadedData 供后续 screening 和 eval 使用
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from feval.config import Config
from feval.data.columns import classify_columns, parse_x_column, parse_y_column


@dataclass
class LoadedData:
    """Container for a loaded CSV dataset."""

    df: pd.DataFrame
    receive_time: np.ndarray  # int64 nanosecond timestamps
    weight: np.ndarray        # sample weights (float64)
    x_columns: list
    y_columns: list
    x_values: pd.DataFrame
    y_values: pd.DataFrame
    train_mask: np.ndarray    # boolean
    test_mask: np.ndarray     # boolean

    @property
    def train_x(self) -> pd.DataFrame:
        return self.x_values[self.train_mask]

    @property
    def train_y(self) -> pd.DataFrame:
        return self.y_values[self.train_mask]

    @property
    def test_x(self) -> pd.DataFrame:
        return self.x_values[self.test_mask]

    @property
    def test_y(self) -> pd.DataFrame:
        return self.y_values[self.test_mask]

    @property
    def train_time(self) -> np.ndarray:
        return self.receive_time[self.train_mask]

    @property
    def test_time(self) -> np.ndarray:
        return self.receive_time[self.test_mask]

    @property
    def train_weight(self) -> np.ndarray:
        return self.weight[self.train_mask]

    @property
    def test_weight(self) -> np.ndarray:
        return self.weight[self.test_mask]

    def x_parsed(self, col: str):
        """Return parsed metadata for an X column."""
        return parse_x_column(col)

    def y_parsed(self, col: str):
        """Return parsed metadata for a Y column."""
        return parse_y_column(col)


def _prepare_loaded_data(
    df: pd.DataFrame,
    config: Config,
) -> LoadedData:
    """Shared logic: classify columns, extract arrays, train/test split."""
    if config.time_column not in df.columns:
        raise ValueError(f"Time column '{config.time_column}' not found. "
                         f"Available: {list(df.columns)}")

    # 时间列容错:多文件 concat(merge_daily_xy)可能引入 NaT/空值,
    # 先 coerce + drop 无效行(整行 drop 保持 x/y/time 对齐),再 sort/astype。
    # 沿用本仓范式(factor_check.py 用 pd.to_numeric(errors="coerce") + dropna)。
    _time_coerced = pd.to_numeric(df[config.time_column], errors="coerce")
    _time_valid = _time_coerced.notna()
    if not _time_valid.all():
        df = df[_time_valid.values].reset_index(drop=True)
        _time_coerced = _time_coerced[_time_valid]
    df[config.time_column] = _time_coerced.values

    df = df.sort_values(config.time_column).reset_index(drop=True)

    x_cols, y_cols, time_col, weight_col = classify_columns(
        df.columns.tolist(),
        time_column=config.time_column,
        weight_column=config.weight_column,
        x_prefix=config.x_prefix,
        y_prefix=config.y_prefix,
    )

    if not x_cols:
        raise ValueError(f"No X columns found with prefix '{config.x_prefix}'. "
                         f"Available: {list(df.columns)}")
    if not y_cols:
        raise ValueError(f"No Y columns found with prefix '{config.y_prefix}'. "
                         f"Available: {list(df.columns)}")

    receive_time = df[config.time_column].values.astype(np.int64)
    weight = (df[config.weight_column].values.astype(np.float64)
              if weight_col and config.weight_column in df.columns
              else np.ones(len(df), dtype=np.float64))

    x_values = df[x_cols].astype(np.float64)
    y_values = df[y_cols].astype(np.float64)

    if config.train_cutoff_ns is not None:
        cutoff = config.train_cutoff_ns
    else:
        cutoff = np.quantile(receive_time, config.train_ratio)

    train_mask = receive_time <= cutoff
    test_mask = ~train_mask

    return LoadedData(
        df=df,
        receive_time=receive_time,
        weight=weight,
        x_columns=x_cols,
        y_columns=y_cols,
        x_values=x_values,
        y_values=y_values,
        train_mask=train_mask,
        test_mask=test_mask,
    )


def load_csv(
    path,
    config: Optional[Config] = None,
) -> LoadedData:
    """Load a feature CSV file.

    Args:
        path: Path to the CSV file (str or Path).
        config: Optional Config. If None, uses defaults.

    Returns:
        LoadedData with classified columns and train/test masks.
    """
    if config is None:
        config = Config()

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    return _prepare_loaded_data(df, config)


def load_df(
    df: pd.DataFrame,
    config: Optional[Config] = None,
) -> LoadedData:
    """Load a feature DataFrame directly (no file I/O).

    Args:
        df: DataFrame with X/Y/receive_time columns.
        config: Optional Config. If None, uses defaults.

    Returns:
        LoadedData with classified columns and train/test masks.
    """
    if config is None:
        config = Config()
    return _prepare_loaded_data(df.copy(), config)
