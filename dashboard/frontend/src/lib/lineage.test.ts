import { describe, expect, it } from "vitest";
import { buildTree, layoutTree, shortName, ancestorPath, NODE_W, COL_GAP } from "./lineage";
import type { Factor, LineageEdge } from "../types";

const F = (xname: string, icir = 1): Factor => ({
  xname, class_name: null, file_path: null, formula_text: null, params: null,
  status: "evaluated", verdict: null, latest_ic: 0.1, latest_icir: icir,
  latest_sharpe: null, latest_rank_ic: null, latest_r2_x: 0.2, latest_res_ic: 0.01,
  created_ts: null, last_updated_ts: null, quality_score: null, quality_grade: null,
  intuition: null, anchor_text: null, origin_type: null, cohort_tag: null,
  operator_chain: null, evaluation_status: null, deprecated_at: null, tags: [],
  resic_ic_ratio: 0.1, gate_pass: true, failed_gates: [],
  s_ic: 1, s_icir: 1, s_res_ic: 1, s_r2: 1, agg_score: 1,
});
const E = (p: string, c: string): LineageEdge => ({
  parent_xname: p, child_xname: c, relation_type: null, outcome: null,
  confidence: null, op_id: null, operator_name: null,
});

describe("shortName", () => {
  it("keeps short names", () => expect(shortName("Alpha")).toBe("Alpha"));
  it("truncates long names", () => {
    expect(shortName("VeryLongFactorNameThatExceedsLimit").length).toBeLessThanOrEqual(23);
  });
});

describe("buildTree", () => {
  it("builds parent-child and counts subtree", () => {
    const { roots, byName } = buildTree(
      [F("A"), F("B"), F("C")], [E("A", "B"), E("B", "C")], "all");
    expect(roots.map(r => r.xname)).toEqual(["A"]);
    expect(byName.get("A")!.subtreeCount).toBe(3);
    expect(byName.get("A")!.children[0].xname).toBe("B");
  });
  it("filters by branch", () => {
    const { roots } = buildTree([F("A"), F("B"), F("X")], [E("A", "B")], "A");
    expect(roots.map(r => r.xname)).toEqual(["A"]);
  });
  it("orphan (cycle-only) nodes still appear under all", () => {
    const { roots } = buildTree([F("A"), F("B")], [E("A", "B"), E("B", "A")], "all");
    expect(roots.length).toBe(2);
  });
});

describe("layoutTree", () => {
  it("lays out leaves on distinct rows, parents centered", () => {
    const { roots } = buildTree(
      [F("A"), F("B"), F("C"), F("D"), F("E")],
      [E("A", "B"), E("A", "C"), E("B", "D"), E("B", "E")], "all");
    const lay = layoutTree(roots, new Set());
    const y = (n: string) => lay.nodes.find(x => x.node.xname === n)!.y;
    expect(y("D")).not.toBe(y("E"));
    expect(y("B")).toBeCloseTo((y("D") + y("E")) / 2);
    expect(y("A")).toBeCloseTo((y("B") + y("C")) / 2);
    const x = (n: string) => lay.nodes.find(x => x.node.xname === n)!.x;
    expect(x("B") - x("A")).toBe(NODE_W + COL_GAP);
  });
  it("collapsed node hides descendants", () => {
    const { roots } = buildTree([F("A"), F("B"), F("C")],
                                [E("A", "B"), E("B", "C")], "all");
    const lay = layoutTree(roots, new Set(["B"]));
    expect(lay.nodes.map(n => n.node.xname)).not.toContain("C");
  });
  it("fills edge outcome/operator from edge list", () => {
    const edges: LineageEdge[] = [
      { ...E("A", "B"), outcome: "improved", operator_name: "winsorize" },
    ];
    const { roots } = buildTree([F("A"), F("B")], edges, "all");
    const lay = layoutTree(roots, new Set(), edges);
    expect(lay.edges.length).toBe(1);
    expect(lay.edges[0].outcome).toBe("improved");
    expect(lay.edges[0].operator).toBe("winsorize");
  });
});

describe("ancestorPath", () => {
  it("walks to root", () => {
    const parentOf = new Map([["C", "B"], ["B", "A"]]);
    expect(ancestorPath("C", parentOf)).toEqual(["A", "B", "C"]);
  });
  it("is cycle-safe", () => {
    const parentOf = new Map([["B", "A"], ["A", "B"]]);
    expect(ancestorPath("A", parentOf)).toEqual(["B", "A"]);
  });
});
