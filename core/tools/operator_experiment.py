#!/usr/bin/env python3
"""算子增量实验范式 · 一期：干净基底 + 单算子变体 + 配对归因。

范式核心（多轮讨论收敛）：
- 因子 = 基底 + 算子；基底 = 一条信息类型 + 一个经典输出算子，无叠加。
- 算子 = 信息**类型**的一次变换（类型入→类型出），签名固定；具体实参（bid_size/oi 等）是因子的事。
- 实验 = 一次动一个算子，同一样本配对逐日 ΔIC；每步一个算子一个 Δ，链天然可追溯。
- 判决 = 四象限（预测兑现 × ΔIC 变好）+ 三重判据（均值达标 / t 显著 / 逐日符号一致）。

本文件三部分：
1. BASES：干净基底标签（26 维结构，同 coupling_check 标签，可过 check_coupling 自洽）
2. 算子变体生成：在基底上加一个算子 → 完整变体标签 + 类型签名 + 可证伪预测
3. 配对归因：读两个因子的 csv_ic_ts.csv（逐日 IC），对齐 (date,horizon) 差分 → d_t 序列 → 统计
"""
import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from coupling_check import check_coupling


# ============ 1. 干净基底 ============

# Imbalance 基底：一条信息类型（bid/ask 档位向量）+ 一个经典输出算子（差比聚合 → 不平衡）。
# 无差分 / 无标准化 / 无平滑 / 无触发 / 无门控 / 无多路 / 无辅助输入。
IMBALANCE_BASE = {
    "字段": [
        {"name": "bid_size", "type": "向量"},
        {"name": "ask_size", "type": "向量"},
    ],
    "档位选择": "L0最优档",
    "聚合运算": "差比",
    "加权": None,
    "数据源": "单合约",
    "差分": None,
    "标准化方法": None,
    "标准化估计": None,
    "平滑": None,
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": "代数差",
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": None,           # 直接输出原始不平衡比值，最干净
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {},
    "DAG拓扑": {
        "分支数": 1, "对称性": "对称", "各路角色": ["单路"], "辅助输入": [], "合并点": "无（单路）",
    },
}

# Mom 基底：一条信息类型（价格序列）+ 一个经典输出算子（窗口差分 → 动量）。
# 只做"当期价 − 窗口前价"的经典动量，不加平滑/标准化/触发——干净动量。
MOM_BASE = {
    "字段": [
        {"name": "mid_price", "type": "标量"},
    ],
    "档位选择": None,
    "聚合运算": None,
    "加权": None,
    "数据源": "单合约",
    "差分": "窗口差分",
    "标准化方法": None,
    "标准化估计": None,
    "平滑": None,
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": None,
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": None,           # 直接输出窗口动量
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {},
    "DAG拓扑": {
        "分支数": 1, "对称性": "对称", "各路角色": ["单路"], "辅助输入": [], "合并点": "无（单路）",
    },
}

# Activity 基底：一条信息类型（成交量/成交笔数）+ 一个经典输出算子（窗口聚合 → 活跃度）。
# 只做"窗口内成交总量"的经典活跃度，不加比率/标准化——干净活跃度。
ACTIVITY_BASE = {
    "字段": [
        {"name": "total_volume", "type": "累计标量"},
    ],
    "档位选择": None,
    "聚合运算": "窗口求和",
    "加权": None,
    "数据源": "单合约",
    "差分": None,
    "标准化方法": None,
    "标准化估计": None,
    "平滑": None,
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": None,
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": None,           # 直接输出窗口成交活跃度
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {},
    "DAG拓扑": {
        "分支数": 1, "对称性": "对称", "各路角色": ["单路"], "辅助输入": [], "合并点": "无（单路）",
    },
}

# OiChange 基底：一条信息类型（OI 序列）+ 一个经典输出算子（差分 → 持仓变化）。
# 只做"当期 OI − 前值 OI"的经典持仓变化，不加平滑/门控——干净 OI 变化。
OI_CHANGE_BASE = {
    "字段": [
        {"name": "oi", "type": "标量"},
    ],
    "档位选择": None,
    "聚合运算": None,
    "加权": None,
    "数据源": "单合约",
    "差分": "一阶差分",
    "标准化方法": None,
    "标准化估计": None,
    "平滑": None,
    "触发类型": None,
    "spike方向": None,
    "阈值类型": None,
    "关系类型": None,
    "共现条件": None,
    "lead-lag τ方式": None,
    "相关类型": None,
    "lift统计": None,
    "组合运算": None,
    "加权权重": None,
    "输出变换": None,           # 直接输出持仓变化
    "输出门控": None,
    "对齐粒度": None,
    "stale策略": None,
    "对齐方向": None,
    "参数": {},
    "DAG拓扑": {
        "分支数": 1, "对称性": "对称", "各路角色": ["单路"], "辅助输入": [], "合并点": "无（单路）",
    },
}

BASES = {
    "Imbalance": IMBALANCE_BASE,
    "Mom": MOM_BASE,
    "Activity": ACTIVITY_BASE,
    "OiChange": OI_CHANGE_BASE,
}


# ============ 2. 算子定义（签名固定 + 可证伪预测）============

# 每个算子：op_id / 类型签名 / 标签改动 / 可证伪预测（claim-first）。
# 类型签名描述"信息类型怎么变"，不涉及具体实参。
OPERATORS = {
    "diff": {
        "op_type": "transform",
        "signature": "标量序列 → 一阶差分 → 标量序列",
        "label_change": {"差分": "一阶差分"},
        "prediction": {
            "mechanism": "不平衡的水平信号含盘口漂移噪声；差分后保留不平衡的冲击（变化量），瞬时行为更有方向性",
            "condition": "全时段",
            "metric": "逐日 rank IC",
            "direction": "ΔIC > 0（差分后逐日 IC 提升）",
        },
    },
    "smooth_ema": {
        "op_type": "transform",
        "signature": "标量序列 → EMA 平滑 → 标量序列",
        "label_change": {"平滑": "EMA"},
        "prediction": {
            "mechanism": "原始不平衡逐 tick 抖动；EMA 平滑滤掉微观噪声，暴露持续性不平衡",
            "condition": "全时段",
            "metric": "逐日 rank IC",
            "direction": "ΔIC > 0（平滑后逐日 IC 提升）",
        },
    },
    "gate": {
        "op_type": "output",
        "signature": "标量序列 → 事件门控 → 稀疏信号",
        "label_change": {"触发类型": "spike阈值", "spike方向": "单侧正≥θ", "阈值类型": "z-score", "输出门控": "事件门控"},
        "prediction": {
            "mechanism": "不平衡达到极端 z 时才有预测力；门控滤掉平凡时段，信号稀疏但信噪比高",
            "condition": "不平衡 z≥θ 事件期",
            "metric": "事件期条件 rank IC + 稀疏度",
            "direction": "事件期条件 IC > 全样本 IC",
        },
    },
    # ============ 事件信息算子（一期 3 个算子全部作用于"值流"，以下补事件流的时间结构）============
    "ac1": {
        "op_type": "transform",
        "signature": "标量序列 → EWMA lag-1 自相关 → 标量序列",
        "label_change": {"差分": "自相关(EWMA lag1)"},
        "prediction": {
            "mechanism": "库内相关全是跨序列(13个 corr/cov 因子无一是单序列自相关)。lag-1 自相关直接度量信号的记忆结构:AC1<0=Roll 反弹(短期回复),AC1>0=动量延续。输出是二阶时序结构,库内因子输出全是一阶/水平,IC 行为重叠概率最低",
            "condition": "全时段",
            "metric": "逐日 rank IC + 残差 IC 强度",
            "direction": "AC1 显著非零(AG 主力预期 AC1<0,价格有反弹结构),|IC|>0 且与库内因子残差≥0.5",
        },
    },
    "dir_streak": {        "op_type": "transform",
        "signature": "方向事件流 → 同向串结构聚合 → 标量序列",
        "label_change": {
            "字段": [{"name": "trade_side", "type": "事件流"}],
            "触发类型": "序列pattern连续N次",   # tpl10 已有取值，但从未有算子把事件方向流当输入
            "spike方向": "单侧正≥θ",
            "阈值类型": "滚动quantile",
            "输出门控": "事件门控",
        },
        "prediction": {
            "mechanism": "净流(buy−sell)把方向事件坍缩成单一标量，丢失'连续同向攻击'的串结构。同向串长 L 是该方向信息持续注入的指纹：串越长，后续收益越可能沿串方向延续（动量），且比同窗口净流 OFI 的信噪比高——串长对'攻击强度'是超线性加权，净流是线性加权",
            "condition": "同向串长 z≥θ 事件期",
            "metric": "事件期条件 rank IC（对照同窗口净流 OFI 的条件 IC）",
            "direction": "ΔIC > 0：串长信号条件 IC > 净流 OFI 条件 IC",
        },
    },
    "dir_flip": {
        "op_type": "transform",
        "signature": "方向事件流 → 翻转计数频率 → 标量序列",
        "label_change": {
            "字段": [{"name": "trade_side", "type": "事件流"}],
            "触发类型": "符号切换",              # tpl10/tpl11 已有取值，无算子用于事件方向
            "spike方向": "符号切换",
            "输出门控": None,
        },
        "prediction": {
            "mechanism": "方向事件的来回切换频率衡量信息耗竭/多空拉锯：翻转频率骤升 = 单边信息结束、回到均衡；翻转率低且同向串长 = 强趋势。净流 OFI 对'来回扫'免疫（对冲后≈0），翻转频率捕捉净流看不到的拉锯结构",
            "condition": "翻转频率 z 事件期（相对滚动基线）",
            "metric": "翻转后 K 步回复收益 + 条件 rank IC",
            "direction": "翻转率骤升后回复收益显著（|return|>基线），方向无偏",
        },
    },
    "pulse_z": {
        "op_type": "transform",
        "signature": "累计序列 → 周期差分脉冲 → z-score 门控稀疏信号",
        "label_change": {
            "字段": [{"name": "total_volume", "type": "累计标量"}],
            "差分": "事件增量",
            "标准化方法": "z-score",
            "标准化估计": "滚动窗固定N",
            "触发类型": "spike阈值",
            "spike方向": "双侧|x|≥θ",
            "阈值类型": "z-score",
            "输出门控": "事件门控",
        },
        "prediction": {
            "mechanism": "累计水位含历史过程噪声，脉冲（周期 Δvolume）才是当期成交事件强度：大额脉冲 = 大单进场/离场事件。脉冲 z 门控只在大额成交爆发期输出，捕捉'信息注入瞬间'的波动与方向延续，优于对累计水位做门控（水位高不代表当期有事件）",
            "condition": "脉冲 z≥θ 事件期（大额成交爆发）",
            "metric": "事件期波动放大倍数 + 条件 rank IC",
            "direction": "事件期 |ret| 显著放大，且方向由同窗 OFI 决定（条件 IC 符号与 OFI 一致）",
        },
    },
}


def make_variant(base_label, op_id):
    """在基底上加一个算子 → 完整变体标签。其余维度锁死，仅算子维度变。"""
    op = OPERATORS[op_id]
    variant = json.loads(json.dumps(base_label))
    variant.update(op["label_change"])
    # 校验：变体标签必须自洽（连带修正留给 auto_fix，但这里应天然自洽）
    violations = check_coupling(variant)
    return variant, violations


def list_applicable(base_label):
    """自动检测：基底上可用哪些算子（一期简单规则：全部可用，二期按类型签名/applicability 判定）。"""
    return list(OPERATORS.keys())


# ============ 3. 配对归因（读 csv_ic_ts.csv，逐日配对差分）============

CSV_IC_COLUMNS = ["date", "factor", "x_col", "horizon", "y_col", "rank_ic", "pearson_day"]


def read_csv_ic(path):
    """读 csv_ic_ts.csv → {(date, horizon, x_col): rank_ic}。

    key 含 x_col：主力(X.SHFE-AG)与次主力(X.SHFE-AG@1)特征共用同一 y_col，
    不加 x_col 时 @1 行会覆盖主力行，配对归因会配到错误合约。
    """
    import csv as _csv
    rows = {}
    with open(path, newline="") as f:
        reader = _csv.DictReader(f)
        for r in reader:
            date = r.get("date") or r.get("Date")
            h = r.get("horizon")
            ic = r.get("rank_ic")
            if not all([date, h, ic]):
                continue
            # horizon 形如 "@1" / "1" / "60"
            h_num = re.sub(r"[^\d]", "", str(h))
            if not h_num:
                continue
            xcol = r.get("x_col") or r.get("factor") or ""
            # 规约成合约前缀：X.SHFE-AG@sqy0_xxx → X.SHFE-AG；X.SHFE-AG@1@sqy0_xxx → X.SHFE-AG@1
            m = re.match(r"(X\.[A-Z]+-[A-Z]+(?:@\d+)?)", xcol)
            contract = m.group(1) if m else xcol
            rows[(date, int(h_num), contract)] = float(ic)
    return rows


def paired_diff(base_path, variant_path, min_days=3):
    """配对逐日差分：对齐 (date,horizon,y_col)，d_t = IC_variant − IC_base。
    返回逐日差分序列（按 horizon 分组的 dict）+ 汇总统计。"""
    base = read_csv_ic(base_path)
    var = read_csv_ic(variant_path)
    keys = sorted(set(base) & set(var))
    if len(keys) < min_days:
        return {"ok": False, "error": f"共享样本不足: {len(keys)} < {min_days}"}

    by_h = {}
    for k in keys:
        date, h, y = k
        by_h.setdefault(h, {"dates": [], "d": []}).get("dates").append(date)
        by_h[h]["d"].append(var[k] - base[k])

    summary = {}
    for h, rec in by_h.items():
        d = rec["d"]
        n = len(d)
        mean = sum(d) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
        t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
        pos = sum(1 for x in d if x > 0)
        sign_consistency = pos / n
        summary[h] = {
            "n": n,
            "mean_dic": round(mean, 6),
            "std_dic": round(sd, 6),
            "t_stat": round(t, 4),
            "p_value": round(2 * _t_sf(abs(t), n - 1), 4) if n > 1 else None,
            "sign_consistency": round(sign_consistency, 4),
        }
    return {"ok": True, "n_shared": len(keys), "by_horizon": summary}


def _t_sf(t, df):
    """t 分布生存函数（双尾）。无 scipy 时用正态近似 + 大 df 修正。"""
    try:
        from scipy.stats import t as _t
        return float(_t.sf(t, df))
    except ImportError:
        return _norm_sf(t)


def _norm_sf(z):
    """标准正态生存函数（scipy 不可用时的近似，df 大时够用）。"""
    return 0.5 * math.erfc(z / math.sqrt(2))


def verdict_from_summary(summary, mean_floor=0.01, alpha=0.05, sign_floor=0.6):
    """三重判据：均值达标 + t 显著 + 逐日符号一致，三过才算有效。
    返回每 horizon 的 (verdict, reasons)。"""
    out = {}
    for h, s in summary.items():
        checks = []
        ok = True
        if abs(s["mean_dic"]) < mean_floor:
            ok = False
            checks.append(f"均值|ΔIC|={abs(s['mean_dic']):.4f}<{mean_floor}")
        if s["p_value"] is not None and s["p_value"] > alpha:
            ok = False
            checks.append(f"t 不显著(p={s['p_value']:.3f}≥{alpha})")
        if s["sign_consistency"] < sign_floor:
            ok = False
            checks.append(f"符号一致率={s['sign_consistency']:.2f}<{sign_floor}")
        out[h] = {"ok": ok, "reasons": checks if checks else ["三重判据全过"]}
    return out


# ============ CLI ============

def main():
    ap = argparse.ArgumentParser(description="算子增量实验：定义基底/变体 + 配对归因")
    ap.add_argument("--base", default="Imbalance", help="基底名（BASES 键）")
    ap.add_argument("--list-operators", action="store_true", help="列基底适用算子")
    ap.add_argument("--variant-json", help="输出某算子的变体标签 JSON（如 diff）")
    ap.add_argument("--paired-diff", nargs=2, metavar=("BASE_CSV", "VARIANT_CSV"), help="配对逐日 ΔIC 归因")
    args = ap.parse_args()

    if args.list_operators:
        base = BASES[args.base]
        print(json.dumps({"base": args.base, "applicable_operators": list_applicable(base)}, ensure_ascii=False, indent=2))
        return

    if args.variant_json:
        variant, violations = make_variant(BASES[args.base], args.variant_json)
        out = {
            "base": args.base,
            "op_id": args.variant_json,
            "op": OPERATORS[args.variant_json],
            "label": variant,
            "coupling_violations": violations,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return

    if args.paired_diff:
        result = paired_diff(args.paired_diff[0], args.paired_diff[1])
        if not result.get("ok"):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        v = verdict_from_summary(result["by_horizon"])
        result["verdict"] = v
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
