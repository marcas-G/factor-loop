#!/usr/bin/env python3
"""P002 Phenomenon Miner — observation-only, FORBIDDEN interpretation。

从 factors.db 扫描 4 类"表示内部不一致"现象（非 dead_end）：
A. 成功因子局部裂缝: 总体有效但某匹配状态下反转/失效
B. 两有效因子冲突: 同 state 下方向不兼容
C. 跨 feed 匹配矛盾: 控制 regime 后 main/sub 行为不同
D. 多尺度矛盾: 同因子跨 horizon 符号翻转/衰减异常

输出: phenomenon JSON（无解释，只有 observation）
"""
import sqlite3, json, numpy as np

DB = "/home/lgao/work/factor-autoloop/factors.db"

def mine(conn):
    phenomena = []

    # === Source A: 成功因子局部裂缝 ===
    # 策略: icir>1 的成功因子, 但 sign_match<0.55 或 bad_bucket 比例高
    # → "总体有效但某条件下行为不稳"
    print("=== Source A: 成功因子局部裂缝 ===")
    factors_a = conn.execute("""
        SELECT f.xname, f.latest_icir, f.latest_ic, COALESCE(f.angle_code,'?')
        FROM factors f
        WHERE f.status='evaluated' AND f.latest_icir IS NOT NULL AND f.latest_icir > 1.5
        ORDER BY f.latest_icir DESC LIMIT 20
    """).fetchall()
    for xn, icir, ic, ang in factors_a:
        rows = conn.execute("""
            SELECT y_horizon, AVG(ic), COUNT(*)
            FROM factor_ic_daily
            WHERE factor_xname=? AND symbol='SHFE-AG' AND freq NOT LIKE '%sub%'
            GROUP BY y_horizon
        """, (xn,)).fetchall()
        if len(rows) < 3: continue
        ics = {h: v for h, v, _ in rows}
        # 找 horizon 间符号翻转
        sorted_h = sorted(ics.keys())
        for i in range(len(sorted_h)-1):
            h1, h2 = sorted_h[i], sorted_h[i+1]
            if ics[h1] * ics[h2] < 0 and abs(ics[h1]) > 0.01 and abs(ics[h2]) > 0.003:
                phenomena.append({
                    "phenomenon_id": f"P-A-{len([p for p in phenomena if p['source_type']=='A'])+1}",
                    "source_type": "A_local_break",
                    "representations": {"factor": xn[:35], "angle": ang},
                    "matched_conditions": {"symbol": "SHFE-AG", "feed": "main"},
                    "expected_regular_relation": "成功因子跨 horizon 应同号平滑衰减",
                    "observed_deviation": f"h{h1} IC={ics[h1]:.4f} vs h{h2} IC={ics[h2]:.4f} 符号翻转",
                    "persistence": {"n_horizons": len(ics), "icir": round(icir,2)},
                    "evidence_strength": "MODERATE",
                    "interpretation": "FORBIDDEN"
                })
                print(f"  {xn[:30]:<30} h{h1}={ics[h1]:.4f} → h{h2}={ics[h2]:.4f} (flip)")
                break

    # === Source B: 两有效因子冲突 ===
    # 同 angle_code 的两个 icir>1 因子, IC 序列 pearson < 0 (稳定反向)
    print(f"\n=== Source B: 两有效因子冲突 ===")
    angles = conn.execute("SELECT DISTINCT angle_code FROM factors WHERE status='evaluated' AND angle_code IS NOT NULL").fetchall()
    for (ang,) in angles:
        fs = conn.execute("SELECT xname FROM factors WHERE angle_code=? AND status='evaluated' AND latest_icir>1.5",(ang,)).fetchall()
        if len(fs) < 2: continue
        for i in range(len(fs)):
            for j in range(i+1, min(i+3, len(fs))):
                r1 = conn.execute("SELECT date,ic FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND y_horizon=1 AND freq NOT LIKE '%sub%' ORDER BY date",(fs[i][0],)).fetchall()
                r2 = conn.execute("SELECT date,ic FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND y_horizon=1 AND freq NOT LIKE '%sub%' ORDER BY date",(fs[j][0],)).fetchall()
                d1={d:v for d,v in r1}; d2={d:v for d,v in r2}
                common=sorted(set(d1)&set(d2))
                if len(common)<30: continue
                a=[d1[d] for d in common]; b=[d2[d] for d in common]
                if np.std(a)<1e-9 or np.std(b)<1e-9: continue
                c=np.corrcoef(a,b)[0,1]
                if c < -0.1:
                    phenomena.append({
                        "phenomenon_id": f"P-B-{len([p for p in phenomena if p['source_type']=='B'])+1}",
                        "source_type": "B_conflict",
                        "representations": {"factor_a": fs[i][0][:30], "factor_b": fs[j][0][:30], "angle": ang},
                        "matched_conditions": {"symbol": "SHFE-AG", "horizon": 1, "n_days": len(common)},
                        "expected_regular_relation": "同 angle 有效因子应方向一致",
                        "observed_deviation": f"IC corr={c:.3f} (反向)",
                        "persistence": {"n_days": len(common)},
                        "evidence_strength": "MODERATE",
                        "interpretation": "FORBIDDEN"
                    })
                    print(f"  [{ang}] {fs[i][0][:20]} vs {fs[j][0][:20]} corr={c:.3f}")
                    break
            else: continue
            break

    # === Source C: 跨 feed 匹配矛盾 ===
    # icir>1 的因子, main 有信号但 sub 近零或翻转
    print(f"\n=== Source C: 跨 feed 矛盾 ===")
    cross = conn.execute("SELECT DISTINCT factor_xname FROM factor_ic_daily WHERE symbol='SHFE-AG' AND freq LIKE '%sub%'").fetchall()
    for (xn,) in cross[:25]:
        mi = conn.execute("SELECT AVG(ic) FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND freq NOT LIKE '%sub%' AND y_horizon=1",(xn,)).fetchone()[0]
        si = conn.execute("SELECT AVG(ic) FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND freq LIKE '%sub%' AND y_horizon=1",(xn,)).fetchone()[0]
        if mi and si and abs(mi)>0.02 and mi*si<0:
            phenomena.append({
                "phenomenon_id": f"P-C-{len([p for p in phenomena if p['source_type']=='C'])+1}",
                "source_type": "C_cross_feed",
                "representations": {"factor": xn[:35], "main_ic": round(mi,4), "sub_ic": round(si,4)},
                "matched_conditions": {"symbol": "SHFE-AG", "horizon": 1},
                "expected_regular_relation": "同因子跨 main/sub feed 应行为一致",
                "observed_deviation": f"main IC={mi:.4f} vs sub IC={si:.4f} 符号翻转",
                "persistence": {},
                "evidence_strength": "MODERATE",
                "interpretation": "FORBIDDEN"
            })
            print(f"  {xn[:32]:<32} main={mi:.4f} sub={si:.4f}")

    # === Source D: 多尺度矛盾 ===
    # h1 强但 h300 衰减>85%（短尺度有信号长尺度消失）
    print(f"\n=== Source D: 多尺度矛盾 ===")
    multi = conn.execute("SELECT DISTINCT factor_xname FROM factor_ic_daily WHERE symbol='SHFE-AG' GROUP BY factor_xname HAVING COUNT(DISTINCT y_horizon)>=4").fetchall()
    for (xn,) in multi[:30]:
        h1 = conn.execute("SELECT AVG(ic) FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND y_horizon=1 AND freq NOT LIKE '%sub%'",(xn,)).fetchone()[0]
        h300 = conn.execute("SELECT AVG(ic) FROM factor_ic_daily WHERE factor_xname=? AND symbol='SHFE-AG' AND y_horizon=300 AND freq NOT LIKE '%sub%'",(xn,)).fetchone()[0]
        if h1 and h300 and abs(h1)>0.03 and abs(h300)<abs(h1)*0.15:
            phenomena.append({
                "phenomenon_id": f"P-D-{len([p for p in phenomena if p['source_type']=='D'])+1}",
                "source_type": "D_multiscale",
                "representations": {"factor": xn[:35]},
                "matched_conditions": {"symbol": "SHFE-AG", "feed": "main"},
                "expected_regular_relation": "同因子跨 horizon 应可预测衰减",
                "observed_deviation": f"h1 IC={h1:.4f} → h300 IC={h300:.4f} (衰减{100*(1-abs(h300/h1)):.0f}%)",
                "persistence": {},
                "evidence_strength": "MODERATE",
                "interpretation": "FORBIDDEN"
            })
            print(f"  {xn[:32]:<32} h1={h1:.4f} h300={h300:.4f} ({100*(1-abs(h300/h1)):.0f}%衰减)")

    print(f"\n=== 总 phenomenon: {len(phenomena)} ===")
    for s in set(p['source_type'] for p in phenomena):
        n = sum(1 for p in phenomena if p['source_type']==s)
        print(f"  {s}: {n}")
    return phenomena

if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    phen = mine(conn)
    conn.close()
    json.dump(phen, open("/tmp/p002_phenomena.json","w"), ensure_ascii=False, indent=1)
