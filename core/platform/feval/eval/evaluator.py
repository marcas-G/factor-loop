"""因子评估主入口。

FeatureEvaluator: 一键加载 CSV → 跑全部统计分析 → 返回 EvalResult。
EvalResult: 包含所有分析结果的 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Tuple

import numpy as np
import pandas as pd

from feval.config import Config
from feval.data.loader import load_csv, load_df, LoadedData
from feval.analysis.screening import run_screening

from feval.eval.metrics import (
    compute_session_ic,
    compute_vol_regime_ic,
    compute_linear_edge,
    compute_quintile,
    compute_zero_analysis,
    compute_train_test,
)


@dataclass
class EvalResult:
    """Complete factor evaluation result."""

    screening_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    session_ic_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    vol_regime_ic_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    linear_edge_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    quintile_df: Dict[Tuple[str, str], pd.DataFrame] = field(default_factory=dict)
    zero_analysis_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    train_test_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    decision_df: pd.DataFrame = field(default_factory=pd.DataFrame)


class FeatureEvaluator:
    """Generalized factor evaluation framework.

    Usage:
        ev = FeatureEvaluator()
        result = ev.evaluate('/path/to/data.csv')
        ev.report(result, output_dir='./eval_output')
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

    def evaluate(self, csv_path: str) -> EvalResult:
        """Run full evaluation pipeline on a CSV file.

        Args:
            csv_path: Path to CSV file with X and Y columns.

        Returns:
            EvalResult with all analysis DataFrames.
        """
        print(f'Loading {csv_path}...')
        data = load_csv(csv_path, self.config)
        print(f'  {len(data.x_columns)} X features, {len(data.y_columns)} Y targets')
        print(f'  {data.train_mask.sum():,} train, {data.test_mask.sum():,} test')

        return self._run_pipeline(data)

    def evaluate_df(self, df: pd.DataFrame, label: str = "DataFrame") -> EvalResult:
        """Run full evaluation pipeline on a DataFrame (no file I/O).

        Args:
            df: DataFrame with X/Y/receive_time columns.
            label: Label for logging (e.g. factor name).

        Returns:
            EvalResult with all analysis DataFrames.
        """
        print(f'Loading {label} ({len(df):,} rows)...')
        data = load_df(df, self.config)
        print(f'  {len(data.x_columns)} X features, {len(data.y_columns)} Y targets')
        print(f'  {data.train_mask.sum():,} train, {data.test_mask.sum():,} test')

        return self._run_pipeline(data)

    def _run_pipeline(self, data: LoadedData) -> EvalResult:

        print('Running screening...')
        screening_df = run_screening(data, self.config, period='all', parallel=False)
        print(f'  {len(screening_df)} pairs evaluated')

        print('Computing session IC...')
        session_ic_df = compute_session_ic(data, screening_df)

        print('Computing volatility-regime IC...')
        vol_regime_ic_df = compute_vol_regime_ic(data, screening_df)

        print('Computing linear edge...')
        linear_edge_df = compute_linear_edge(data, screening_df)

        print('Computing quintile analysis...')
        quintile_df = compute_quintile(data, screening_df, top_n=5)

        print('Computing zero analysis...')
        zero_analysis_df = compute_zero_analysis(data, screening_df)

        print('Computing train/test IC decay...')
        train_test_df = compute_train_test(data, screening_df)

        print('Computing decision summary...')
        from feval.eval.decision import compute_decision_summary
        tmp_result = EvalResult(
            screening_df=screening_df,
            session_ic_df=session_ic_df,
            vol_regime_ic_df=vol_regime_ic_df,
            linear_edge_df=linear_edge_df,
            quintile_df=quintile_df,
            zero_analysis_df=zero_analysis_df,
            train_test_df=train_test_df,
        )
        decision_df = compute_decision_summary(tmp_result)

        print('Done.')
        return EvalResult(
            screening_df=screening_df,
            session_ic_df=session_ic_df,
            vol_regime_ic_df=vol_regime_ic_df,
            linear_edge_df=linear_edge_df,
            quintile_df=quintile_df,
            zero_analysis_df=zero_analysis_df,
            train_test_df=train_test_df,
            decision_df=decision_df,
        )

    def report(self, result: EvalResult, output_dir: str = './eval_output') -> None:
        """Generate full report: tables + plots saved to output_dir.

        Args:
            result: EvalResult from evaluate().
            output_dir: Directory to save plots and tables.
        """
        from feval.eval.visualizer import (
            plot_session_ic,
            plot_vol_regime_ic,
            plot_linear_edge,
            plot_quintile_monotonicity,
            plot_ic_decay,
            plot_train_test_scatter,
            plot_summary_dashboard,
            build_label_map,
        )

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Build label map
        label_map = build_label_map(result)
        pd.DataFrame([
            {'alias': v, 'x_col': k}
            for k, v in label_map.items()
        ]).to_csv(out / 'label_map.csv', index=False)

        # Save CSV tables
        result.screening_df.to_csv(out / 'screening.csv', index=False)
        result.session_ic_df.to_csv(out / 'session_ic.csv', index=False)
        result.vol_regime_ic_df.to_csv(out / 'vol_regime_ic.csv', index=False)
        result.linear_edge_df.to_csv(out / 'linear_edge.csv', index=False)
        result.zero_analysis_df.to_csv(out / 'zero_analysis.csv', index=False)
        result.train_test_df.to_csv(out / 'train_test.csv', index=False)

        if not result.decision_df.empty:
            result.decision_df.to_csv(out / 'decision_summary.csv', index=False)

        # Save summary.md
        _write_markdown_summary(result, out / 'summary.md')

        # Save plots
        figs = {
            'session_ic': plot_session_ic(result),
            'vol_regime_ic': plot_vol_regime_ic(result),
            'linear_edge': plot_linear_edge(result),
            'quintile': plot_quintile_monotonicity(result),
            'ic_decay': plot_ic_decay(result),
            'train_test': plot_train_test_scatter(result),
            'dashboard': plot_summary_dashboard(result),
        }

        dpi = self.config.dpi
        for name, fig in figs.items():
            fig.savefig(out / f'{name}.png', dpi=dpi, bbox_inches='tight')

        print(f'Report saved to {out}/')


def _write_markdown_summary(result: EvalResult, output_path: Path, top_n: int = 10) -> None:
    """Write summary.md — the primary human-readable decision report."""
    df = result.decision_df
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('# Factor Evaluation Summary\n\n')

        if df.empty:
            f.write('No decision summary available.\n')
            return

        counts = df['decision'].value_counts().to_dict()
        f.write('## Decision Counts\n\n')
        for k in ['KEEP', 'WATCH', 'REJECT']:
            f.write(f'- {k}: {counts.get(k, 0)}\n')

        f.write('\n## Top Candidates\n\n')

        top = df.head(top_n)
        for i, (_, row) in enumerate(top.iterrows(), 1):
            f.write(f'### {i}. {row.get("decision", "")} | Score={row.get("score", "")}\n\n')
            f.write(f'- X: `{row.get("x_col", "")}`\n')
            f.write(f'- Y: `{row.get("y_col", "")}`\n')
            f.write(f'- Horizon: {row.get("horizon", "")}\n')
            f.write(f'- IC: {row.get("ic_mean", np.nan):+.6f}\n')
            f.write(f'- ICIR: {row.get("ic_ir", np.nan):+.3f}\n')
            f.write(f'- Test IC: {row.get("test_ic", np.nan):+.6f}\n')
            f.write(f'- Same Sign: {row.get("same_sign", "")}\n')
            f.write(f'- Bucket: {row.get("bucket_direction", "")}, spread={row.get("bucket_spread", np.nan)}\n')
            f.write(f'- Zero Diff: {row.get("zero_diff", np.nan)}\n')
            f.write(f'- Beta t-stat: {row.get("beta_tstat", np.nan)}\n')
            f.write(f'- Reason: {row.get("reason", "")}\n\n')