"""分析层：单对指标计算 (metrics) + 全量筛选 (screening)。"""

from feval.analysis.metrics import analyze_pair, AnalysisResult
from feval.analysis.screening import run_screening

__all__ = ["analyze_pair", "AnalysisResult", "run_screening"]
