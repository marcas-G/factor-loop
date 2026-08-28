import { describe, expect, it } from "vitest";
import { applyFilters, operatorChainLength, sortFactors } from "./filter";
import { DEFAULT_FILTERS } from "../state";
import type { Factor } from "../types";

const F = (over: Partial<Factor>): Factor => ({
  xname: "Alpha", class_name: null, file_path: null, formula_text: null, params: null,
  status: "evaluated", verdict: null, latest_ic: null, latest_icir: null,
  latest_sharpe: null, latest_rank_ic: null, latest_r2_x: null, latest_res_ic: null,
  created_ts: null, last_updated_ts: null, deprecated_at: null,
  quality_score: null, quality_grade: null, intuition: null, anchor_text: null,
  origin_type: null, cohort_tag: null, operator_chain: null,
  evaluation_status: null, tags: [], resic_ic_ratio: null,
  gate_pass: false, failed_gates: [], s_ic: null, s_icir: null,
  s_res_ic: null, s_r2: null, agg_score: null,
  ...over,
});

describe("operatorChainLength", () => {
  it("null when operator_chain missing", () => {
    expect(operatorChainLength(F({}))).toBeNull();
  });
  it("0 when empty or whitespace", () => {
    expect(operatorChainLength(F({ operator_chain: "" }))).toBe(0);
    expect(operatorChainLength(F({ operator_chain: "   " }))).toBe(0);
  });
  it("counts split parts", () => {
    expect(operatorChainLength(F({ operator_chain: "a->b->c" }))).toBe(3);
    expect(operatorChainLength(F({ operator_chain: "a+b·c" }))).toBe(3);
    expect(operatorChainLength(F({ operator_chain: "a->b->c->d->e" }))).toBe(5);
  });
  it("parses JSON array strings as the DB stores them (persist.py json.dumps)", () => {
    expect(operatorChainLength(F({ operator_chain: "[]" }))).toBe(0);
    expect(operatorChainLength(F({ operator_chain: "[21]" }))).toBe(1);
    expect(operatorChainLength(F({ operator_chain: "[21, 23]" }))).toBe(2);
  });
  it("falls back to split on malformed JSON array", () => {
    expect(operatorChainLength(F({ operator_chain: "[21,23" }))).toBe(1);
  });
});

describe("applyFilters", () => {
  it("text search hits xname, formula, intuition and tag names", () => {
    const fs = [
      F({ xname: "alpha_one" }),
      F({ xname: "X1", formula_text: "ALPHA_ONE(x)" }),
      F({ xname: "X2", intuition: " alpha_one idea" }),
      F({ xname: "X3", tags: [{ name: "Alpha_One", description: null }] }),
      F({ xname: "X4", formula_text: "unrelated" }),
    ];
    const out = applyFilters(fs, { ...DEFAULT_FILTERS, q: "alpha_one" });
    expect(out.map(f => f.xname)).toEqual(["alpha_one", "X1", "X2", "X3"]);
  });
  it("status multi-select", () => {
    const fs = [F({ xname: "A", status: "draft" }), F({ xname: "B", status: "evaluated" })];
    expect(applyFilters(fs, { ...DEFAULT_FILTERS, status: ["draft"] })
      .map(f => f.xname)).toEqual(["A"]);
  });
  it("gate combo: pass requires gate_pass, others require not-failed", () => {
    const fs = [
      F({ xname: "pass", gate_pass: true, failed_gates: [] }),
      F({ xname: "failPass", gate_pass: false, failed_gates: [] }),
      F({ xname: "icFail", gate_pass: true, failed_gates: ["ic"] }),
      F({ xname: "icOk", gate_pass: true, failed_gates: ["r2"] }),
    ];
    const out = applyFilters(fs, { ...DEFAULT_FILTERS, gates: ["pass", "ic"] });
    expect(out.map(f => f.xname)).toEqual(["pass", "icOk"]);
  });
  it("tags: any overlap", () => {
    const fs = [
      F({ xname: "A", tags: [{ name: "t1", description: null }] }),
      F({ xname: "B", tags: [{ name: "t2", description: null }] }),
    ];
    expect(applyFilters(fs, { ...DEFAULT_FILTERS, tags: ["t1", "t9"] })
      .map(f => f.xname)).toEqual(["A"]);
  });
  it("origin matches origin_type or class_name", () => {
    const fs = [
      F({ xname: "A", origin_type: "seed", class_name: null }),
      F({ xname: "B", origin_type: null, class_name: "Momentum" }),
      F({ xname: "C", origin_type: "mutation", class_name: "Other" }),
    ];
    expect(applyFilters(fs, { ...DEFAULT_FILTERS, origin: ["seed", "Momentum"] })
      .map(f => f.xname)).toEqual(["A", "B"]);
  });
  it("op-chain range excludes null chains", () => {
    const fs = [
      F({ xname: "none" }),                                   // operator_chain null
      F({ xname: "zero", operator_chain: "" }),
      F({ xname: "two", operator_chain: "a->b" }),
      F({ xname: "four", operator_chain: "a->b->c->d" }),
    ];
    const out = applyFilters(fs, { ...DEFAULT_FILTERS, opChainMin: 2, opChainMax: 3 });
    expect(out.map(f => f.xname)).toEqual(["two"]);
  });
  it("op-chain min only", () => {
    const fs = [
      F({ xname: "none" }),
      F({ xname: "one", operator_chain: "a" }),
      F({ xname: "five", operator_chain: "a->b->c->d->e" }),
    ];
    expect(applyFilters(fs, { ...DEFAULT_FILTERS, opChainMin: 2 })
      .map(f => f.xname)).toEqual(["five"]);
  });
  it("created date range covers whole end day", () => {
    const fs = [
      F({ xname: "before", created_ts: "2026-01-02T10:00:00" }),
      F({ xname: "startDay", created_ts: "2026-03-01T00:00:01" }),
      F({ xname: "inRange", created_ts: "2026-03-15T12:00:00" }),
      F({ xname: "endDayLate", created_ts: "2026-05-31T23:30:00" }),
      F({ xname: "after", created_ts: "2026-06-01T00:00:00" }),
      F({ xname: "nullTs", created_ts: null }),
    ];
    const out = applyFilters(fs, {
      ...DEFAULT_FILTERS, createdFrom: "2026-03-01", createdTo: "2026-05-31",
    });
    expect(out.map(f => f.xname)).toEqual(["startDay", "inRange", "endDayLate"]);
  });
});

describe("sortFactors", () => {
  it("desc with nulls sunk", () => {
    const fs = [
      F({ xname: "a", agg_score: 1 }),
      F({ xname: "b", agg_score: null }),
      F({ xname: "c", agg_score: 3 }),
      F({ xname: "d", agg_score: null }),
      F({ xname: "e", agg_score: 2 }),
    ];
    expect(sortFactors(fs, "agg_score", "desc").map(f => f.xname))
      .toEqual(["c", "e", "a", "b", "d"]);
  });
  it("asc also sinks nulls", () => {
    const fs = [
      F({ xname: "a", latest_icir: 2 }),
      F({ xname: "b", latest_icir: null }),
      F({ xname: "c", latest_icir: 1 }),
    ];
    expect(sortFactors(fs, "latest_icir", "asc").map(f => f.xname))
      .toEqual(["c", "a", "b"]);
  });
  it("string keys sort localeCompare-aware", () => {
    const fs = [F({ xname: "b" }), F({ xname: "a" }), F({ xname: "c" })];
    expect(sortFactors(fs, "xname", "asc").map(f => f.xname)).toEqual(["a", "b", "c"]);
  });
});
