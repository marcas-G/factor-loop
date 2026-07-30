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
import random
from pathlib import Path
from coupling_check import check_coupling, auto_fix_coupling, param_coupling_hints, ADD_OI_LIFT_BIDASK

NODES = json.load(open(Path(__file__).parent / "transform_nodes.json", encoding="utf-8"))["nodes"]


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


def pick_transforms(label, n=3, seed=None, prefer_dims=None):
    """随机选 n 个变换（互斥：同维度只选一个）。prefer_dims 优先（对症维度排前）。"""
    if seed is not None:
        random.seed(seed)
    candidates = pick_candidates(label)
    random.shuffle(candidates)
    # prefer_dims 优先（对症维度排前, 内部保持shuffle随机）
    if prefer_dims:
        candidates.sort(key=lambda c: 0 if c[0] in prefer_dims else 1)
    picked = []
    picked_dims = set()
    for dim, op, val in candidates:
        if dim not in picked_dims:
            picked.append((dim, op, val))
            picked_dims.add(dim)
        if len(picked) >= n:
            break
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


def run_flow(parent_label, n_transforms=3, seed=None, prefer_dims=None):
    """完整变换流程（标签层）。

    返回 (变换指令, 新标签, 连带修正, 参数提示, 成功?)。
    """
    # 1. 验证父标签
    violations = check_coupling(parent_label)
    if violations:
        return None, None, None, f"父标签不自洽: {violations}", False

    # 2. 选变换（prefer_dims 优先: 对症维度）
    transforms = pick_transforms(parent_label, n_transforms, seed=seed, prefer_dims=prefer_dims)

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
