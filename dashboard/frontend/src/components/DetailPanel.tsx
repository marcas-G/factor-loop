import type { Factor, Iteration, Lesson } from "../types";

interface Props {
  factor: Factor | null;
  iterations: Iteration[];
  lessons: Lesson[];
  parentOf: Map<string, string>;
  onClose: () => void;
}

function Bar({ label, v }: { label: string; v: number | null }) {
  return (
    <div className="subscore">
      <span>{label}</span>
      <div className="track"><div className="fill" style={{ width: `${(v ?? 0) * 100}%` }} /></div>
      <b>{v === null ? "—" : v.toFixed(2)}</b>
    </div>
  );
}

const fmt = (v: number | null | undefined, d = 3): string =>
  v === null || v === undefined ? "—" : v.toFixed(d);

export function DetailPanel({ factor, iterations, lessons, parentOf, onClose }: Props) {
  if (!factor) return null;

  const path: string[] = [];
  const seen = new Set<string>();
  let cur: string | undefined = factor.xname;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    path.unshift(cur);
    cur = parentOf.get(cur);
  }
  const steps = path.slice(1).map((name, i) => ({
    name,
    it: iterations.find(t => t.to_xname === name && t.from_xname === path[i]),
  }));
  const rel = lessons.filter(l => l.factor_xname === factor.xname);

  return (
    <aside className="detail-panel" aria-live="polite">
      <header>
        <h3 className="mono">{factor.xname}</h3>
        <button className="icon-button" onClick={onClose} title="关闭">✕</button>
      </header>
      <div className="detail-metrics">
        <div><span>IC</span><b>{fmt(factor.latest_ic, 4)}</b></div>
        <div><span>ICIR</span><b>{fmt(factor.latest_icir, 2)}</b></div>
        <div><span>R²</span><b>{fmt(factor.latest_r2_x, 2)}</b></div>
        <div><span>残差IC</span><b>{fmt(factor.latest_res_ic, 4)}</b></div>
        <div><span>残差IC/IC</span><b>{fmt(factor.resic_ic_ratio, 2)}</b></div>
        <div><span>聚合分</span><b>{fmt(factor.agg_score)}</b></div>
      </div>
      <Bar label="IC 分" v={factor.s_ic} />
      <Bar label="ICIR 分" v={factor.s_icir} />
      <Bar label="残差IC 分" v={factor.s_res_ic} />
      <Bar label="R² 分" v={factor.s_r2} />
      {factor.tags.length > 0 && (
        <div className="chips">
          {factor.tags.map(t => <span key={t.name} className="chip">{t.name}</span>)}
        </div>
      )}
      {factor.formula_text && (
        <section><h4>公式</h4><pre className="code">{factor.formula_text}</pre></section>
      )}
      {factor.intuition && (
        <section><h4>意图</h4><p>{factor.intuition}</p></section>
      )}
      {factor.status && (
        <section><h4>状态</h4><p>{factor.status}{factor.verdict ? ` · ${factor.verdict}` : ""}</p></section>
      )}
      {steps.length > 0 && (
        <section>
          <h4>演化路径</h4>
          <ol className="evo">
            {steps.map(({ name, it }) => (
              <li key={name}>
                <span className="mono">{name}</span>
                {it && (
                  <>
                    <em>{it.change_note ?? it.reason ?? ""}</em>
                    <b className={it.outcome === "improved" ? "up" : it.outcome === "declined" ? "down" : ""}>
                      {it.outcome ?? ""}
                      {it.icir_delta != null
                        ? ` ${it.icir_delta > 0 ? "+" : ""}${it.icir_delta.toFixed(2)}` : ""}
                    </b>
                  </>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {rel.length > 0 && (
        <section>
          <h4>相关教训 ({rel.length})</h4>
          <ul className="lessons">
            {rel.map(l => <li key={l.id}><i>{l.type}</i>{l.text}</li>)}
          </ul>
        </section>
      )}
    </aside>
  );
}
