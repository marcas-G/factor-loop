"""feval: 因子评估框架。

提供 7 维统计评估：Screening / Session IC / Vol-Regime IC / Linear Edge (beta t-stat + R²) / Quintile / Zero Analysis / Train-Test Decay。
"""

from feval.config import Config
from feval.data.columns import (
    ColumnType, ParsedXColumn, ParsedYColumn,
    classify_columns, parse_x_column, parse_y_column,
)
from feval.data.loader import load_csv, LoadedData
from feval.analysis.metrics import analyze_pair, AnalysisResult
from feval.analysis.screening import run_screening
from feval.eval import FeatureEvaluator, EvalResult

__all__ = [
    "Config",
    "LoadedData", "load_csv",
    "ColumnType", "ParsedXColumn", "ParsedYColumn",
    "classify_columns", "parse_x_column", "parse_y_column",
    "analyze_pair", "AnalysisResult", "run_screening",
    "FeatureEvaluator", "EvalResult",
]
