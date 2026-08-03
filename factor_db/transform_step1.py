#!/usr/bin/env python3
"""research-loop Step 1（变换引擎版）：父因子 → N 个候选。

替代原 Step 1（hypothesize 图推理 + brainstorm）。跑 transform_flow N 次
（不同 seed），产 N 个候选的标签层产出（变换指令 + 新标签 + 参数提示）。

主 agent 拿到候选后：
  1. LLM 按变换指令改写父因子描述 → 新因子描述
  2. 组织成 brainstorm factors 格式（name/formula/intuition/tags/params）
  3. persist_candidates 存 state
  4. 交 run-factor-agent（Step 2: write/submit/check）

输入: 父因子标签 + name + N
输出: N 个候选 JSON（标签层产出，供主 agent LLM 改写）
"""
import json
import argparse
from transform_flow import run_flow, LowDiscrepancyRNG


# dead_end 原因 → 对症变换维度（优先变换这些维度, 针对性救活）
DEAD_END_FIX = {
    "饱和族冗余": ["字段", "关系类型", "数据源"],       # 换基底逃饱和族
    "IC弱/冗余": ["字段", "关系类型", "差分"],           # 换机制/基底
    "信号稀疏": ["触发类型", "参数", "spike方向"],       # 调触发/阈值密度
    "rank虚高": ["输出变换"],                            # 换output（rank→tanh/z）
    "忠实度/泄漏": ["输出门控", "输出变换"],             # 修output门控
}


def gen_candidates(parent_label, parent_name, n=3, n_transforms=2, seed_start=0,
                   low_discrepancy=False, temperature=1.0, prefer_bonus=1.0):
    """跑 transform_flow N 次，产 N 候选。prefer_dims 据 dead_end_reason 对症选变换。

    low_discrepancy: 实测对本系统无益, 默认关闭, 保留开关仅供实验:
      - 维度覆盖均匀度: 与独立 seed 几乎相同(熵比 0.89 vs 0.90)——
        互斥约束 + Softmax 已把维度层面铺匀, 低差异无边际收益。
      - 组合去重率: 独立 seed 反而更优(100% vs 94%)——
        离散组合空间里「每次独立随机」在去重上本质最优; 低差异的「均匀」
        优势只在连续数值积分场景成立, 生搬到这里反而引入结构化重复。
    temperature / prefer_bonus: Softmax 旋钮, 是本次改动真正有价值的部分。
    """
    # 读 dead_end_reason → prefer_dims（对症变换维度, 非纯随机）
    dead_end_reason = parent_label.get("_dead_end_reason")
    prefer_dims = DEAD_END_FIX.get(dead_end_reason) if dead_end_reason else None
    # 共享一条低差异流（整批铺匀的关键）; None → 走老逻辑（每候选独立 seed）
    rng = LowDiscrepancyRNG(seed=seed_start) if low_discrepancy else None
    candidates = []
    seed = seed_start
    while len(candidates) < n:
        commands, new_label, fixes, param_hints, ok = run_flow(
            parent_label, n_transforms=n_transforms,
            seed=None if low_discrepancy else seed,
            prefer_dims=prefer_dims, rng=rng,
            temperature=temperature, prefer_bonus=prefer_bonus,
        )
        seed += 1
        if not ok:
            continue
        candidates.append({
            "candidate_idx": len(candidates),
            "seed": seed - 1,
            "parent": parent_name,
            "commands": commands,        # 变换指令（LLM 改写描述用）
            "new_label": new_label,      # 新标签（组织 factor JSON 用）
            "fixes": fixes,              # 连带修正记录
            "param_hints": param_hints,  # 参数连带提示（write-factor 注意）
        })
    return candidates


def gen_name_hint(new_label):
    """从变换标签提取关键维度, 作为 LLM 起描述性名的语义提示(替代父名+Tidx)。"""
    dims = []
    for key in ["关系类型", "差分", "字段", "输出变换", "lead-lag τ方式", "触发类型", "平滑"]:
        v = new_label.get(key)
        if not v:
            continue
        if isinstance(v, list):
            v = "+".join(f["name"] if isinstance(f, dict) else str(f) for f in v)
        dims.append(f"{key}={v}")
    return "; ".join(dims[:4])


def label_to_factor_skeleton(new_label, parent_name, candidate_idx):
    """从新标签推导 factor JSON 骨架（name_hint/tags/params）。
    name/formula/intuition 都留主 agent LLM 填——name 据 commands 起
    描述性 PascalCase 名（不复用父因子名, 体现变换本身）。"""
    # name: 留空, 由 research-loop LLM 据 commands + name_hint 起（不再父名+Tidx）
    name = None

    # tags: 从标签推导
    tags = []
    field_names = [f["name"] if isinstance(f, dict) else f for f in new_label.get("字段", [])]
    if len(field_names) >= 2:
        tags.append("cross_field")
    if new_label.get("关系类型"):
        tags.append("event_sync")
        tags.append(str(new_label["关系类型"]).replace("条件概率", ""))
    if new_label.get("触发类型"):
        tags.append("event_driven")
    if new_label.get("输出门控"):
        tags.append("gated")
    # 去重 + 限长
    tags = list(dict.fromkeys(tags))[:6]

    # params: 从标签的参数 + 模板默认
    params = dict(new_label.get("参数", {}))

    return {
        "name": name,
        "name_hint": gen_name_hint(new_label),
        "tags": tags,
        "params": params,
        "categories": ["AG", "CU", "AU", "AL", "NI"],
        # name / formula / intuition 留空, 主 agent LLM 按 commands 改写填
        "formula": None,
        "intuition": None,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", default=None, help="父因子名(不指定则从PARENT_POOL随机选)")
    ap.add_argument("--n", type=int, default=3, help="候选数")
    ap.add_argument("--n-transforms", type=int, default=2, help="每候选变换数")
    ap.add_argument("--seed-start", type=int, default=100)
    ap.add_argument("--low-discrepancy", action="store_true",
                    help="开启低差异采样(共享 Sobol 流)。默认关: 实测对离散组合去重无益")
    ap.add_argument("--temperature", type=float, default=1.0,
                    help="Softmax 温度: 小=偏利用(prefer_dims), 大=偏随机")
    ap.add_argument("--prefer-bonus", type=float, default=1.0,
                    help="prefer_dims 维度加分幅度")
    args = ap.parse_args()

    # 父因子: 从 PARENT_POOL 选(--parent 指定 或 随机)
    from coupling_check import PARENT_POOL
    import random as _random
    if args.parent and args.parent in PARENT_POOL:
        parent_name = args.parent
    elif args.parent:
        print(f"✗ 父因子 {args.parent} 不在 PARENT_POOL: {list(PARENT_POOL.keys())}", file=__import__("sys").stderr)
        __import__("sys").exit(1)
    else:
        parent_name = _random.choice(list(PARENT_POOL.keys()))
    parent_label = PARENT_POOL[parent_name]
    print(f"# 父因子: {parent_name}（PARENT_POOL 共 {len(PARENT_POOL)} 个）", file=__import__("sys").stderr)

    candidates = gen_candidates(
        parent_label, parent_name,
        n=args.n, n_transforms=args.n_transforms, seed_start=args.seed_start,
        low_discrepancy=args.low_discrepancy,
        temperature=args.temperature, prefer_bonus=args.prefer_bonus,
    )

    # 产出：每个候选 = 标签层产出 + factor 骨架（formula/intuition 待 LLM 填）
    output = {
        "parent": parent_name,
        "n_candidates": len(candidates),
        "candidates": [],
    }
    for c in candidates:
        skeleton = label_to_factor_skeleton(c["new_label"], parent_name, c["candidate_idx"])
        output["candidates"].append({
            **c,
            "factor_skeleton": skeleton,
        })

    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
