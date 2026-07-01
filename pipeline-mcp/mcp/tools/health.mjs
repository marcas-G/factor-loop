export const healthSchema = {
  name: "health",
  description: "检查 quant-mcp server 是否存活，返回当前时间戳",
  inputSchema: { type: "object", properties: {} },
};

export async function healthHandler(_input) {
  return { ok: true, ts: new Date().toISOString() };
}
