"""Phase 3 v1 —— Representation Challenge Investigation。

v0 证明"LLM 能提出值得调查的表示质疑";v1 证明"这些质疑能否被真正的数据实验
支持或反驳"。核心对象链:
  Representation Challenge → Counterexample Test Contract → Probe → Evidence → Verdict

v1 硬禁令: 不发明算子 / 不优化 alpha / 每 case ≤2 probe(防 adaptive mining)。
成熟度: v0=Generation, v1=Investigation, v2=Invention。
"""
