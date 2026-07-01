"""因子评估可视化。

所有 eval 相关图表集中在此，输入是 EvalResult，输出 plt.Figure。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if TYPE_CHECKING:
    from feval.eval.evaluator import EvalResult


def _short_label(x_col: str, max_len: int = 20, label_map: dict | None = None) -> str:
    """Generate a short human-readable label from an X column name."""
    if label_map and x_col in label_map:
        return label_map[x_col]

    s = x_col.replace('X.', '').replace('XXY_trade_', '').replace('xxy_', '')
    if len(s) > max_len:
        s = s[:max_len] + '...'
    return s


def build_label_map(result) -> dict:
    """Build F001/F002 alias map for all unique X columns."""
    x_cols = []
    for df in [
        result.screening_df,
        result.session_ic_df,
        result.vol_regime_ic_df,
        result.linear_edge_df,
        result.zero_analysis_df,
        result.train_test_df,
    ]:
        if df is not None and not df.empty and 'x_col' in df.columns:
            x_cols.extend(df['x_col'].dropna().unique().tolist())

    x_cols = sorted(set(x_cols))
    return {x: f'F{i+1:03d}' for i, x in enumerate(x_cols)}


def plot_session_ic(result: EvalResult) -> plt.Figure:
    """Bar chart of IC by SHFE trading session, grouped by instrument."""
    df = result.session_ic_df
    if df.empty:
        return _empty_fig("No session IC data")

    sessions = ['morning', 'midday', 'afternoon', 'night']
    session_labels = ['Morning\n09-10', 'Midday\n10:30-11:30', 'Afternoon\n13:30-15', 'Night\n21-02:30']

    instruments = sorted(df['instrument'].unique())
    n_inst = len(instruments)

    fig, axes = plt.subplots(1, n_inst, figsize=(6 * n_inst, 5), squeeze=False)

    colors = ['#2196F3', '#F44336', '#4CAF50', '#9C27B0']

    for i, inst in enumerate(instruments):
        ax = axes[0, i]
        sub = df[df['instrument'] == inst]
        x = np.arange(len(sessions))
        width = 0.35

        horizons = sorted(sub['horizon'].unique())
        for h_idx, h in enumerate(horizons):
            h_sub = sub[sub['horizon'] == h]
            offset = (h_idx - len(horizons) / 2) * width
            for s_idx, sess in enumerate(sessions):
                col = f'{sess}_ic'
                val = h_sub[col].mean() if col in h_sub.columns else 0
                color = colors[h_idx % len(colors)]
                ax.bar(x[s_idx] + offset, val, width, color=color, alpha=0.7,
                       label=f'@{h}s' if s_idx == 0 else None)

        ax.set_xticks(x)
        ax.set_xticklabels(session_labels, fontsize=7)
        ax.set_ylabel('IC (Spearman)')
        ax.set_title(inst, fontsize=11)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')
        if i == 0:
            ax.legend(fontsize=7, loc='lower left')

    fig.suptitle('IC by Trading Session', fontsize=13)
    fig.tight_layout()
    return fig


def plot_vol_regime_ic(result: EvalResult) -> plt.Figure:
    """Line chart of IC across volatility regime (low vol -> high vol).

    Y axis rolling std is used as a proxy for market volatility regime.
    Data is split into 5 quintiles; IC is computed within each bucket.
    A robust factor should have positive IC across all regimes.
    """
    df = result.vol_regime_ic_df
    if df.empty:
        return _empty_fig("No vol-regime IC data")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), squeeze=False)

    for ax_idx, inst in enumerate(sorted(df['instrument'].unique())):
        ax = axes[0, min(ax_idx, axes.shape[1] - 1)]
        sub = df[df['instrument'] == inst]

        q_cols = [c for c in sub.columns if c.startswith('q') and c.endswith('_ic')]
        if not q_cols:
            continue

        means = []
        stds = []
        for _, row in sub.iterrows():
            vals = [row[c] for c in q_cols if not np.isnan(row[c])]
            means.append(np.mean(vals))
            stds.append(np.std(vals))

        if means:
            x = range(1, len(means) + 1)
            ax.errorbar(x, means, yerr=stds, fmt='o-', capsize=3,
                         linewidth=1.5, markersize=5, label=inst)

    axes[0, 1].set_xlabel('Volatility Quintile (1=low, 5=high)')
    for a in axes.flat:
        a.set_ylabel('IC')
        a.axhline(0, color='black', linewidth=0.5)
        a.legend(fontsize=9)
        a.grid(True, alpha=0.3)
    axes[0, 0].set_title('IC vs Volatility Regime')

    fig.tight_layout()
    return fig


def plot_linear_edge(result: EvalResult) -> plt.Figure:
    """Bar chart of beta t-statistic from linear calibration Y = alpha + beta * X.

    beta_tstat = beta / SE(beta). |t| > 2 means significant at p < 0.05.
    Measures how significant the linear relationship Y = alpha + beta * X is.
    """
    df = result.linear_edge_df
    if df.empty:
        return _empty_fig("No linear edge data")

    col = 'beta_tstat'
    if col not in df.columns:
        return _empty_fig("No beta_tstat column")
    df = df.dropna(subset=[col]).copy()
    df['_abs_tstat'] = df[col].abs()
    df = df.sort_values('_abs_tstat', ascending=False).head(30)

    fig, ax = plt.subplots(figsize=(14, max(5, len(df) * 0.3)))

    labels = []
    for _, row in df.iterrows():
        short_x = _short_label(row['x_col'], max_len=15)
        r2 = row.get('linear_r2', np.nan)
        r2_str = f' R2={r2:.4f}' if not pd.isna(r2) else ''
        labels.append(f'{row["instrument"]} {short_x} @{row["horizon"]}s{r2_str}')

    colors = ['#4CAF50' if abs(v) >= 3 else '#FF9800' if abs(v) >= 2 else '#F44336'
              for v in df[col].values]
    y_pos = range(len(df))
    ax.barh(y_pos, df[col].values, color=colors, alpha=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('beta t-statistic  (beta / SE(beta))')
    ax.axvline(x=2.0, color='orange', linewidth=1, linestyle='--', alpha=0.7, label='|t|=2 (p<0.05)')
    ax.axvline(x=-2.0, color='orange', linewidth=1, linestyle='--', alpha=0.7)
    ax.axvline(x=3.0, color='green', linewidth=1, linestyle='--', alpha=0.7, label='|t|=3 (p<0.01)')
    ax.axvline(x=-3.0, color='green', linewidth=1, linestyle='--', alpha=0.7)
    ax.axvline(x=0, color='black', linewidth=0.5)
    ax.grid(True, alpha=0.3, axis='x')
    ax.legend(fontsize=8)
    ax.set_title('Linear Edge: beta t-stat  (green=|t|>=3, orange>=2, red<2)', fontsize=10)
    ax.invert_yaxis()

    fig.tight_layout()
    return fig


def plot_quintile_monotonicity(result: EvalResult) -> plt.Figure:
    """Bar chart of Y mean by X quintile for top pairs.

    X values are daily-internally quintiled (Q1=lowest, Q5=highest).
    Zero bucket (Z): X=0 rows shown separately.
    Supports both positive (Q1<Q2<...<Q5) and negative monotonic direction.
    """
    pairs = result.quintile_df
    if not pairs:
        return _empty_fig("No quintile data")

    n = len(pairs)
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)
    axes_flat = axes.flat

    zero_color = '#9E9E9E'
    quintile_colors = ['#F44336', '#FF9800', '#FFEB3B', '#8BC34A', '#4CAF50']

    for idx, (key, bucket_df) in enumerate(pairs.items()):
        ax = axes_flat[idx]
        short = f'{_short_label(key[0], 15)} @{key[1].split("@")[-1]}s'

        direction = getattr(bucket_df, 'attrs', {}).get('direction', '')
        dir_arrow = ' ↑' if direction == 'positive' else ' ↓' if direction == 'negative' else ''

        x_pos = range(len(bucket_df))
        bar_colors = []
        for b in bucket_df.index:
            if b == 'Z':
                bar_colors.append(zero_color)
            elif b in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']:
                bar_colors.append(quintile_colors[int(b[1]) - 1])
            else:
                bar_colors.append('#9E9E9E')

        ax.bar(x_pos, bucket_df['Y_mean'], color=bar_colors, alpha=0.8)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(bucket_df.index, fontsize=8)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.set_ylabel('Mean Y')
        ax.set_title(f'{short}{dir_arrow}', fontsize=9)

        for i, v in enumerate(bucket_df['Y_mean']):
            ax.text(i, v + 0.002 * np.sign(v), f'{v:+.5f}', ha='center', fontsize=7)
        if 'hit_rate' in bucket_df.columns:
            for i, v in enumerate(bucket_df['hit_rate']):
                ax.text(i, v * 0.85, f'{v:.0%}', ha='center', fontsize=6, color='white')

        ax.grid(True, alpha=0.3, axis='y')

    for idx in range(n, nrows * ncols):
        axes_flat[idx].set_visible(False)

    fig.suptitle('Quintile Monotonicity  (daily-internal bucket, Z=zero bucket)', fontsize=12)
    fig.tight_layout()
    return fig


def plot_ic_decay(result: EvalResult) -> plt.Figure:
    """Bar chart of IC vs forward horizon, one subplot per feature.

    Shows how IC decays as the prediction horizon increases.
    A good factor has high IC at short horizons that decays gracefully.
    """
    df = result.screening_df
    if df.empty:
        return _empty_fig("No screening data")

    features = sorted(df['x_col'].unique())

    # Limit to features with nonzero |IC| to avoid wasted space
    active = []
    for f in features:
        sub = df[df['x_col'] == f]
        if sub['ic_mean'].abs().max() > 1e-6:
            active.append(f)
    if not active:
        active = features

    ncols = min(3, len(active))
    nrows = (len(active) + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)
    axes_flat = axes.flat

    for ax_idx, x_col in enumerate(active):
        ax = axes_flat[ax_idx]
        sub = df[df['x_col'] == x_col].sort_values('horizon')

        horizons = sub['horizon'].values
        ic_vals = sub['ic_mean'].values

        short_label = _short_label(x_col, max_len=25)
        colors_bar = ['#F44336' if v < 0 else '#4CAF50' for v in ic_vals]
        ax.bar(range(len(horizons)), ic_vals, color=colors_bar, alpha=0.8, width=0.6)

        ax.set_xticks(range(len(horizons)))
        ax.set_xticklabels([f'@{h}s' for h in horizons])
        ax.set_ylabel('IC')
        ax.set_title(short_label, fontsize=9)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')

        for i, v in enumerate(ic_vals):
            ax.text(i, v + 0.002 * np.sign(v), f'{v:+.4f}', ha='center', fontsize=8)

    for idx in range(len(active), nrows * ncols):
        axes_flat[idx].set_visible(False)

    fig.suptitle('IC Decay by Horizon', fontsize=12)
    fig.tight_layout()
    return fig


def plot_train_test_scatter(result: EvalResult) -> plt.Figure:
    """Scatter plot: Train IC vs Test IC, colored by decay ratio.

    Data is split chronologically (first 70% train, last 30% test).
    Decay = test_ic / train_ic.
    Green: |decay| > 0.7 (robust), Orange: 0.3-0.7 (light overfit), Red: < 0.3 (severe).
    Points near the diagonal mean train and test agree.
    """
    df = result.train_test_df
    if df.empty:
        return _empty_fig("No train/test data")

    fig, ax = plt.subplots(figsize=(8, 8))

    decay = df['ic_decay'].values
    colors_scatter = np.where(
        np.abs(decay) > 0.7, '#4CAF50',
        np.where(np.abs(decay) > 0.3, '#FF9800', '#F44336'),
    )

    ax.scatter(df['train_ic'], df['test_ic'], c=colors_scatter, alpha=0.6, s=30, edgecolors='none')
    lim = max(abs(df['train_ic']).max(), abs(df['test_ic']).max(), 0.01) * 1.1
    ax.plot([-lim, lim], [-lim, lim], 'k--', linewidth=1, alpha=0.3)
    ax.set_xlabel('Train IC (first 70% of data)')
    ax.set_ylabel('Test IC (last 30% of data)')
    ax.set_title('Train vs Test IC  (green=robust, orange=light OF, red=severe)')
    ax.grid(True, alpha=0.3)

    n_robust = (np.abs(decay) > 0.7).sum()
    n_light = ((np.abs(decay) > 0.3) & (np.abs(decay) <= 0.7)).sum()
    n_severe = (np.abs(decay) <= 0.3).sum()
    ax.text(0.02, 0.98, f'Robust: {n_robust}  Light OF: {n_light}  Severe OF: {n_severe}',
            transform=ax.transAxes, va='top', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fig.tight_layout()
    return fig


def plot_summary_dashboard(result: EvalResult) -> plt.Figure:
    """2x3 summary dashboard."""
    fig = plt.figure(figsize=(20, 12))

    ax1 = fig.add_subplot(2, 3, 1)
    _mini_screening(ax1, result.screening_df)

    ax2 = fig.add_subplot(2, 3, 2)
    if not result.screening_df.empty:
        top = result.screening_df.nlargest(10, 'ic_mean')
        features = sorted(top['x_col'].unique())
        for f_idx, feat in enumerate(features):
            sub = top[top['x_col'] == feat].sort_values('horizon')
            offset = (f_idx - len(features) / 2) * 0.35
            ax2.bar(sub['horizon'] + offset, sub['ic_mean'], 0.35, alpha=0.8,
                    label=_short_label(feat, 15))
        ax2.set_title('Top 10 IC by Horizon')
        ax2.axhline(0, color='black', linewidth=0.5)
        ax2.legend(fontsize=6)
        ax2.grid(True, alpha=0.3)

    ax3 = fig.add_subplot(2, 3, 3)
    if not result.train_test_df.empty:
        d = result.train_test_df
        decay = d['ic_decay'].values
        ax3.scatter(d['train_ic'], d['test_ic'],
                    c=np.where(np.abs(decay) > 0.7, '#4CAF50', np.where(np.abs(decay) > 0.3, '#FF9800', '#F44336')),
                    alpha=0.6, s=25, edgecolors='none')
        ax3.plot([-0.05, 0.05], [-0.05, 0.05], 'k--', linewidth=0.5, alpha=0.3)
        ax3.set_title('Train vs Test IC')
        ax3.set_xlabel('Train IC'); ax3.set_ylabel('Test IC')
        ax3.grid(True, alpha=0.3)

    ax4 = fig.add_subplot(2, 3, 4)
    _mini_session(ax4, result.session_ic_df)

    ax5 = fig.add_subplot(2, 3, 5)
    _mini_linear_edge(ax5, result.linear_edge_df)

    ax6 = fig.add_subplot(2, 3, 6)
    _mini_quintile(ax6, result.quintile_df)

    fig.suptitle('Factor Evaluation Dashboard', fontsize=14, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


# --- Mini helpers for dashboard ---

def _mini_screening(ax: plt.Axes, df: pd.DataFrame):
    if df.empty:
        return
    top = df.nlargest(15, 'ic_mean')
    short = top['x_col'].apply(_short_label)
    colors = ['#4CAF50' if v > 0 else '#F44336' for v in top['ic_mean'].values]
    ax.barh(range(len(top)), top['ic_mean'].values, color=colors, alpha=0.8)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(short, fontsize=7)
    ax.set_xlabel('IC')
    ax.invert_yaxis()
    ax.set_title('Top 15 Pairs', fontsize=10)
    ax.grid(True, alpha=0.3, axis='x')


def _mini_session(ax: plt.Axes, df: pd.DataFrame):
    if df.empty:
        return
    sessions = ['morning_ic', 'midday_ic', 'afternoon_ic', 'night_ic']
    labels = ['Morning', 'Midday', 'Afternoon', 'Night']
    instruments = sorted(df['instrument'].unique())
    x = np.arange(len(sessions))
    width = 0.8 / max(len(instruments), 1)
    colors = ['#2196F3', '#F44336', '#4CAF50', '#9C27B0']
    for i, inst in enumerate(instruments):
        sub = df[df['instrument'] == inst]
        means = [sub[s].mean() if s in sub.columns else 0 for s in sessions]
        ax.bar(x + i * width, means, width, color=colors[i % len(colors)], alpha=0.7, label=inst)
    ax.set_xticks(x + width * (len(instruments) - 1) / 2)
    ax.set_xticklabels(labels, fontsize=8)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_ylabel('IC')
    ax.set_title('Session IC', fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3, axis='y')


def _mini_linear_edge(ax: plt.Axes, df: pd.DataFrame):
    if df.empty:
        return
    col = 'beta_tstat'
    if col not in df.columns:
        return
    # Show average |beta_tstat| by instrument
    df_c = df.dropna(subset=[col]).copy()
    df_c['_abs_t'] = df_c[col].abs()
    agg = df_c.groupby('instrument')['_abs_t'].mean().sort_values()
    colors = ['#4CAF50' if v >= 3 else '#FF9800' if v >= 2 else '#F44336' for v in agg.values]
    ax.bar(range(len(agg)), agg.values, color=colors, alpha=0.8)
    ax.set_xticks(range(len(agg)))
    ax.set_xticklabels(agg.index, fontsize=9)
    ax.set_ylabel('Avg |beta t-stat|')
    ax.axhline(2.0, color='orange', linewidth=1, linestyle='--', alpha=0.7)
    ax.axhline(3.0, color='green', linewidth=1, linestyle='--', alpha=0.7)
    ax.set_title('Avg |beta t-stat| by Instrument', fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    for i, v in enumerate(agg.values):
        ax.text(i, v + 0.1, f'{v:.1f}', ha='center', fontsize=8)


def _mini_quintile(ax: plt.Axes, quintile_df: dict):
    if not quintile_df:
        return
    key = list(quintile_df.keys())[0]
    bucket_df = quintile_df[key]
    zero_color = '#9E9E9E'
    quintile_colors = ['#F44336', '#FF9800', '#FFEB3B', '#8BC34A', '#4CAF50']

    bar_colors = []
    for b in bucket_df.index:
        if b == 'Z':
            bar_colors.append(zero_color)
        elif b in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']:
            bar_colors.append(quintile_colors[int(b[1]) - 1])
        else:
            bar_colors.append('#9E9E9E')

    x = range(len(bucket_df))
    ax.bar(x, bucket_df['Y_mean'], color=bar_colors, alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(bucket_df.index, fontsize=8)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_ylabel('Mean Y')
    direction = getattr(bucket_df, 'attrs', {}).get('direction', '')
    dir_arrow = ' ↑' if direction == 'positive' else ' ↓' if direction == 'negative' else ''
    short = f'{_short_label(key[0], 12)} @{key[1].split("@")[-1]}s'
    ax.set_title(f'Quintile: {short}{dir_arrow}', fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')


def plot_ic_heatmap(result: EvalResult) -> plt.Figure:
    """Heatmap: IC matrix of (X feature) x (Y horizon).

    Rows = X features (sorted), columns = Y horizons.
    Color intensity shows IC magnitude; green=positive, red=negative.
    Annotated with IC values.
    """
    df = result.screening_df
    if df.empty:
        return _empty_fig("No screening data")

    # Pivot to matrix: rows=x_col, columns=horizon, values=ic_mean
    ic_matrix = df.pivot_table(index='x_col', columns='horizon', values='ic_mean')
    # Sort by best |IC| row
    ic_matrix['_best'] = ic_matrix.abs().max(axis=1)
    ic_matrix = ic_matrix.sort_values('_best', ascending=True)
    ic_matrix = ic_matrix.drop(columns='_best')

    fig, ax = plt.subplots(figsize=(14, max(6, len(ic_matrix) * 0.5)))

    short_rows = [_short_label(r, max_len=30) for r in ic_matrix.index]
    col_labels = [f'@{int(h)}s' for h in ic_matrix.columns]

    im = ax.imshow(ic_matrix.values, cmap='RdYlGn', aspect='auto',
                   vmin=-0.15, vmax=0.15)

    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=9)
    ax.set_yticks(range(len(short_rows)))
    ax.set_yticklabels(short_rows, fontsize=8)
    ax.set_xlabel('Y Horizon')
    ax.set_title('IC Heatmap  (green=positive IC, red=negative IC)', fontsize=11)

    # Annotate each cell
    for i in range(len(ic_matrix)):
        for j in range(len(ic_matrix.columns)):
            val = ic_matrix.iloc[i, j]
            if not np.isnan(val):
                color = 'white' if abs(val) > 0.10 else 'black'
                ax.text(j, i, f'{val:+.4f}', ha='center', va='center',
                        fontsize=7, color=color)

    fig.colorbar(im, ax=ax, label='IC (Spearman)', shrink=0.8)
    fig.tight_layout()
    return fig


def plot_session_ic_heatmap(result: EvalResult) -> plt.Figure:
    """Heatmap: Session IC by (X feature) x (Trading Session).

    Rows = X features, columns = Morning/Midday/Afternoon/Night.
    """
    df = result.session_ic_df
    if df.empty:
        return _empty_fig("No session IC data")

    sessions = ['morning_ic', 'midday_ic', 'afternoon_ic', 'night_ic']
    session_labels = ['Morning\n09-10', 'Midday\n10:30-11:30', 'Afternoon\n13:30-15', 'Night\n21-02:30']

    # For each X feature, pick the pair with highest |IC| across sessions
    df['_avg_abs'] = df[sessions].abs().mean(axis=1)
    best = df.loc[df.groupby('x_col')['_avg_abs'].idxmax()]
    best = best.sort_values('_avg_abs', ascending=False)

    matrix_data = []
    row_labels = []
    for _, row in best.iterrows():
        vals = [row.get(s, np.nan) for s in sessions]
        matrix_data.append(vals)
        row_labels.append(_short_label(row['x_col'], 25))

    matrix = np.array(matrix_data)

    fig, ax = plt.subplots(figsize=(10, max(6, len(row_labels) * 0.5)))
    im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto', vmin=-0.15, vmax=0.15)

    ax.set_xticks(range(len(session_labels)))
    ax.set_xticklabels(session_labels, fontsize=9)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8)
    ax.set_title('Session IC Heatmap  (best horizon per X feature)', fontsize=11)

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            v = matrix[i, j]
            if not np.isnan(v):
                color = 'white' if abs(v) > 0.10 else 'black'
                ax.text(j, i, f'{v:+.4f}', ha='center', va='center',
                        fontsize=7, color=color)

    fig.colorbar(im, ax=ax, label='IC', shrink=0.8)
    fig.tight_layout()
    return fig


def _empty_fig(msg: str) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.set_title(msg)
    return fig
