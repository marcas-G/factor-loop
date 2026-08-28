import { useEffect, useMemo, useRef, useState } from "react";
import type { Factor } from "../types";
import type { FilterState } from "../state";
import { GATE_OPTIONS } from "../lib/filter";
import { STATUS_LABELS } from "../charts/colors";

interface Props {
  factors: Factor[];
  filters: FilterState;
  onChange: (patch: Partial<FilterState>) => void;
  onReset: () => void;
}

function uniq(xs: string[]): string[] {
  return [...new Set(xs)].sort((a, b) => a.localeCompare(b));
}

function MultiSelect({ label, options, selected, labels, onChange }: {
  label: string;
  options: string[];
  selected: string[];
  labels?: Record<string, string>;
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const away = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter(s => s !== v) : [...selected, v]);

  return (
    <div className="ms" ref={ref}>
      <button type="button" className="ms-btn" onClick={() => setOpen(o => !o)}>
        {label}
        {selected.length > 0 && <span className="count">{selected.length}</span>}
      </button>
      {open && (
        <div className="ms-pop">
          {options.length === 0 && <div className="ms-empty">无选项</div>}
          {options.map(o => (
            <label key={o} className="ms-item">
              <input type="checkbox" checked={selected.includes(o)}
                     onChange={() => toggle(o)} />
              <span>{labels?.[o] ?? o}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilterBar({ factors, filters, onChange, onReset }: Props) {
  const options = useMemo(() => {
    const tagNames: string[] = [];
    const origins: string[] = [];
    for (const f of factors) {
      for (const t of f.tags) tagNames.push(t.name);
      if (f.origin_type) origins.push(f.origin_type);
      if (f.class_name) origins.push(f.class_name);
    }
    return {
      status: uniq(factors.map(f => f.status)),
      tags: uniq(tagNames),
      origin: uniq(origins),
    };
  }, [factors]);

  const num = (v: string): number | null =>
    v === "" ? null : (Number.isFinite(Number(v)) ? Number(v) : null);

  return (
    <div className="filter-bar">
      <input className="fb-search" placeholder="搜索 xname / 公式 / 直觉 / 标签"
             value={filters.q}
             onChange={e => onChange({ q: e.target.value })} />

      <MultiSelect label="状态" options={options.status} selected={filters.status}
                   labels={STATUS_LABELS}
                   onChange={next => onChange({ status: next })} />
      <MultiSelect label="标签" options={options.tags} selected={filters.tags}
                   onChange={next => onChange({ tags: next })} />
      <MultiSelect label="闸门" options={GATE_OPTIONS.map(g => g.value)}
                   selected={filters.gates}
                   labels={Object.fromEntries(GATE_OPTIONS.map(g => [g.value, g.label]))}
                   onChange={next => onChange({ gates: next })} />
      <MultiSelect label="来源" options={options.origin} selected={filters.origin}
                   onChange={next => onChange({ origin: next })} />

      <div className="fb-range">
        <span className="fb-label">算子链</span>
        <input type="number" min={0} placeholder="min" value={filters.opChainMin ?? ""}
               onChange={e => onChange({ opChainMin: num(e.target.value) })} />
        <span className="fb-sep">–</span>
        <input type="number" min={0} placeholder="max" value={filters.opChainMax ?? ""}
               onChange={e => onChange({ opChainMax: num(e.target.value) })} />
      </div>

      <div className="fb-range">
        <span className="fb-label">创建</span>
        <input type="date" value={filters.createdFrom ?? ""}
               onChange={e => onChange({ createdFrom: e.target.value || null })} />
        <span className="fb-sep">–</span>
        <input type="date" value={filters.createdTo ?? ""}
               onChange={e => onChange({ createdTo: e.target.value || null })} />
      </div>

      <button type="button" className="fb-reset" onClick={onReset}>重置</button>
    </div>
  );
}
