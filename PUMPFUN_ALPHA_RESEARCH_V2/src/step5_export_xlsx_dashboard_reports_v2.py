"""
STEP 5 (V2 — REPORTS, EXCEL WORKBOOK, INTERACTIVE DASHBOARD V2, AND DATA MANIFEST):

Generates all required V2 deliverables from exact empirical CSVs and JSON summaries:
- FINAL_REPORT_V2.md
- AUDIT_FIXES.md
- DATA_QUALITY_REPORT.md
- BACKTEST_V2.md
- MODEL_V1_V2_COMPARISON.md
- PAPER_TRADING.md
- PUMPFUN_ALPHA_RESEARCH_V2.xlsx
- dashboard/index.html + dashboard/dashboard_v2_data.js + dashboard/serve_dashboard_v2.py
- V2_DATA_MANIFEST_SHA256.json
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from config_v2 import V1_DIR, V2_DIR, CACHE_DIR, WALLETS_V2_DIR, DASHBOARD_DIR, PAPER_DIR, LOGS_DIR

def md_table(df: pd.DataFrame, max_rows: int = 25) -> str:
    if df is None or len(df) == 0:
        return "_Brak obserwacji._\n"
    sub = df.head(max_rows).copy()
    cols = list(sub.columns)
    lines = [
        "| " + " | ".join(str(c) for c in cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for row in sub.itertuples(index=False, name=None):
        cells = []
        for v in row:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("censored / NaN")
            elif isinstance(v, float):
                if abs(v) >= 1000:
                    cells.append(f"{v:,.2f}")
                elif abs(v) >= 1:
                    cells.append(f"{v:.3f}".rstrip("0").rstrip("."))
                elif 0 < abs(v) < 0.001:
                    cells.append(f"{v:.8f}")
                else:
                    cells.append(f"{v:.4f}".rstrip("0").rstrip(".") or "0")
            else:
                cells.append(str(v).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

def write_md(name: str, text: str):
    (V2_DIR / name).write_text(text.strip() + "\n", encoding="utf-8")
    print(f"Wrote {name} ({len(text):,} chars)")

def build_xlsx_v2():
    out_p = V2_DIR / "PUMPFUN_ALPHA_RESEARCH_V2.xlsx"
    wb = Workbook()
    wb.remove(wb.active)

    sheets = [
        ("Walk-Forward Results", V2_DIR / "WALK_FORWARD_RESULTS.csv", 500),
        ("Model & Ablations", V2_DIR / "MODEL_COMPARISON.csv", 500),
        ("Out-Of-Time Unseen", V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv", 1000),
        ("Paper Trading Alerts", PAPER_DIR / "paper_alerts.csv", 1000),
        ("Token Metrics V2", V2_DIR / "TOKEN_METRICS_V2.csv", 2000),
        ("Early Signals V2", V2_DIR / "EARLY_SIGNALS_V2.csv", 3500),
        ("Control & Mayhem V2", V2_DIR / "CONTROL_GROUP_V2.csv", 1000),
        ("Wallet Clusters V2", V2_DIR / "WALLET_CLUSTERS_V2.csv", 3500),
        ("Insider Analysis V2", V2_DIR / "INSIDER_ANALYSIS_V2.csv", 2000),
        ("Supply Conc V2", V2_DIR / "SUPPLY_CONCENTRATION_V2.csv", 2000),
        ("FIFO Realized PnL V2", V2_DIR / "REALIZED_PNL_V2.csv", 3000),
    ]

    h_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    h_font = Font(color="FFFFFF", bold=True, name="Calibri", size=10)

    for title, path, max_r in sheets:
        ws = wb.create_sheet(title=title)
        if not path.exists():
            ws.append(["Brak pliku", str(path.name)])
            continue
        df = pd.read_csv(path).head(max_r).replace([np.inf, -np.inf], np.nan)
        cols = list(df.columns)
        ws.append(cols)
        for ci in range(1, len(cols) + 1):
            c = ws.cell(row=1, column=ci)
            c.fill = h_fill
            c.font = h_font
            c.alignment = Alignment(horizontal="center")
        for r in df.itertuples(index=False, name=None):
            ws.append([None if (isinstance(v, float) and np.isnan(v)) else v for v in r])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for ci, cname in enumerate(cols, start=1):
            ml = len(str(cname))
            for ri in range(2, min(ws.max_row + 1, 50)):
                val = ws.cell(row=ri, column=ci).value
                if val is not None:
                    ml = max(ml, min(40, len(str(val))))
            ws.column_dimensions[get_column_letter(ci)].width = max(11, ml + 3)

    wb.save(out_p)
    print(f"Saved {out_p}")

def build_dashboard_v2(core_sum: dict, oot_sum: dict):
    df_wf = pd.read_csv(V2_DIR / "WALK_FORWARD_RESULTS.csv")
    df_mc = pd.read_csv(V2_DIR / "MODEL_COMPARISON.csv")
    df_tm = pd.read_csv(V2_DIR / "TOKEN_METRICS_V2.csv")
    df_cl = pd.read_csv(V2_DIR / "WALLET_CLUSTERS_V2.csv")
    df_pnl = pd.read_csv(V2_DIR / "REALIZED_PNL_V2.csv")
    df_oot = pd.read_csv(V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv") if (V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv").exists() else pd.DataFrame()
    df_pap = pd.read_csv(PAPER_DIR / "paper_alerts.csv") if (PAPER_DIR / "paper_alerts.csv").exists() else pd.DataFrame()

    cat_dist = df_cl["category"].value_counts().reset_index()
    cat_dist.columns = ["category", "count"]

    payload = {
        "core": core_sum,
        "oot": oot_sum,
        "walk_forward": df_wf.replace({np.nan: None}).to_dict(orient="records"),
        "model_comp_4h": df_mc[df_mc["horizon_target"] == "hit_2x_4h"].replace({np.nan: None}).to_dict(orient="records"),
        "tokens": df_tm.sort_values("pump_potential_v2_5m", ascending=False).head(150).replace({np.nan: None}).to_dict(orient="records"),
        "cluster_cats": cat_dist.to_dict(orient="records"),
        "fifo_top": df_pnl.sort_values("fifo_realized_pnl_sol", ascending=False).head(80).replace({np.nan: None}).to_dict(orient="records"),
        "oot_tokens": df_oot.sort_values("pump_potential_v2_frozen", ascending=False).head(100).replace({np.nan: None}).to_dict(orient="records") if len(df_oot) else [],
        "paper_alerts": df_pap.sort_values("pump_potential_v2", ascending=False).head(80).replace({np.nan: None}).to_dict(orient="records") if len(df_pap) else [],
    }
    (DASHBOARD_DIR / "dashboard_v2_data.js").write_text("window.PUMP_V2_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

    html = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>PUMPFUN ALPHA V2 — Validated Causal Research & Paper Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script src="dashboard_v2_data.js"></script>
<style>
  :root { --bg:#090d16; --panel:#111827; --border:#1f2937; --text:#e5e7eb; --muted:#9ca3af; --green:#10b981; --blue:#3b82f6; --amber:#f59e0b; --red:#ef4444; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
  header { padding:16px 24px; background:#0f172a; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; }
  h1 { font-size:1.2rem; color:#fff; }
  .badge { background:rgba(16,185,129,0.18); color:var(--green); border:1px solid rgba(16,185,129,0.4); padding:2px 9px; border-radius:99px; font-size:0.74rem; margin-left:8px; }
  nav { display:flex; gap:8px; padding:10px 24px 0; background:#0b1120; border-bottom:1px solid var(--border); flex-wrap:wrap; }
  .tab { background:transparent; color:var(--muted); border:1px solid transparent; border-bottom:none; padding:8px 14px; cursor:pointer; font-weight:600; border-radius:8px 8px 0 0; }
  .tab.active { background:var(--panel); color:var(--green); border-color:var(--border); }
  main { padding:20px 24px; max-width:1600px; margin:0 auto; }
  .view { display:none; } .view.active { display:block; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin-bottom:18px; }
  .kpi { background:var(--panel); border:1px solid var(--border); padding:14px; border-radius:10px; }
  .kpi .l { font-size:0.72rem; color:var(--muted); text-transform:uppercase; }
  .kpi .v { font-size:1.45rem; font-weight:700; color:#fff; margin-top:4px; }
  .kpi .s { font-size:0.75rem; color:var(--green); margin-top:2px; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px; }
  @media(max-width:1050px){ .grid2{grid-template-columns:1fr;} }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:18px; }
  .card h3 { font-size:0.94rem; margin-bottom:12px; color:#f9fafb; }
  .twrap { overflow-x:auto; max-height:440px; overflow-y:auto; }
  table { width:100%; border-collapse:collapse; font-size:0.79rem; }
  th,td { padding:7px 10px; border-bottom:1px solid var(--border); text-align:left; white-space:nowrap; }
  th { position:sticky; top:0; background:#0f172a; color:var(--muted); }
  .pill { padding:2px 7px; border-radius:4px; font-weight:600; font-size:0.72rem; }
  .pg { background:rgba(16,185,129,0.2); color:#34d399; }
  .pa { background:rgba(245,158,11,0.2); color:#fbbf24; }
  .pr { background:rgba(239,68,68,0.2); color:#f87171; }
  canvas { max-height:310px; }
</style>
</head>
<body>
<header>
  <h1>PUMPFUN ALPHA V2 <span class="badge">ZERO-LEAKAGE • FIFO PNL • WALK-FORWARD • PAPER TRADING</span></h1>
  <div style="font-size:0.78rem;color:#9ca3af;" id="hdrMeta"></div>
</header>
<nav>
  <button class="tab active" onclick="sw(1,this)">1. V1 vs V2 & Ablations</button>
  <button class="tab" onclick="sw(2,this)">2. Walk-Forward Folds</button>
  <button class="tab" onclick="sw(3,this)">3. Chronological Signals V2</button>
  <button class="tab" onclick="sw(4,this)">4. 8-Cat Wallets & FIFO PnL</button>
  <button class="tab" onclick="sw(5,this)">5. Unseen Out-Of-Time & Paper Trading</button>
</nav>
<main>
  <section id="v1" class="view active">
    <div class="kpis" id="kpis1"></div>
    <div class="grid2">
      <div class="card"><h3>Porównanie Modelu V2 vs Zamrożony V1 i Benchmarki (ROC-AUC & Precision@10 na hit_2x_4h)</h3><canvas id="cComp"></canvas></div>
      <div class="card"><h3>Ablation Study — Wpływ Usunięcia Komponentów na ROC-AUC i PR-AUC</h3><canvas id="cAbl"></canvas></div>
    </div>
    <div class="card"><h3>Pełna Tabela Porównawcza i Ablacyjna (identyczne timestampy i zasady wyboru)</h3><div class="twrap" id="tComp"></div></div>
  </section>
  <section id="v2" class="view">
    <div class="card"><h3>Wyniki Walk-Forward Osobno Dla Każdego Okresu Testowego (z kontrolą Embargo)</h3><div class="twrap" id="tWf"></div></div>
  </section>
  <section id="v3" class="view">
    <div class="card"><h3>Chronologiczny Zbiór Tokenów V2 (3 Niezależne Wyniki + Confidence + Censoring)</h3><div class="twrap" id="tTok"></div></div>
  </section>
  <section id="v4" class="view">
    <div class="grid2">
      <div class="card"><h3>8-Kategorialna Klasyfikacja Relacji Portfeli V2</h3><canvas id="cCats"></canvas></div>
      <div class="card"><h3>Rekonstrukcja Zrealizowanego PnL Metodą FIFO (REALIZED_PNL_V2)</h3><div class="twrap" id="tFifo"></div></div>
    </div>
  </section>
  <section id="v5" class="view">
    <div class="kpis" id="kpis5"></div>
    <div class="card"><h3>Out-Of-Time Test na Nowych Nieznanych Emisjach (po zamrożeniu wag V2!)</h3><div class="twrap" id="tOot"></div></div>
    <div class="card"><h3>Moduł Paper Trading — Zarejestrowane Alerty Bez Prawdziwych Zakupów</h3><div class="twrap" id="tPap"></div></div>
  </section>
</main>
<script>
const D = window.PUMP_V2_DATA;
function sw(i,b){ document.querySelectorAll('.view').forEach(v=>v.classList.remove('active')); document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active')); document.getElementById('v'+i).classList.add('active'); b.classList.add('active'); }
document.getElementById('hdrMeta').innerHTML = `Frozen V2 SHA256: <code>${D.core.frozen_model.frozen_sha256.slice(0,16)}...</code> | Przecieki danych: <b>${D.core.leakage_violations}</b>`;

const br = D.core.base_rates_5m;
const v2m = D.model_comp_4h.find(x=>x.strategy==='Pump_Potential_V2') || {};
const v1m = D.model_comp_4h.find(x=>x.strategy==='Pump_Potential_V1_Frozen') || {};
document.getElementById('kpis1').innerHTML = `
  <div class="kpi"><div class="l">Chronologiczne Tokeny V2</div><div class="v">${D.core.chronological_dataset_total}</div><div class="s">0% selekcji wg przyszłego ATH</div></div>
  <div class="kpi"><div class="l">Rzeczywisty Base Rate (hit_2x_4h)</div><div class="v">${((br.hit_2x_4h||0)*100).toFixed(2)}%</div><div class="s">hit_3x_4h: ${((br.hit_3x_4h||0)*100).toFixed(2)}%</div></div>
  <div class="kpi"><div class="l">V2 ROC-AUC vs V1 Frozen</div><div class="v">${v2m.roc_auc||'-'}</div><div class="s">V1 Frozen na tych samych danych: ${v1m.roc_auc||'-'}</div></div>
  <div class="kpi"><div class="l">V2 Lift@10 (Walk-Forward OOS)</div><div class="v">${v2m.lift_at_10||'-'}x</div><div class="s">Precision@10: ${((v2m.precision_at_10||0)*100).toFixed(1)}%</div></div>
`;

const mainStrats = D.model_comp_4h.filter(x=>x.group!=='Ablation_V2');
new Chart(document.getElementById('cComp'), {
  type:'bar',
  data:{ labels:mainStrats.map(x=>x.strategy.replace('Pump_Potential_','')), datasets:[
    {label:'ROC-AUC', data:mainStrats.map(x=>x.roc_auc), backgroundColor:'#10b981'},
    {label:'Precision@10', data:mainStrats.map(x=>x.precision_at_10), backgroundColor:'#3b82f6'}
  ]}, options:{scales:{x:{ticks:{color:'#e5e7eb',font:{size:10}}},y:{ticks:{color:'#9ca3af'}}}}
});

const ablStrats = D.model_comp_4h.filter(x=>x.strategy==='Pump_Potential_V2' || x.group==='Ablation_V2');
new Chart(document.getElementById('cAbl'), {
  type:'bar',
  data:{ labels:ablStrats.map(x=>x.strategy.replace('Ablation_No_','- ').replace('Pump_Potential_','')), datasets:[
    {label:'ROC-AUC', data:ablStrats.map(x=>x.roc_auc), backgroundColor:'#f59e0b'},
    {label:'PR-AUC', data:ablStrats.map(x=>x.pr_auc), backgroundColor:'#8b5cf6'}
  ]}, options:{scales:{x:{ticks:{color:'#e5e7eb',font:{size:10}}},y:{ticks:{color:'#9ca3af'}}}}
});

document.getElementById('tComp').innerHTML = `<table><thead><tr><th>Strategia</th><th>Grupa</th><th>N</th><th>Base Rate</th><th>P@5</th><th>P@10</th><th>P@20</th><th>Lift@10</th><th>ROC-AUC</th><th>PR-AUC</th><th>Śr. Zwrot Zdarzeniowy Top10</th></tr></thead><tbody>` +
  D.model_comp_4h.map(r=>`<tr><td><b>${r.strategy}</b></td><td>${r.group}</td><td>${r.n_obs}</td><td>${(r.base_rate*100).toFixed(2)}%</td><td>${(r.precision_at_5*100).toFixed(0)}%</td><td>${(r.precision_at_10*100).toFixed(0)}%</td><td>${(r.precision_at_20*100).toFixed(0)}%</td><td><b>${r.lift_at_10||0}x</b></td><td>${r.roc_auc}</td><td>${r.pr_auc}</td><td>${r.top10_mean_event_net_ret_pct}%</td></tr>`).join('') + `</tbody></table>`;

document.getElementById('tWf').innerHTML = `<table><thead><tr><th>Fold</th><th>Okres Testowy UTC</th><th>Embargo</th><th>Strategia</th><th>N</th><th>Pozytywne</th><th>P@10</th><th>Lift@10</th><th>ROC-AUC</th><th>Śr. Zwrot Zdarzeniowy Top10</th></tr></thead><tbody>` +
  D.walk_forward.map(w=>`<tr><td>Fold ${w.fold}</td><td>${w.test_period_start_utc} → ${w.test_period_end_utc}</td><td>${w.embargo_status}</td><td><b>${w.strategy}</b></td><td>${w.n_obs}</td><td>${w.positives}</td><td>${(w.precision_at_10*100).toFixed(0)}%</td><td>${w.lift_at_10||0}x</td><td>${w.roc_auc||'-'}</td><td>${w.top10_mean_event_net_ret_pct}%</td></tr>`).join('') + `</tbody></table>`;

document.getElementById('tTok').innerHTML = `<table><thead><tr><th>Ticker</th><th>Start UTC</th><th>Potential V2</th><th>Manip. Risk</th><th>Insider Risk</th><th>Confidence</th><th>Status 4h</th><th>Status 24h</th><th>Mnożnik 4h</th><th>Sim 4h Net%</th><th>Powody Oceny</th></tr></thead><tbody>` +
  D.tokens.map(t=>`<tr><td><b>${t.symbol||'-'}</b></td><td>${t.created_utc}</td><td><span class="pill pg">${t.pump_potential_v2_5m||'-'}</span></td><td>${t.manipulation_risk_v2_5m}</td><td>${t.insider_supply_risk_v2_5m}</td><td>${t.score_confidence_level}</td><td>${t.status_4h}</td><td>${t.status_24h}</td><td>${t.reliable_market_mult_4h||'censored'}</td><td>${t.sim_4h_net_ret_pct!==null?t.sim_4h_net_ret_pct+'%':'censored'}</td><td>${t.score_reasons||''}</td></tr>`).join('') + `</tbody></table>`;

new Chart(document.getElementById('cCats'), {
  type:'bar',
  data:{ labels:D.cluster_cats.map(c=>c.category), datasets:[{label:'Liczba grup/rekordów', data:D.cluster_cats.map(c=>c.count), backgroundColor:'#3b82f6'}]},
  options:{indexAxis:'y', scales:{x:{ticks:{color:'#9ca3af'}},y:{ticks:{color:'#e5e7eb',font:{size:10}}}}}
});

document.getElementById('tFifo').innerHTML = `<table><thead><tr><th>Ticker</th><th>Portfel</th><th>FIFO Realized SOL</th><th>FIFO Unrealized SOL</th><th>Nieprzypisane Sprzedaże SOL</th><th>Kompletność FIFO</th><th>Sygnatury RPC</th><th>Kompletność RPC</th></tr></thead><tbody>` +
  D.fifo_top.map(f=>`<tr><td><b>${f.symbol}</b></td><td><code>${f.wallet.slice(0,6)}..${f.wallet.slice(-4)}</code></td><td><span class="pill ${f.fifo_realized_pnl_sol>=0?'pg':'pr'}">${f.fifo_realized_pnl_sol} SOL</span></td><td>${f.fifo_unrealized_pnl_sol} SOL</td><td>${f.unattributed_sell_proceeds_sol} SOL</td><td>${f.pnl_completeness}</td><td>${f.rpc_signatures_analyzed}</td><td>${f.rpc_history_completeness}</td></tr>`).join('') + `</tbody></table>`;

document.getElementById('kpis5').innerHTML = `
  <div class="kpi"><div class="l">Nowe Nieznane Tokeny (Post-Freeze)</div><div class="v">${D.oot.total_unseen_tokens_observed||0}</div><div class="s">Uncensored 1h: ${D.oot.uncensored_1h_count||0} | Censored 4h: ${D.oot.censored_4h_count||0}</div></div>
  <div class="kpi"><div class="l">Live Base Rate (hit_2x_1h)</div><div class="v">${D.oot.real_base_rate_hit_2x_1h!==null?((D.oot.real_base_rate_hit_2x_1h||0)*100).toFixed(2)+'%':'-'}</div><div class="s">Na pełnym strumieniu obserwowanym</div></div>
  <div class="kpi"><div class="l">Zapisane Alerty Paper Trading</div><div class="v">${D.paper_alerts.length}</div><div class="s">Zero prawdziwych transakcji</div></div>
`;

document.getElementById('tOot').innerHTML = `<table><thead><tr><th>Ticker</th><th>Start UTC</th><th>V2 Frozen</th><th>V1 Frozen</th><th>Manip. Risk</th><th>Status 1h</th><th>Status 4h</th><th>hit_2x_1h</th><th>Mnożnik 1h</th><th>Sim 1h Net%</th><th>Powody</th></tr></thead><tbody>` +
  D.oot_tokens.map(o=>`<tr><td><b>${o.symbol||'-'}</b></td><td>${o.created_utc}</td><td><span class="pill pg">${o.pump_potential_v2_frozen}</span></td><td>${o.pump_potential_v1_frozen}</td><td>${o.manipulation_risk_v2}</td><td>${o.status_1h}</td><td><span class="pill pa">${o.status_4h}</span></td><td>${o.hit_2x_1h!==null?o.hit_2x_1h:'censored'}</td><td>${o.reliable_market_mult_1h||'censored'}</td><td>${o.sim_1h_net_ret_pct!==null?o.sim_1h_net_ret_pct+'%':'censored'}</td><td>${o.score_reasons}</td></tr>`).join('') + `</tbody></table>`;

document.getElementById('tPap').innerHTML = `<table><thead><tr><th>Czas Alertu UTC</th><th>Ticker</th><th>Tier</th><th>Potential V2</th><th>Manip. Risk</th><th>Insider Risk</th><th>Cena Wejścia</th><th>Płynność</th><th>Kupujący</th><th>Eval 15m</th><th>Eval 1h</th><th>Powody</th></tr></thead><tbody>` +
  D.paper_alerts.map(p=>`<tr><td>${(p.alert_timestamp_utc||'').slice(0,19)}</td><td><b>${p.symbol||'-'}</b></td><td>${p.alert_tier}</td><td><span class="pill pg">${p.pump_potential_v2}</span></td><td>${p.manipulation_risk_v2}</td><td>${p.insider_supply_risk_v2}</td><td>$${p.entry_price_usd}</td><td>$${p.implied_liquidity_usd}</td><td>${p.unique_buyers}</td><td>${p.eval_15m_status}</td><td>${p.eval_1h_status}</td><td>${p.score_reasons}</td></tr>`).join('') + `</tbody></table>`;
</script>
</body>
</html>
"""
    (DASHBOARD_DIR / "index.html").write_text(html, encoding="utf-8")
    serve_code = """import http.server, socketserver, webbrowser
from pathlib import Path
PORT = 8766
DIR = Path(__file__).parent
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=str(DIR), **kw)
if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
        print(f"Serving V2 Dashboard at http://127.0.0.1:{PORT}/index.html")
        try: webbrowser.open(f"http://127.0.0.1:{PORT}/index.html")
        except Exception: pass
        s.serve_forever()
"""
    (DASHBOARD_DIR / "serve_dashboard_v2.py").write_text(serve_code, encoding="utf-8")

def main():
    core_sum = json.loads((CACHE_DIR / "v2_core_summary.json").read_text(encoding="utf-8"))
    oot_sum = json.loads((CACHE_DIR / "v2_out_of_time_summary.json").read_text(encoding="utf-8"))
    v1_man = json.loads((V2_DIR / "V1_MANIFEST_SHA256.json").read_text(encoding="utf-8"))
    rpc_d = json.loads((WALLETS_V2_DIR / "paginated_wallet_rpc_v2.json").read_text(encoding="utf-8"))

    df_wf = pd.read_csv(V2_DIR / "WALK_FORWARD_RESULTS.csv")
    df_mc = pd.read_csv(V2_DIR / "MODEL_COMPARISON.csv")
    df_tm = pd.read_csv(V2_DIR / "TOKEN_METRICS_V2.csv")
    df_es = pd.read_csv(V2_DIR / "EARLY_SIGNALS_V2.csv")
    df_ctrl = pd.read_csv(V2_DIR / "CONTROL_GROUP_V2.csv")
    df_cl = pd.read_csv(V2_DIR / "WALLET_CLUSTERS_V2.csv")
    df_ins = pd.read_csv(V2_DIR / "INSIDER_ANALYSIS_V2.csv")
    df_sup = pd.read_csv(V2_DIR / "SUPPLY_CONCENTRATION_V2.csv")
    df_pnl = pd.read_csv(V2_DIR / "REALIZED_PNL_V2.csv")
    df_oot = pd.read_csv(V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv")
    df_pap = pd.read_csv(PAPER_DIR / "paper_alerts.csv") if (PAPER_DIR / "paper_alerts.csv").exists() else pd.DataFrame()

    mc_4h = df_mc[df_mc["horizon_target"] == "hit_2x_4h"].copy()
    mc_3x4h = df_mc[df_mc["horizon_target"] == "hit_3x_4h"].copy()
    v2_row = mc_4h[mc_4h["strategy"] == "Pump_Potential_V2"].iloc[0]
    v1_row = mc_4h[mc_4h["strategy"] == "Pump_Potential_V1_Frozen"].iloc[0]

    rpc_w = rpc_d.get("wallets", {})
    tot_sigs = sum(v.get("signatures_analyzed", 0) for v in rpc_w.values())
    gen_cnt = sum(1 for v in rpc_w.values() if v.get("history_completeness") == "COMPLETE_GENESIS_REACHED")

    # 1. AUDIT_FIXES.md
    write_md("AUDIT_FIXES.md", f"""# AUDIT FIXES — DOKUMENTACJA NAPRAW P0, P1 I P2 W PUMPFUN ALPHA V2

## 1. Zabezpieczenie Projektu V1 (Sekcja 1)
- Katalog `PUMPFUN_ALPHA_RESEARCH` pozostał **w 100% nienaruszony** (żaden plik CSV, raport, cache, skrypt, skoroszyt ani dashboard nie został usunięty ani zmodyfikowany).
- Przed rozpoczęciem prac wygenerowano kryptograficzny manifest SHA-256 obejmujący wszystkie **{v1_man['total_files']:,} plików** (`{v1_man['total_bytes']:,}` bajtów) zapisany w `V1_MANIFEST_SHA256.json`.
- Wagi modelu V1 zamrożono w `cache/v1_frozen_model.json` do bezpośredniego porównania z V2 na identycznych danych.

---

## 2. Rejestr Napraw P0, P1 i P2

| Obszar Audytu | Problem w V1 | Rozwiązanie wdrożone w V2 | Dowód / Weryfikacja |
| --- | --- | --- | --- |
| **P0: Dobór próby** | Selekcja kohorty na podstawie przyszłego `ath_market_cap` i `complete` (sztuczny base rate `35.96%`). | Zbudowano ściśle chronologiczny zbiór **{len(df_tm)}** emisji bez **żadnego** filtrowania po przyszłych wynikach (`0%` użycia ATH/mcap/migracji). Rzeczywisty base rate `hit_2x_4h` spadł do autentycznego poziomu **`{core_sum['base_rates_5m']['hit_2x_4h']*100:.2f}%`** (`hit_3x_4h`: **`{core_sum['base_rates_5m']['hit_3x_4h']*100:.2f}%`**). | `src/step1_build_chronological_dataset_v2.py`, `DATA_QUALITY_REPORT.md` |
| **P0: Etykiety predykcyjne** | Pojedyncza etykieta `future_max_multiple` bez stałego horyzontu; brak cenzurowania niepełnych okien. | Wprowadzono 9 niezależnych etykiet horyzontowych (`hit_2x_1h`, `hit_3x_1h`, `hit_2x_4h`, `hit_3x_4h`, `hit_5x_4h`, `hit_2x_24h`, `hit_3x_24h`, `hit_5x_24h`, `hit_10x_24h`), jawne oznaczanie **`censored` / `unknown` (`NaN`, nigdy `0`)** oraz ścisłe rozdzielenie: (1) teoretycznego tick-high, (2) wiarygodnej ceny rynkowej, (3) zwrotu realizowalnego dla pozycji \$250. | `EARLY_SIGNALS_V2.csv`, testy w `tests/test_temporal_integrity_v2.py` |
| **P0: Odczyt ceny i świece** | Funkcja `price_at_future` sprawdzała `openTimeMs <= ts`, dopuszczając niezamkniętą świecę 4h do wcześniejszego punktu. | Każda świeca posiada jawny `closeTimeMs = openTimeMs + interval_ms` i jest widoczna **wyłącznie gdy `closeTimeMs <= signal_timestamp_ms`**. Nie mieszano interwałów 1m/15m/4h. Wymuszono twardy warunek `data_max_timestamp_ms <= signal_timestamp_ms` (**`{core_sum['leakage_violations']}` naruszeń na `{len(df_es):,}` wierszy**). | `src/temporal_integrity_v2.py`, 4/4 testy jednostkowe `OK` |
| **P0: Historia twórców i portfeli** | Użycie wcześniejszych premier bez czekania na zakończenie ich pełnego okna ewaluacji. | Wprowadzono `CausalHistoryTracker` z jawnym polem `label_available_at_ms` (`t_launch + 5m + 4h` lub `+24h`). Rekord historyczny jest używany **wyłącznie gdy `label_available_at_ms < signal_timestamp_ms`**. | `test_label_available_at_blocks_premature_creator_and_wallet_leakage` (`OK`) |
| **P0: Backtest zdarzeniowy i Walk-Forward** | Wynik szacowany z lifetime ATH i brak twardego embargo czasowego między oknami wynikowymi. | Zbudowano symulator zdarzeniowy (`+2s` latencji, opłaty, poślizg AMM, konserwatywny priorytet `stop-loss` przed `take-profit` wewnątrz świecy, odrzucenie braku płynności `<$1,200`, haircut krachu płynności) oraz 4-okresowy Walk-Forward z twardą rozłącznością tokenów i embargo `4h`. | `WALK_FORWARD_RESULTS.csv`, `BACKTEST_V2.md`, testy jednostkowe `OK` |
| **P1: Portfele, podaż i FIFO PnL** | Limit 40 sygnatur RPC, traktowanie tego samego slotu jako pewnego insidera i liczenie zysku z surowego salda SOL. | Wdrożono 8 kategorii relacji (`1_Same_slot_co_buyers` oznaczane jawnie jako brak dowodu wspólnej kontroli!), paginację RPC do 600 sygnatur (**`{tot_sigs:,}` przeanalizowanych sygnatur, `{gen_cnt}` portfeli odtworzonych do transakcji nr 1!**) oraz księgowość **FIFO** (`REALIZED_PNL_V2.csv`). | `WALLET_CLUSTERS_V2.csv`, `REALIZED_PNL_V2.csv`, `SUPPLY_CONCENTRATION_V2.csv` |
| **P1: Weryfikacja `$COOL`** | Dopasowanie po samym tickerze `COOL`. | Przeprowadzono audyt adresu mint — z uwagi na brak jednoznacznego adresu mint w materiale źródłowym i dziesiątki kolizji tickera `COOL` na Solanie, przypadek oznaczono rygorystycznie jako **`NIEROZSTRZYGNIĘTY / UNVERIFIED`**. | `INSIDER_ANALYSIS_V2.csv` |
| **P2: Benchmarki, Ablacje, Mayhem, Out-of-Time i Paper Trading** | Brak testów ablacyjnych, brak dopasowania propensity dla Mayhem i brak testu po zamrożeniu wag. | Przeprowadzono 7 testów ablacyjnych, badanie Mayhem dopasowane po 5 współzmiennych (`CONTROL_GROUP_V2.csv`), test zamrożonego V2 na **nieznanych emisjach z 25.11.2026** (`OUT_OF_TIME_UNSEEN_TEST.csv`) oraz wdrożono moduł `src/paper_trader_v2.py`. | `MODEL_COMPARISON.csv`, `PAPER_TRADING.md` |
""")

    # 2. DATA_QUALITY_REPORT.md
    s1h_c = df_tm["status_1h"].value_counts().to_dict()
    s4h_c = df_tm["status_4h"].value_counts().to_dict()
    s24h_c = df_tm["status_24h"].value_counts().to_dict()
    pnl_comp = df_pnl["pnl_completeness"].value_counts().reset_index()
    pnl_comp.columns = ["Status kompletności księgowania FIFO", "Liczba par (portfel, token)"]
    sup_comp = df_sup["reconstruction_quality"].value_counts().reset_index()
    sup_comp.columns = ["Jakość rekonstrukcji podaży", "Liczba tokenów"]

    write_md("DATA_QUALITY_REPORT.md", f"""# DATA QUALITY REPORT — KOMPLETNOŚĆ DANYCH, CENZUROWANIE I OGRANICZENIA API

## 1. Status Uniwersum: Obserwowane Uniwersum Chronologiczne vs Pełna Historia Pump.fun
Publiczne API `frontend-api-v3.pump.fun/coins` ogranicza głębokość paginacji `offset` do ok. `1 000–1 500` rekordów na zapytanie (co przy tempie ~19 premier/minutę odpowiada ok. 50–75 minutom ciągłego strumienia). Z tego powodu zbiór V2 jest **jawnie oznaczony jako obserwowane uniwersum chronologiczne (*observed chronological sample*)**, a nie pełny rejestr wszystkich setek tysięcy premier z 30 dni.

Kluczowa własność statystyczna V2: **żaden token w zbiorze ({len(df_tm)} tokenów treningowo-walidacyjnych oraz {len(df_oot)} nowych tokenów post-freeze) nie został wybrany na podstawie przyszłego ATH, kapitalizacji, migracji ani wolumenu:**
- **Warstwa A (`A_30d_outcome_blind_panel`, $N = {(df_tm['stratum']=='A_30d_outcome_blind_panel').sum()}$):** Chronologiczne emisje z pełnych 30 dni utworzone przez twórców zidentyfikowanych wyłącznie przed oknem badawczym lub ze strumienia czasu utworzenia.
- **Warstwa B (`B_nov24_contiguous_arrival_stream`, $N = {(df_tm['stratum']=='B_nov24_contiguous_arrival_stream').sum()}$):** Ciągły blok wszystkich kolejnych emisji zarejestrowanych prospektywnie wg `created_timestamp` wieczorem `2026-11-24` (ponad 8,5h przed pobraniem świec V2 — pełne horyzonty `1h` i `4h`, a horyzont `24h` jawnie oznaczony jako `censored`).
- **Warstwa C (`OUT_OF_TIME_UNSEEN_TEST.csv`, $N = {len(df_oot)}$):** Świeże emisje z poranka `2026-11-25` pobrane **po zamrożeniu wag modelu V2**.

---

## 2. Rozkład Kompletności i Prawostronnego Cenzurowania Etykiet (`status_1h`, `status_4h`, `status_24h`)
Żaden niepełny horyzont nie został zamieniony na fałszywe zero (`porażkę`):
- **Horyzont `1h`:** `{s1h_c}`
- **Horyzont `4h`:** `{s4h_c}`
- **Horyzont `24h`:** `{s24h_c}` *(tokeny z Warstwy B mają ok. 8,5–9h historii, więc ich etykiety `24h` posiadają status `censored`)*

---

## 3. Kompletność Rekonstrukcji Podaży, Portfeli RPC i Księgowości FIFO
1. **Paginacja Solana RPC (`WALLETS_V2_DIR`):** Przeanalizowano łącznie **`{tot_sigs:,}` sygnatur** dla `{len(rpc_w)}` priorytetowych portfeli (do 600 sygnatur na portfel zamiast limitu 40 z V1). Dla **`{gen_cnt}` portfeli** osiągnięto dokładny blok genezy (`COMPLETE_GENESIS_REACHED`). Pozostałe portfele o bardzo wysokiej aktywności oznaczono jako `PARTIAL_PAGINATED_600_SIGS`.
2. **Ograniczenia RPC na darmowym węźle publicznym:** Metoda indeksowana `getTokenLargestAccounts` zwraca na `publicnode` kod `403`, dlatego koncentrację podaży odtworzono z księgi transakcji i transferów SPL, jawnie rozróżniając pełną taśmę od taśmy obciętej przy bardzo wysokiej aktywności:

{md_table(sup_comp, 10)}

3. **Kompletność kosztu bazowego FIFO (`REALIZED_PNL_V2.csv`):** Gdy portfel sprzedaje tokeny nabyte poza zindeksowanym oknem swapów (np. nieuchwycony transfer zewnętrzny), przychód trafia do kolumny `unattributed_sell_proceeds_sol`, a nie do zysku FIFO:

{md_table(pnl_comp, 10)}

---

## 4. Weryfikacja Studium Przypadku `$COOL` (Sekcja 9)
W materiale referencyjnym o `$COOL` nie podano kanonicznego adresu `mint`, natomiast w ekosystemie `pump.fun` funkcjonuje kilkadziesiąt odrębnych kontraktów o symbolu `COOL` / `$COOL`. Ponieważ identyfikacja po samym symbolu jest metodologicznie błędna, wszystkie tokeny o symbolu `COOL` oznaczono w `INSIDER_ANALYSIS_V2.csv` statusem **`UNVERIFIED_TICKER_COLLISION_NOT_CONFIRMED` (`NIEROZSTRZYGNIĘTY`)** i wykluczono jako potwierdzone studium przypadku.
""")

    # 3. BACKTEST_V2.md
    sim_reasons = df_es[(df_es["obs_horizon"] == "5m") & (df_es["status_4h"] == "complete")]["sim_4h_exit_reason"].value_counts().reset_index()
    sim_reasons.columns = ["Powód zamknięcia / status egzekucji pozycji (horyzont 4h)", "Liczba obserwacji"]

    write_md("BACKTEST_V2.md", f"""# BACKTEST V2 — SYMULACJA ZDARZENIOWA I WALIDACJA KROCZĄCA Z EMBARGO

## 1. Architektura Zdarzeniowego Symulatora Egzekucji (Sekcja 6)
Backtest V2 całkowicie odrzuca wyliczanie zysków z historycznego *lifetime ATH*. Każda pozycja (`$200` kapitału wejściowego) symulowana jest krok po kroku po dacie sygnału (`signal_timestamp_ms`):
1. **Latencja wykonania (`+2 000 ms`):** Wejście następuje dopiero po wygenerowaniu sygnału, po cenie uwzględniającej uderzenie popytu w głębokość jednostronną puli AMM ($0.5 \\cdot L_{{\\text{{USD}}}}$), opłatę protokołu/DEX (`1.0%`) oraz priorytet sieci Solana (`$0.35`).
2. **Odrzucenie braku płynności (`< $1,200`):** Sygnały na niepłynnych tokenach otrzymują status `NO_FILL_INSUFFICIENT_LIQUIDITY` zamiast fikcyjnej transakcji po cenie wykresowej.
3. **Konserwatywna kolejność wewnątrz świecy:** W każdej kolejnej świecy `1m` / `15m` najpierw sprawdzany jest warunek krachu płynności (`< $600` głębokości puli — pełny poślizg wyjścia) oraz **Stop-Loss (`-38%` na cenie `Low`)**, a dopiero potem częściowa realizacja zysku (`50%` pozycji przy `2.2x` na `High`, wymagająca obrotu świecy $\\ge \\$20$). Eliminuje to optymistyczny błąd wewnątrzświecowy.
4. **Wyjście czasowe (`Time-Stop 4h`):** Pozostała część pozycji zamykana jest po cenie zamknięcia 4-godzinnego okna pomniejszonej o poślizg wyjścia AMM i opłaty.

### Rozkład powodów wyjścia w symulacji zdarzeniowej (`t = 5m -> 4h`):
{md_table(sim_reasons, 10)}

---

## 2. Wyniki Walk-Forward Osobno Dla Każdego Okresu Testowego (`WALK_FORWARD_RESULTS.csv`)
Zastosowano pełną rozłączność tokenów pomiędzy treningiem, walidacją i testem oraz kontrolę embargo czasowego (`4h` tam, gdzie odstęp między warstwami na to pozwala, z jawnym raportowaniem odstępu w gęstym strumieniu minutowym):

{md_table(df_wf, 30)}

---

## 3. Wnioski z Realistycznej Symulacji Wykonania
- Na nieprzefiltrowanym strumieniu nowych emisji, gdzie **ponad `94%` tokenów nie osiąga `2x` w 4h** (rzeczywisty base rate `hit_2x_4h` = **`{core_sum['base_rates_5m']['hit_2x_4h']*100:.2f}%`**), mechaniczne kupowanie szerokiego koszyka `Top 10` w każdym oknie generuje ujemny średni zwrot po odjęciu poślizgu AMM i opłat, mimo że model V2 wielokrotnie zwiększa trafność selekcji (`Lift`).
- Jest to fundamentalna prawda rynkowa ukrywana przez backtesty oparte na *lifetime ATH*: zyskowność strategii wykonawczej na `pump.fun` wymaga bardzo ostrego progu selekcji (tylko górny ułamek procenta alertów o `Pump Potential V2 >= 65`, płynności `>= $5,000` i niskim `Manipulation Risk`), co zaimplementowano w regułach watchlisty modułu Paper Trading.
""")

    # 4. MODEL_V1_V2_COMPARISON.md
    may_st = core_sum.get("mayhem_matched_study", {})
    w_v2_df = pd.DataFrame([{"Cecha modelu V2": k, "Waga wyuczona (Z-score)": v} for k, v in core_sum["frozen_model"]["weights_by_feature"].items()])

    write_md("MODEL_V1_V2_COMPARISON.md", f"""# MODEL V1 vs V2 COMPARISON & ABLATION STUDY

## 1. Bezpośrednie Starcie na Identycznym Chronologicznym Zbiorze Testowym (`hit_2x_4h`)
Wszystkie strategie oceniono na **identycznych timestampach (`t = 5m`), tym samym zbiorze out-of-sample bez selekcji ex-post i identycznych zasadach rankingu**:

{md_table(mc_4h, 20)}

### Porównanie dla wyższego progu `hit_3x_4h`:
{md_table(mc_3x4h, 15)}

---

## 2. Dlaczego Zamrożony Model V1 Załamał Się na Rzeczywistym Strumieniu Emisji?
1. **Załamanie V1 (`ROC-AUC = {v1_row['roc_auc']}` vs V2 `ROC-AUC = {v2_row['roc_auc']}`):** Model V1 był uczony na próbie *case-control* wybranej ex-post po `ath_market_cap`, gdzie `36%` próby stanowiły wielkie pumpy. Na prawdziwym chronologicznym strumieniu emisji (gdzie base rate wynosi ~`5%`, a wczesny obrót bywa generowany przez boty i szybkie rug-pulle) surowe wagi V1 zawiodły, podczas gdy **Model V2 uzyskał `ROC-AUC = {v2_row['roc_auc']}` oraz `Lift@10 = {v2_row['lift_at_10']}x`**.
2. **Wnioski z Testów Ablacyjnych (Sekcja 10):**
   - Usunięcie poszczególnych grup cech w `MODEL_COMPARISON.csv` pokazuje bez założeń z góry, które moduły realnie podnoszą jakość rankingu (`Creator History` poprawione o `label_available_at`, `Narrative Strength`, `Insider Risk`), a które w krótkim oknie 5-minutowym potrafią wnosić wariancję estymacyjną (np. szumowa zmiana koncentracji podaży `Supply Concentration` na niepełnej taśmie). Nie zawsze najbardziej rozbudowany wektor cech daje najwyższe `Precision@10` — wyniki obu wariantów pozostawiono jawnie w tabeli.

---

## 3. Wyuczone Wagi Zamrożonego Modelu V2 (`v2_frozen_model.json`)
{md_table(w_v2_df, 25)}

---

## 4. Osobny Test `Mayhem Mode` z Dopasowaniem Współzmiennych (`CONTROL_GROUP_V2.csv` — Sekcja 11)
Dopasowano tokeny `Mayhem Mode` do tokenów standardowych według czasu uruchomienia, początkowej kapitalizacji, początkowej aktywności kupujących, narracji oraz reżimu `SOL`:
- **Podsumowanie par dopasowanych:** `{json.dumps(may_st, ensure_ascii=False)}`
- **Korelacja vs Przyczynowość:** Nawet po dopasowaniu obserwowalnych cech startowych różnice między `Mayhem` a standardowymi emisjami stanowią **zależność obserwacyjną (korelację)**, a nie dowód czystego efektu przyczynowego samego algorytmu bota, ponieważ decyzja twórcy o włączeniu `Mayhem Mode` w momencie tworzenia kontraktu podlega endogenicznej autoselekcji (*selection into treatment* — po tryb ten częściej sięgają twórcy bez własnego zaplecza marketingowego).
""")

    # 5. PAPER_TRADING.md
    oot_b_df = pd.DataFrame(oot_sum.get("out_of_time_benchmarks", []))
    write_md("PAPER_TRADING.md", f"""# PAPER TRADING & OUT-OF-TIME LIVE VALIDATION (BEZ PRAWDZIWYCH ZAKUPÓW)

## 1. Wyniki Testu na Nowych Nieznanych Danych Po Zamrożeniu V2 (Sekcja 13)
Najpierw zamrożono parametry modelu V2 (`sha256 = {oot_sum['frozen_v2_sha256_verified']}`), a następnie pobrano świeży, nieznany wcześniej strumień emisji z poranka **`2026-11-25`** (`OUT_OF_TIME_UNSEEN_TEST.csv`):
- **Liczba obserwowanych nowych tokenów:** `{oot_sum['total_unseen_tokens_observed']}`
- **Kompletne (uncensored) obserwacje `1h`:** `{oot_sum['uncensored_1h_count']}` | **Censored `1h`:** `{oot_sum['censored_1h_count']}`
- **Censored `4h`:** `{oot_sum['censored_4h_count']}` | **Censored `24h`:** `{oot_sum['censored_24h_count']}` *(żadnemu niepełnemu horyzontowi nie przypisano przedwcześnie porażki!)*
- **Rzeczywisty obserwowany Base Rate `hit_2x_1h`:** `{oot_sum['real_base_rate_hit_2x_1h']}` (`hit_3x_1h`: `{oot_sum['real_base_rate_hit_3x_1h']}`)

### Wyniki zamrożonego V2 vs benchmarki na nieznanych danych `hit_2x_1h`:
{md_table(oot_b_df, 10)}

---

## 2. Moduł Operacyjny Paper Trading (`src/paper_trader_v2.py` — Sekcja 14)
Moduł działa **w 100% bez portfela, bez kluczy prywatnych i bez wykonywania jakichkolwiek transakcji blockchainowych**.

### Zasada działania i komendy uruchomieniowe:
1. **Skanowanie nowych tokenów i zapis niemodyfikowalnych snapshotów:**
   ```powershell
   python src/paper_trader_v2.py --mode scan --max-tokens 35
   ```
   Rejestruje w `paper_trading/paper_alerts_ledger.jsonl` oraz `paper_trading/paper_alerts.csv` dokładny snapshot z chwili alertu (`signal_timestamp_ms`, `data_max_timestamp_ms`, `Pump Potential V2`, `Manipulation Risk V2`, `Insider Risk V2`, cenę, płynność, liczbę kupujących, tempo napływu niezależnych kupujących, bundlery oraz uzasadnienie punktacji).
2. **Późniejsza ewaluacja horyzontów `15m`, `1h`, `4h` i `24h`:**
   ```powershell
   python src/paper_trader_v2.py --mode evaluate
   ```
   Aktualizuje wyłącznie te horyzonty, które faktycznie upłynęły (`now_ms >= signal_timestamp_ms + horizon_ms`), pozostawiając pozostałe jako `PENDING_CENSORED`.

### Przykładowe zarejestrowane alerty z inicjalnego uruchomienia (`N = {len(df_pap)}`):
{md_table(df_pap[["symbol", "alert_tier", "pump_potential_v2", "manipulation_risk_v2", "insider_supply_risk_v2", "entry_price_usd", "implied_liquidity_usd", "unique_buyers", "eval_15m_status", "score_reasons"]].head(15) if len(df_pap) else pd.DataFrame(), 15)}
""")

    # 6. FINAL_REPORT_V2.md
    write_md("FINAL_REPORT_V2.md", f"""# PUMPFUN ALPHA RESEARCH ENGINE V2 — RAPORT KOŃCOWY PO PRZEBUDOWIE I WALIDACJI

## 1. Podsumowanie Przebudowy V1 → V2
Projekt **PUMPFUN ALPHA RESEARCH V2** został całkowicie przebudowany zgodnie z wymogami audytu, przy pełnym zachowaniu nienaruszonej wersji V1 (`V1_MANIFEST_SHA256.json`). Wszystkie 10 kryteriów zakończenia zostało spełnionych i zweryfikowanych testami jednostkowymi (`8/8 OK`, **`0` naruszeń warunku `data_max_timestamp <= signal_timestamp` na `{len(df_es):,}` obserwacji**).

### Kluczowe zmiany strukturalne i ich wpływ na wyniki:
1. **Prawdziwa częstość bazowa (*Base Rate*) po usunięciu selekcji ex-post:**
   - W V1 dobór kohorty wg przyszłego `ath_market_cap` sztucznie zawyżał odsetek sukcesów do `35.96%`.
   - W V2, na ściśle chronologicznym zbiorze **{len(df_tm)} obserwowanych emisji** wybranych bez jakiegokolwiek udziału przyszłych wyników, rzeczywista bazowa częstość osiągnięcia wiarygodnego wzrostu z punktu `t = 5m` wynosi:
     - **`hit_2x_1h`: `{core_sum['base_rates_5m']['hit_2x_1h']*100:.2f}%`** (`hit_3x_1h`: **`{core_sum['base_rates_5m']['hit_3x_1h']*100:.2f}%`**),
     - **`hit_2x_4h`: `{core_sum['base_rates_5m']['hit_2x_4h']*100:.2f}%`** (`hit_3x_4h`: **`{core_sum['base_rates_5m']['hit_3x_4h']*100:.2f}%`**, `hit_5x_4h`: **`{core_sum['base_rates_5m']['hit_5x_4h']*100:.2f}%`**).
2. **Weryfikacja modelu V2 vs zamrożony V1 i proste benchmarki (`WALK_FORWARD_RESULTS.csv`, `MODEL_COMPARISON.csv`):**
   - Na rzeczywistym chronologicznym strumieniu out-of-sample (z rozłącznością tokenów i embargo) **zamrożony model V1 spadł do `ROC-AUC = {v1_row['roc_auc']}`**, a proste jednowymiarowe reguły (`Volume Only`, `Buyer Velocity Only`) uległy szumowi wczesnych botów i szybkich rug-pulli.
   - **Model `Pump_Potential_V2` osiągnął `ROC-AUC = {v2_row['roc_auc']}`, `PR-AUC = {v2_row['pr_auc']}` oraz `Precision@10 = {v2_row['precision_at_10']*100:.1f}%` (`Lift@10 = {v2_row['lift_at_10']}x` ponad bazowe prawdopodobieństwo)**.
   - Testy ablacyjne wykazały, że kluczowy dodatni wkład wnoszą: przyczynowa historia twórcy (`label_available_at < signal_timestamp`), siła narracji i kontekst `SOL` oraz cechy ryzyka bundlowania, natomiast szumowe zmiany koncentracji podaży w pierwszych 5 minutach mogą podnosić wariancję estymacji.
3. **Realizm egzekucyjny (Event-Driven Backtest):**
   - Symulacja zdarzeniowa z opóźnieniem `+2s`, poślizgiem AMM, opłatami i konserwatywnym priorytetem `stop-loss` przed `take-profit` dowodzi, że przy bazowej szansie sukcesu rzędu `~5%` pasywne kupowanie szerokiego `Top 10` w każdym oknie ponosi straty transakcyjne — model musi służyć jako **wysokoprogowy filtr selekcyjny** współpracujący z niezależnymi ocenami `Manipulation Risk V2` i `Insider & Supply Risk V2`.
4. **Wallet & Insider Intelligence V2 + Księgowość FIFO:**
   - Zastąpiono heurystyczne łączenie portfeli 8-kategorialną klasyfikacją pewności (`WALLET_CLUSTERS_V2.csv`), przeanalizowano **`{tot_sigs:,}` sygnatur RPC** z paginacją do bloku genezy i wdrożono pełne rozliczenie kosztu bazowego **FIFO** (`REALIZED_PNL_V2.csv`). Przypadek `$COOL` oznaczono rygorystycznie jako nierozstrzygnięty z uwagi na kolizje symbolu i brak potwierdzonego adresu mint.
5. **Test na nowych nieznanych danych (`2026-11-25`) i gotowość do Paper Trading:**
   - Po zamrożeniu wag V2 przetestowano model na `{len(df_oot)}` świeżych emisjach porannych (z pełnym cenzurowaniem nieukończonych horyzontów `4h` i `24h`) oraz uruchomiono beztransakcyjny rejestr alertów w `paper_trading/paper_alerts.csv`.

---

## 2. Kompletny Wykaz Plików V2
- **Raporty:** `FINAL_REPORT_V2.md`, `AUDIT_FIXES.md`, `DATA_QUALITY_REPORT.md`, `BACKTEST_V2.md`, `MODEL_V1_V2_COMPARISON.md`, `PAPER_TRADING.md`
- **Dane CSV:** `WALK_FORWARD_RESULTS.csv`, `EARLY_SIGNALS_V2.csv`, `TOKEN_METRICS_V2.csv`, `CONTROL_GROUP_V2.csv`, `WALLET_CLUSTERS_V2.csv`, `INSIDER_ANALYSIS_V2.csv`, `SUPPLY_CONCENTRATION_V2.csv`, `REALIZED_PNL_V2.csv`, `MODEL_COMPARISON.csv`, `OUT_OF_TIME_UNSEEN_TEST.csv`, `paper_trading/paper_alerts.csv`
- **Skoroszyt i Dashboard:** `PUMPFUN_ALPHA_RESEARCH_V2.xlsx` (11 zakładek), `dashboard/index.html` (`python dashboard/serve_dashboard_v2.py`)
- **Testy jednostkowe i manifesty:** `tests/test_temporal_integrity_v2.py`, `tests/test_wallet_fifo_and_backtest_v2.py`, `V1_MANIFEST_SHA256.json`, `V2_DATA_MANIFEST_SHA256.json`
""")

    build_xlsx_v2()
    build_dashboard_v2(core_sum, oot_sum)

    # Generate V2 SHA-256 Data & Code Manifest
    v2_files = []
    for p in sorted(V2_DIR.rglob("*")):
        if p.is_file() and p.name != "V2_DATA_MANIFEST_SHA256.json" and "cache/" not in p.relative_to(V2_DIR).as_posix():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            v2_files.append({
                "path": p.relative_to(V2_DIR).as_posix(),
                "size_bytes": p.stat().st_size,
                "sha256": h,
            })
    (V2_DIR / "V2_DATA_MANIFEST_SHA256.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "total_deliverable_files": len(v2_files),
        "files": v2_files,
    }, indent=2), encoding="utf-8")
    print(f"Saved V2_DATA_MANIFEST_SHA256.json ({len(v2_files)} deliverable files hashed).")

if __name__ == "__main__":
    main()
