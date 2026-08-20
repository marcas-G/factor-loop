"""CSV 列名解析与分类。

将 C++ 导出的列名解析为结构化字段：
- X 列: X.SHFE-AG@XXY_trade_bar_0.8_0.8_5    → 合约 + level=0 + 特征名
- X 列: X.SHFE-AG@1@XXY_trade_imb_0.8_0.8_5   → 合约 + level=1 + 特征名
  level = order book 盘口层级，0 对应实际 level 1 (买1/卖1)，1 对应 level 2
- Y 列: Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@60  → 合约 + 价格类型 + 前瞻 horizon

并提供 classify_columns() 自动分类所有列为 X/Y/时间/权重。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple


class ColumnType(Enum):
    TIME = "time"
    WEIGHT = "weight"
    X_FEATURE = "x_feature"
    Y_TARGET = "y_target"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedXColumn:
    """Parsed representation of an X column name.

    Examples:
        'X.SHFE-AG@XXY_trade_imb_0.8_0.8_5'   -> level=0, feature='XXY_trade_imb_0.8_0.8_5'
        'X.SHFE-AG@1@XXY_trade_bar_0.8_0.8_5'  -> level=1, feature='XXY_trade_bar_0.8_0.8_5'
        'X.SHFE-CU@XXY_trade_imb_0.8_0.8_5'    -> level=0, feature='XXY_trade_imb_0.8_0.8_5'
    """
    full_name: str
    instrument: str       # e.g. 'SHFE-AG'
    level: int            # order book level: 0 = level 1 (买1/卖1), 1 = level 2
    feature_name: str     # e.g. 'XXY_trade_imb_0.8_0.8_5'


@dataclass(frozen=True)
class ParsedYColumn:
    """Parsed representation of a Y column name.

    Example: 'Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@60'

    Fields:
        YIndexSeconds = time unit is seconds
        PriceMid      = mid price as reference price
        SHFE-AG       = instrument
        60            = 60-second forward horizon
    """
    full_name: str
    time_unit: str        # e.g. 'Seconds'
    price_type: str       # e.g. 'PriceMid'
    instrument: str       # e.g. 'SHFE-AG'
    horizon_seconds: int  # e.g. 60


# --- Regex patterns ---

# X: X.<instrument>[@<level>]<@feature>
# Two '@' after prefix: first numeric is level, second is feature name
# One '@' after prefix: it's the feature name (level=0)
_X_PATTERN = re.compile(
    r'^X\.'
    r'(?P<instrument>[A-Za-z0-9_-]+)'  # instrument: SHFE-AG, SHFE-CU, etc.
    r'(?:@(?P<level_or_feature>[^@]+))?'  # everything after first @
    r'(?:@(?P<feature>[^@]+))?$'        # if second @, that's the feature
)

# Y: Y.Y_Y<time_unit><<price_type>>.<instrument>@<horizon>
_Y_PATTERN = re.compile(
    r'^Y\.Y_Y'
    r'(?P<time_unit>[A-Za-z]+)'          # e.g. 'IndexSeconds'
    r'<(?P<price_type>[A-Za-z]+)>'       # e.g. 'PriceMid'
    r'\.(?P<instrument>[A-Za-z0-9_-]+)'  # e.g. 'SHFE-AG'
    r'@(?P<horizon>\d+)$'               # e.g. '60'
)


def parse_x_column(name: str) -> Optional[ParsedXColumn]:
    """Parse an X column name into structured fields.

    Naming convention:
      - 'X.SHFE-AG@XXY_trade_imb_0.8_0.8_5'   -> level=0 (买1/卖1)
      - 'X.SHFE-AG@1@XXY_trade_bar_0.8_0.8_5'  -> level=1 (买2/卖2)
    """
    if not name.startswith("X."):
        return None

    m = _X_PATTERN.match(name)
    if not m:
        return None

    instrument = m.group("instrument")
    level_or_feature = m.group("level_or_feature")
    feature = m.group("feature")

    if feature is not None:
        # Two '@' segments: first is level (must be numeric), second is feature
        try:
            level = int(level_or_feature)
        except (ValueError, TypeError):
            return None
        return ParsedXColumn(
            full_name=name,
            instrument=instrument,
            level=level,
            feature_name=feature,
        )
    elif level_or_feature is not None:
        # One '@' segment: it's the feature name (level=0 by default)
        return ParsedXColumn(
            full_name=name,
            instrument=instrument,
            level=0,
            feature_name=level_or_feature,
        )
    else:
        return ParsedXColumn(
            full_name=name,
            instrument=instrument,
            level=0,
            feature_name="",
        )


def parse_y_column(name: str) -> Optional[ParsedYColumn]:
    """Parse a Y column name into structured fields.

    Example: 'Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@60'
    """
    if not name.startswith("Y."):
        return None

    m = _Y_PATTERN.match(name)
    if not m:
        return None

    return ParsedYColumn(
        full_name=name,
        time_unit=m.group("time_unit"),
        price_type=m.group("price_type"),
        instrument=m.group("instrument"),
        horizon_seconds=int(m.group("horizon")),
    )


def classify_columns(
    columns: List[str],
    time_column: str = "receive_time",
    weight_column: str = "weight",
    x_prefix: str = "X.",
    y_prefix: str = "Y.",
) -> Tuple[List[str], List[str], Optional[str], Optional[str]]:
    """Classify columns into X features, Y targets, time, and weight.

    Returns:
        (x_columns, y_columns, time_column_name, weight_column_name)
    """
    x_cols: List[str] = []
    y_cols: List[str] = []
    time_col: Optional[str] = None
    weight_col: Optional[str] = None

    for col in columns:
        if col == time_column:
            time_col = col
        elif col == weight_column:
            weight_col = col
        elif col.startswith(y_prefix) and parse_y_column(col) is not None:
            y_cols.append(col)
        elif col.startswith(x_prefix) and parse_x_column(col) is not None:
            x_cols.append(col)
        # else: UNKNOWN, silently skip

    return x_cols, y_cols, time_col, weight_col
