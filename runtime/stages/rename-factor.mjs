// 因子 .h 换名工具：DAG 缓存陷阱自愈用。
// 同 xname/features 签名重提交不触发平台 DAG 重算（命中缓存）→ 换 xname 强制重跑。
// 本模块：PascalCase↔snake_case 转换 + 生成唯一新名 + 复制 .h 改名（class/xname frontmatter/names stem）。

import fs from "node:fs";
import path from "node:path";
import { extractClassNameFromH } from "./write-factor.mjs";

// PascalCase → snake_case。含缩写词处理：
//   BPDiff    → bp_diff   （缩写 BP + Diff，规则1 拆边界）
//   BHHI      → bhhi      （全大写缩写不拆，无 [A-Z][a-z] 锚点）
//   TradeRunVolAccel → trade_run_vol_accel
//   TradeRunVolAccel2 → trade_run_vol_accel2
export function toSnake(s) {
  return s
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2") // 缩写词边界: BPDiff→BP_Diff
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")     // 常规: eR→e_R
    .toLowerCase();
}

// 生成唯一新 xname：剥离已有数字尾缀后递增（OldName→OldName2→OldName3...）。
// 跳过 factors/ 目录已存在 .h + db 已登记（existsInDb 可选，返回 bool）。
export function nextUniqueXname(oldXname, factorsDir, existsInDb = null) {
  const base = (oldXname.replace(/\d+$/, "") || oldXname);
  let n = 2;
  while (n < 1000) {
    const candidate = `${base}${n}`;
    const fileExists = factorsDir ? fs.existsSync(path.join(factorsDir, `${candidate}.h`)) : false;
    const dbExists = existsInDb ? existsInDb(candidate) : false;
    if (!fileExists && !dbExists) return candidate;
    n++;
  }
  throw new Error(`nextUniqueXname: ${base}${n}+ 全被占用，换名失败`);
}

// 复制 .h 并改名：class 名 + xname/class_name frontmatter（PascalCase）+ names() stem（snake_case）。
// 假设 names() stem = toSnake(xname)（write-factor 标准规则；非标准 stem 不会被命中，但 class/frontmatter 仍改对）。
// 返回 { newXname, newFile }。改名后用 extractClassNameFromH 校验 class 名，残留则抛错。
export function renameFactorH(oldXname, oldFile, factorsDir, existsInDb = null) {
  if (!fs.existsSync(oldFile)) {
    throw new Error(`renameFactorH: 源 .h 不存在: ${oldFile}`);
  }
  const newXname = nextUniqueXname(oldXname, factorsDir, existsInDb);
  const oldSnake = toSnake(oldXname);
  const newSnake = toSnake(newXname);
  let content = fs.readFileSync(oldFile, "utf8");
  // 先 snake（names stem + 任意 snake 出现），再 Pascal（class/frontmatter）。两者字符集不重叠（_ vs 大写），顺序安全。
  if (oldSnake && oldSnake !== newSnake) {
    content = content.split(oldSnake).join(newSnake);
  }
  if (oldXname !== newXname) {
    content = content.split(oldXname).join(newXname);
  }
  const newFile = path.join(factorsDir, `${newXname}.h`);
  fs.writeFileSync(newFile, content);
  const newClass = extractClassNameFromH(newFile);
  if (newClass !== newXname) {
    throw new Error(`renameFactorH: 改名后 class="${newClass}" 期望="${newXname}"（旧 token 残留或 .h 结构非标准）`);
  }
  return { newXname, newFile };
}
