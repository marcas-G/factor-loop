---
name: submit
description: Use when user wants to prepare factor submission packages — create submission folders, rename class/xname, add comments. Triggers: "提交因子", "打包因子", "准备提交", "submit factors", "生成提交文件夹".
---

# 因子提交打包

将因子 .h 文件打包为 submission 文件夹，完成报告生成、重命名、注释。

## 流程

给定一个目录（默认当前工作目录），其中包含若干 .h 因子文件。

### Step 1: 生成 HTML 实验报告

对每个因子，使用 `html-report-gen` skill 生成报告。如果因子没有 eval_output 数据，跳过此步。

报告放在对应的 submission 文件夹中（Step 2 之后）。

### Step 2: 创建 submission 文件夹并复制文件

对目录中每个因子 .h 文件：
1. 创建 `submissionN/` 文件夹（N 从 0 递增）
2. 将 .h 文件复制到对应文件夹中

```
todolist/
  factor_a.h
  factor_b.h
  → submission0/factor_a.h
  → submission1/factor_b.h
```

### Step 3: 修改 class 名称

在复制的文件中，将原始 class 名替换为：

```
Intern2026_Qiyu_Shen_{YYYYMMDD}_submit_{N}
```

- `{YYYYMMDD}` = 当天日期
- `{N}` = submission 文件夹编号

用 `sed` 或 Edit 工具替换。替换前先识别原始 class 名（`class Xxx : public FeedIndicator` 或 `class Xxx<...> : public FeedIndicator`）。

### Step 4: 修改 xname 输出名

在 `names()` 函数中，给每个输出名加后缀 `_{YYYYMMDD}_{N}`：

**模板类（有 template 参数拼接的）：** 在已有名字后插入日期和编号：
```cpp
// 原: "oi_wt_price_" + std::to_string(WindowSize)
// 改: "oi_wt_price_20260522_0_" + std::to_string(WindowSize)
```

**非模板类（字符串字面量）：** 直接在字符串中加后缀：
```cpp
// 原: "oi_corr_vd", "oi_corr_cms"
// 改: "oi_corr_vd_20260522_1", "oi_corr_cms_20260522_1"
```

### Step 5: 添加原名注释

在 class 声明行末尾加 `//` 注释：

```cpp
class Intern2026_Qiyu_Shen_20260522_submit_0 : public FeedIndicator { // OIVwapSplit
```

## 检测模板类

替换完成后检查 class 声明上方是否有 `template <...>` 行：
- 有 → 提交时 --features 参数需要加 `<>`
- 无 → 不加

## 注意事项

- 只修改复制到 submissionN/ 中的副本，不修改原始 .h 文件
- 如果文件中有辅助类（helper class），不要修改它们
- N 的顺序按文件在目录中出现的顺序决定
