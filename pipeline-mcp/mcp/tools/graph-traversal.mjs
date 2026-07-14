// 组 7: 知识图遍历/读写工具（graph-engine 推理引擎用）。
//
// 分层知识图：AXIOM(axioms) → DERIVED/HYPOTHESIS(ideas) → EVIDENCE/REFUTATION(lessons/factors/observe_outputs)。
// graph_edges 跨表软引用。本组工具供 graph-engine skill / graph-reasoner-agent 读写图。
//
// 读类：query_contradictions(解矛盾输入) / get_subgraph(填链输入) / neighborhood(正交输入)
//       / find_refutation_clusters(归纳输入) / graph_stats(停止条件)
// 写类：add_graph_node / add_graph_edges / mark_contradiction_resolved

import * as factorDb from "../../lib/factor-db.mjs";

const EDGE_TYPES = [
  "CONTRADICTS", "DERIVES_FROM", "INSTANTIATES", "SPECIALIZES", "ORTHOGONAL_TO", "SUPPORTS", "REFUTES", "BOUNDS",
];
const NODE_TABLES = ["axioms", "ideas", "factors", "lessons", "observe_outputs"];

export const queryContradictionsSchema = {
  name: "query_contradictions",
  description:
    "查 CONTRADICTS 边（推理燃料）。resolved=false（默认）返回未解矛盾：observe 实测 vs axiom 理论预期。resolve_contradiction 操作的输入。",
  inputSchema: {
    type: "object",
    properties: {
      resolved: { type: "boolean", default: false, description: "false=未解矛盾（默认），true=已解" },
      axiom_code: { type: "string", description: "可选，限定某公理（如 roll_bounce）" },
      limit: { type: "number", default: 5 },
    },
  },
};
export async function queryContradictionsHandler(args = {}) {
  return factorDb.queryContradictions({
    resolved: args.resolved ?? false,
    axiom_code: args.axiom_code ?? null,
    limit: args.limit ?? 5,
  });
}

export const getSubgraphSchema = {
  name: "get_subgraph",
  description:
    "取以某节点为中心、depth 跳内的子图（节点+边，BFS）。fill_chain_gap / orthogonal_branch 的输入。返回跨表 join 的节点全字段。",
  inputSchema: {
    type: "object",
    required: ["table", "node_id"],
    properties: {
      table: { type: "string", enum: NODE_TABLES },
      node_id: { type: "string", description: "节点 id（factors 传 xname，其余传数字 id 字符串）" },
      depth: { type: "number", default: 2 },
      edge_types: { type: "array", items: { type: "string", enum: EDGE_TYPES } },
      limit: { type: "number", default: 200 },
    },
  },
};
export async function getSubgraphHandler(args = {}) {
  return factorDb.getSubgraph({
    table: args.table, node_id: args.node_id, depth: args.depth ?? 2,
    edge_types: args.edge_types ?? null, limit: args.limit ?? 200,
  });
}

export const neighborhoodSchema = {
  name: "neighborhood",
  description:
    "取某节点 1 跳邻居（比 get_subgraph 轻）。orthogonal_branch 先用它看因子实现群。direction: out/in/both。",
  inputSchema: {
    type: "object",
    required: ["table", "node_id"],
    properties: {
      table: { type: "string", enum: NODE_TABLES },
      node_id: { type: "string" },
      edge_types: { type: "array", items: { type: "string", enum: EDGE_TYPES } },
      direction: { type: "string", enum: ["out", "in", "both"], default: "both" },
      limit: { type: "number", default: 10 },
    },
  },
};
export async function neighborhoodHandler(args = {}) {
  return factorDb.neighborhood({
    table: args.table, node_id: args.node_id, edge_types: args.edge_types ?? null,
    direction: args.direction ?? "both", limit: args.limit ?? 10,
  });
}

export const findRefutationClustersSchema = {
  name: "find_refutation_clusters",
  description:
    "找 REFUTES/SUPPORTS 边指向同一目标的聚簇（3+ 反例指向同一 axiom/idea）。generalize_from_refutation 操作的输入。",
  inputSchema: {
    type: "object",
    properties: {
      target_table: { type: "string", enum: ["axioms", "ideas"], description: "可选，限定目标层" },
      target_id: { type: "string", description: "可选，限定某具体节点" },
      min_size: { type: "number", default: 3, description: "最小反例数" },
      limit: { type: "number", default: 5 },
    },
  },
};
export async function findRefutationClustersHandler(args = {}) {
  return factorDb.findRefutationClusters({
    target_table: args.target_table ?? null, target_id: args.target_id ?? null,
    min_size: args.min_size ?? 3, limit: args.limit ?? 5,
  });
}

export const graphStatsSchema = {
  name: "graph_stats",
  description: "图统计：各层节点数、各边类型数、未解矛盾数。graph-engine 选操作优先级 / 自转循环停止条件用。",
  inputSchema: { type: "object", properties: {} },
};
export async function graphStatsHandler() {
  return factorDb.graphStats();
}

export const addGraphNodeSchema = {
  name: "add_graph_node",
  description:
    "写新节点到图。table='axioms'→公理；table='ideas'→带 argument_chain/necessity_grade/node_layer 的假设。返回新 id。",
  inputSchema: {
    type: "object",
    required: ["table", "data"],
    properties: {
      table: { type: "string", enum: ["axioms", "ideas"] },
      data: {
        type: "object",
        description:
          "axioms: {code,category,statement,formal_form?,expected_signature?,source?,falsifiable?}；" +
          "ideas: {text,argument_chain?,necessity_grade?,node_layer?('DERIVED'|'HYPOTHESIS'),parent_idea_id?}",
      },
    },
  },
};
export async function addGraphNodeHandler({ table, data }) {
  return { id: factorDb.addGraphNode({ table, data }) };
}

export const addGraphEdgesSchema = {
  name: "add_graph_edges",
  description:
    "批量写图边（幂等）。graph-reasoner 产出新边后调用。每条 {from_table,from_id,to_table,to_id,edge_type,weight?,properties?}。",
  inputSchema: {
    type: "object",
    required: ["edges"],
    properties: {
      edges: {
        type: "array",
        items: {
          type: "object",
          required: ["from_table", "from_id", "to_table", "to_id", "edge_type"],
          properties: {
            from_table: { type: "string" }, from_id: { type: "string" },
            to_table: { type: "string" }, to_id: { type: "string" },
            edge_type: { type: "string", enum: EDGE_TYPES },
            weight: { type: "number" }, properties: { type: "object" },
          },
        },
      },
    },
  },
}
export async function addGraphEdgesHandler({ edges }) {
  const ids = [];
  for (const e of edges || []) ids.push(factorDb.addGraphEdge(e));
  return { edge_ids: ids };
}

export const markContradictionResolvedSchema = {
  name: "mark_contradiction_resolved",
  description:
    "标记某 CONTRADICTS 边已由某 idea 解决（properties 加 resolved_by）。resolve_contradiction 产 idea 过 reviewer 后调用。",
  inputSchema: {
    type: "object",
    required: ["edge_id", "idea_id"],
    properties: { edge_id: { type: "integer" }, idea_id: { type: "integer" } },
  },
}
export async function markContradictionResolvedHandler({ edge_id, idea_id }) {
  return factorDb.markContradictionResolved({ edge_id, idea_id });
}

export const markContradictionBoundedSchema = {
  name: "mark_contradiction_bounded",
  description:
    "标记 CONTRADICTS 边为「axiom 边界限定」(否定性结论:axiom 在此 regime 不完备,产不出必然正命题)。与 mark_contradiction_resolved 对称:resolved=肯定解决(产 idea),bounded=否定解决(axiom 证伪)。bounded 后该矛盾不再算 unresolved。graph-reasoner 判定矛盾为或然(axiom 证伪而非数据不足)时调用。",
  inputSchema: {
    type: "object",
    required: ["edge_id", "regime", "reason"],
    properties: {
      edge_id: { type: "integer" },
      regime: { type: "string", description: "失效 regime(如 'SHFE-AG 500ms')" },
      reason: { type: "string", description: "为何或然非必然(超加性/唯一性证不出的根因)" },
    },
  },
};
export async function markContradictionBoundedHandler({ edge_id, regime, reason }) {
  return factorDb.markContradictionBounded({ edge_id, regime, reason });
}

export const ALL_GRAPH_TRAVERSAL_SCHEMAS = [
  queryContradictionsSchema, getSubgraphSchema, neighborhoodSchema,
  findRefutationClustersSchema, graphStatsSchema,
  addGraphNodeSchema, addGraphEdgesSchema,
  markContradictionResolvedSchema, markContradictionBoundedSchema,
];
export const ALL_GRAPH_TRAVERSAL_HANDLERS = {
  query_contradictions: queryContradictionsHandler,
  get_subgraph: getSubgraphHandler,
  neighborhood: neighborhoodHandler,
  find_refutation_clusters: findRefutationClustersHandler,
  graph_stats: graphStatsHandler,
  add_graph_node: addGraphNodeHandler,
  add_graph_edges: addGraphEdgesHandler,
  mark_contradiction_resolved: markContradictionResolvedHandler,
  mark_contradiction_bounded: markContradictionBoundedHandler,
};
