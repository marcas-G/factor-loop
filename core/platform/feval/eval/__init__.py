"""因子评估模块（eval）。

通用化的因子统计分析框架：放入任何 X/Y CSV，自动跑完整评估流程，
输出 IC/ICIR/分层单调性/IC 衰减/时段分析/波动率区间分析。
决策引擎：生成 decision_summary.csv（KEEP/WATCH/REJECT）和 summary.md。

用法:
    from feval.eval import FeatureEvaluator
    ev = FeatureEvaluator()
    result = ev.evaluate('/path/to/data.csv')
    ev.report(result, output_dir='./eval_output')
"""

from feval.eval.evaluator import FeatureEvaluator, EvalResult

__all__ = ["FeatureEvaluator", "EvalResult"]