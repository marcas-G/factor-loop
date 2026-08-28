import { useMemo } from "react";
import type { Factor } from "../types";
import type { FilterState } from "../state";
import { applyFilters, sortFactors } from "../lib/filter";

interface Props {
  factors: Factor[];
  filters: FilterState;
  onSort: (key: FilterState["sortKey"]) => void;
  onSelect: (xname: string) => void;
}

interface Column {
  key: FilterState["sortKey"];
  label: string;
  title?: string;
  numeric?: boolean;
  fmt: (f: Factor) => string;
}

const nf = (v: number | null, digits: number): string =>
  v === null ? "—" : v.toFixed(digits);

const COLUMNS: Column[] = [
  { key: "xname", label: "因子", fmt: f => f.xname },
  { key: "verdict", label: "结论", fmt: f => f.verdict ?? "—" },
  {
    key: "agg_score", label: "聚合分", numeric: true,
    title: "公式说明: s_ic·s_icir·s_res_ic·s_r2 等标准化分的聚合",
    fmt: f => nf(f.agg_score, 2),
  },
  { key: "latest_ic", label: "IC", numeric: true, fmt: f => nf(f.latest_ic, 3) },
  { key: "latest_icir", label: "ICIR", numeric: true, fmt: f => nf(f.latest_icir, 2) },
  { key: "latest_r2_x", label: "R²", numeric: true, fmt: f => nf(f.latest_r2_x, 3) },
  { key: "latest_res_ic", label: "残差IC", numeric: true, fmt: f => nf(f.latest_res_ic, 3) },
  {
    key: "resic_ic_ratio", label: "残差IC/IC", numeric: true,
    fmt: f => nf(f.resic_ic_ratio, 2),
  },
  {
    key: "last_updated_ts", label: "更新时间",
    fmt: f => f.last_updated_ts ? f.last_updated_ts.slice(0, 16).replace("T", " ") : "—",
  },
];

function cell(v: string | null): string {
  if (v === null || v === "") return "";
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function FactorTable({ factors, filters, onSort, onSelect }: Props) {
  const rows = useMemo(
    () => sortFactors(applyFilters(factors, filters), filters.sortKey, filters.sortDir),
    [factors, filters],
  );

  const exportCsv = () => {
    const head = COLUMNS.map(c => cell(c.label)).join(",");
    const body = rows.map(f => COLUMNS.map(c => cell(c.fmt(f))).join(",")).join("\n");
    const blob = new Blob(["﻿" + head + "\n" + body], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `factors-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="chart-box table-box">
      <div className="table-head">
        <figcaption>因子列表 · {rows.length} / {factors.length}</figcaption>
        <button type="button" className="fb-reset" onClick={exportCsv}>导出 CSV</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLUMNS.map(c => (
                <th key={c.key} className={c.numeric ? "num" : ""}>
                  <button type="button" className="sort-header" title={c.title}
                          onClick={() => onSort(c.key)}>
                    {c.label}
                    {filters.sortKey === c.key &&
                      <span className="sort-arrow">{filters.sortDir === "desc" ? "▼" : "▲"}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(f => (
              <tr key={f.xname}
                  className={filters.selected === f.xname ? "selected" : ""}
                  tabIndex={0}
                  onClick={() => onSelect(f.xname)}
                  onKeyDown={e => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(f.xname);
                    }
                  }}>
                {COLUMNS.map(c => (
                  <td key={c.key} className={c.numeric ? "num" : ""}
                      title={c.key === "xname" ? f.xname : undefined}>
                    {c.key === "verdict" && f.verdict
                      ? <span className={`verdict v-${f.verdict}`}>{f.verdict}</span>
                      : c.fmt(f)}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={COLUMNS.length} className="table-empty">无匹配因子</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
