// Step 2A: write-factor 的纯函数（类名/模板检测）。
// 新 pipeline 里 .h 生成由 write-factor skill（Claude）做，这里只提供 submit 阶段需要的辅助函数。
// （旧 SDK 的 processWriteFactorInFork 调 claude-agent-sdk，新 pipeline 不用，已去除）

import fs from "node:fs";

export function extractClassNameFromH(hFile) {
  if (!fs.existsSync(hFile)) return null;
  const content = fs.readFileSync(hFile, "utf8");
  const m = content.match(/\bclass\s+([A-Z][A-Za-z0-9_]*)\s*[:{]/);
  return m ? m[1] : null;
}

export function isTemplateClass(hFile) {
  if (!fs.existsSync(hFile)) return true;
  const content = fs.readFileSync(hFile, "utf8");
  return /\btemplate\s*</.test(content);
}
