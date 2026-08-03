#!/usr/bin/env python3
"""变换流程：输入父因子（描述+标签），输出新因子（新描述+新标签）。

标签层规则化（适用性/选变换/连带检查/修正），LLM 改写描述（主 agent 执行）。

流程:
  1. 验证父标签自洽（check_coupling）
  2. 按标签筛适用变换 + 随机选一组（互斥：同维度只选一个）
  3. 应用变换到标签
  4. 连带自动修正（auto_fix_coupling）
  5. 验证新标签自洽（check_coupling）
  6. 输出变换指令 + 新标签（交 LLM 改写描述）
"""
import json
import math
import random
from pathlib import Path
from coupling_check import check_coupling, auto_fix_coupling, param_coupling_hints, ADD_OI_LIFT_BIDASK

NODES = json.load(open(Path(__file__).parent / "transform_nodes.json", encoding="utf-8"))["nodes"]


class LowDiscrepancyRNG:
    """低差异随机源: random.random() 接口, 可无缝替换 random 模块。

    用途: 让「多次 pick_transforms 共享一条低差异流」, 使整批候选在变换空间铺匀,
    减少「连续 int seed → 各自独立随机流 → 扎堆」的覆盖病。
    有 scipy → Sobol 序列; 无 scipy → 黄金比 Kronecker 序列(同样低差异, 无依赖)。
    """

    def __init__(self, seed=0):
        self._seed = seed
        self._i = 0
        try:
            from scipy.stats import qmc
            self._sobol = qmc.Sobol(d=1, seed=seed)
            self._mode = "sobol"
        except ImportError:
            self._sobol = None
            self._mode = "kronecker"

    def random(self):
        """返回 [0, 1) 的下一个低差异点。"""
        self._i += 1
        if self._mode == "sobol":
            return float(self._sobol.random(1)[0, 0])
        # 黄金比 Kronecker 序列: (seed + i·φ) mod 1
        phi = (math.sqrt(5) - 1) / 2
        return (self._seed + self._i * phi) % 1.0


def pick_candidates(label):
    """根据标签筛所有适用变换候选。返回 [(维度, 操作, 新值), ...]。"""
    candidates = []
    for node in NODES:
        dim = node["dimension"]
        ntype = node["type"]

        # special（参数/DAG拓扑）：所有操作都候选
        if ntype == "special":
            for op in node.get("operations", []):
                candidates.append((dim, "special", op))
            continue

        values = node.get("values", [])
        current = label.get(dim)

        # swap：标签有该维度（非 null）→ 可换值（排除当前）
        if ntype in ("swap", "both"):
            if dim == "字段" and isinstance(current, list):
                # 字段是 list, swap 排除已在 list 的值(去重, 避免换后重复)
                existing_names = {f["name"] if isinstance(f, dict) else f for f in current}
                for v in values:
                    if v not in existing_names:
                        candidates.append((dim, "swap", v))
            elif current is not None and current != [] and current != {}:
                # 共现条件是 dict，特殊处理
                cur_check = current if not isinstance(current, dict) else tuple(sorted(current.items()))
                for v in values:
                    if v != cur_check:
                        candidates.append((dim, "swap", v))

        # add_remove / both：启用新值（排除当前已有的, 避免重复启用）
        if ntype in ("add_remove", "both"):
            for v in values:
                if current is None or v != current:
                    candidates.append((dim, "enable", v))

    return candidates


def pick_transforms(label, n=3, seed=None, prefer_dims=None,
                    temperature=1.0, prefer_bonus=1.0, rng=None):
    """Softmax 温度采样选 n 个变换（互斥：同维度只选一个）。

    随机源由 rng 注入:
      rng=None（默认）+ seed → 走全局 random（老逻辑, 向后兼容）
      rng=LowDiscrepancyRNG(...) → 低差异采样（整批铺匀）

    temperature = 聪明↔随机 旋钮:
      T→0  纯利用: 只选 prefer_dims, 退化为原硬排序
      T→∞  纯随机: 退化为原 shuffle
      中间  高分更可能中, 但保留随机 ← "聪明又随机"
    prefer_bonus = prefer_dims 维度的加分幅度（偏好强度）。
    prefer_dims=None → 所有人分相等, 等价均匀随机（向后兼容）。
    """
    if rng is None:
        if seed is not None:
            random.seed(seed)
        rng = random
    pool = list(pick_candidates(label))
    if not pool:
        return []

    def score(c):
        return prefer_bonus if (prefer_dims and c[0] in prefer_dims) else 0.0

    picked, picked_dims = [], set()
    while pool and len(picked) < n:
        # softmax 权重（数值稳定）: w = exp((score - max) / T)
        scores = [score(c) for c in pool]
        mx = max(scores)
        weights = [math.exp((s - mx) / temperature) for s in scores]
        total = sum(weights)
        # 轮盘赌按权重抽一个（随机源 = rng）
        r = rng.random() * total
        acc, idx = 0.0, 0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                idx = i
                break
        chosen = pool[idx]
        picked.append(chosen)
        picked_dims.add(chosen[0])
        pool = [c for c in pool if c[0] != chosen[0]]  # 互斥: 移除同维度
    return picked


def apply_transforms(label, transforms):
    """应用变换到标签。返回 (新标签, 变换指令列表)。"""
    new_label = json.loads(json.dumps(label))  # deep copy
    commands = []
    for dim, op, val in transforms:
        if op == "swap":
            # 字段是 list, 换其中一个元素(不是整个 list 换成单值)
            if dim == "字段" and isinstance(new_label.get(dim), list) and new_label[dim]:
                old_list = new_label[dim]
                old_first = old_list[0]
                old_name = old_first["name"] if isinstance(old_first, dict) else str(old_first)
                vec_fields = {"bid_size", "ask_size"}
                new_type = "向量" if val in vec_fields else "标量"
                old_list[0] = {"name": val, "type": new_type}
                commands.append(f"把字段 {old_name} 换成 {val}")
            else:
                old = new_label.get(dim)
                new_label[dim] = val
                commands.append(f"把{dim}从 {old} 换成 {val}")
        elif op == "enable":
            new_label[dim] = val
            commands.append(f"启用 {val}（{dim}）")
        elif op == "special":
            commands.append(val)
            # special 是描述性操作（参数/拓扑），标签层不直接改
    return new_label, commands


def run_flow(parent_label, n_transforms=3, seed=None, prefer_dims=None,
             rng=None, temperature=1.0, prefer_bonus=1.0):
    """完整变换流程（标签层）。

    返回 (变换指令, 新标签, 连带修正, 参数提示, 成功?)。
    rng/temperature/prefer_bonus 透传给 pick_transforms:
      rng=None + seed → 老逻辑（向后兼容）; rng=LowDiscrepancyRNG → 低差异采样。
    """
    # 1. 验证父标签
    violations = check_coupling(parent_label)
    if violations:
        return None, None, None, f"父标签不自洽: {violations}", False

    # 2. 选变换（prefer_dims 优先: 对症维度）
    transforms = pick_transforms(parent_label, n_transforms,
                                 seed=seed, prefer_dims=prefer_dims,
                                 rng=rng, temperature=temperature, prefer_bonus=prefer_bonus)

    # 3. 应用
    new_label, commands = apply_transforms(parent_label, transforms)

    # 4. 连带自动修正
    new_label, fixes = auto_fix_coupling(new_label)

    # 5. 验证新标签
    violations = check_coupling(new_label)
    if violations:
        return commands, new_label, None, f"新标签不自洽(连带修正后仍违反): {violations}", False

    # 6. 参数连带提示（哪些参数因维度变化需重定）
    param_hints = param_coupling_hints(parent_label, new_label)

    return commands, new_label, fixes, param_hints, True


def format_diff(old_label, new_label):
    """格式化标签变化。"""
    lines = []
    for dim in new_label:
        old_v = old_label.get(dim)
        new_v = new_label[dim]
        if old_v != new_v:
            lines.append(f"  {dim}: {old_v} → {new_v}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=" * 60)
    print("变换流程测试: AddOiLiftBidAsk (seed=10)")
    print("=" * 60)

    commands, new_label, fixes, param_hints, ok = run_flow(ADD_OI_LIFT_BIDASK, n_transforms=2, seed=10)

    if not ok:
        print(f"✗ 流程失败: {param_hints}")
    else:
        print("选中的变换指令:")
        for i, cmd in enumerate(commands, 1):
            print(f"  {i}. {cmd}")
        print()
        if fixes:
            print("连带自动修正:")
            for f in fixes:
                print(f"  {f}")
            print()
        if param_hints:
            print("参数连带提示（需重定的参数）:")
            for h in param_hints:
                print(f"  {h}")
            print()
        print("标签变化:")
        print(format_diff(ADD_OI_LIFT_BIDASK, new_label))
        print()
        print("✓ 新标签自洽。参数提示交 LLM/write-factor 注意。")

    # 多次随机测试
    print()
    print("=" * 60)
    print("多次随机变换测试（验证稳定性）")
    print("=" * 60)
    success = 0
    fail = 0
    for s in range(20):
        commands, new_label, fixes, param_hints, ok = run_flow(ADD_OI_LIFT_BIDASK, n_transforms=3, seed=s)
        if ok:
            success += 1
        else:
            fail += 1
            print(f"  seed={s} 失败: {param_hints}")
    print(f"20 次随机变换: {success} 成功, {fail} 失败")
