"""
STEP 6: Institutional Excel Workbook (`PUMPFUN_ALPHA_RESEARCH.xlsx` with 13 formatted tabs)
and Interactive 8-View HTML/JS Intelligence Dashboard (`dashboard/index.html` + `serve_dashboard.py`)
including Bubblemaps-style Wallet Cluster Graph, Multi-Token Price Charts, 7x24 Conditional Probability Heatmap
(UTC & Polish CET), and Global Interactive Filters (Date, Multiplier, Liquidity, Narrative, Pump Profile, Risk Level).
"""
import json
import logging
from pathlib import Path
import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from config import BASE_DIR, CACHE_DIR, CANDLES_CACHE_DIR, DASHBOARD_DIR, LOGS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step6_export.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step6")

def build_excel_workbook():
    out_xlsx = BASE_DIR / "PUMPFUN_ALPHA_RESEARCH.xlsx"
    logger.info(f"Building {out_xlsx} with 13 formatted sheets...")

    tabs = [
        ("TOP 100 PUMPS", "TOP_100_PUMPS.csv", 100),
        ("Token Metrics", "TOKEN_METRICS.csv", 2000),
        ("Wallet Intelligence", "WALLET_INTELLIGENCE.csv", 2000),
        ("Wallet Clusters", "WALLET_CLUSTERS.csv", 2000),
        ("Insider Analysis", "INSIDER_PROFIT_ANALYSIS.csv", 2000),
        ("Supply Concentration", "SUPPLY_CONCENTRATION.csv", 3500),
        ("Creator Analysis", "CREATOR_ANALYSIS.csv", 2000),
        ("Hourly Patterns", "HOURLY_PATTERNS.csv", 500),
        ("Name Analysis", "NAME_ANALYSIS.csv", 5000),
        ("Social Analysis", "SOCIAL_ANALYSIS.csv", 2000),
        ("Control Group", "CONTROL_GROUP.csv", 1000),
        ("Early Signals", "EARLY_SIGNALS.csv", 3500),
        ("Backtest", "BACKTEST_RESULTS.csv", 2000),
    ]

    wb = Workbook()
    # remove default sheet
    wb.remove(wb.active)

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, name="Calibri", size=10)
    cell_font = Font(name="Calibri", size=10)

    for sheet_title, csv_name, max_rows in tabs:
        ws = wb.create_sheet(title=sheet_title)
        csv_p = BASE_DIR / csv_name
        if not csv_p.exists():
            ws.append(["Brak pliku źródłowego", csv_name])
            continue
        df = pd.read_csv(csv_p).head(max_rows)
        # Replace NaN/inf for openpyxl
        df = df.replace([np.inf, -np.inf], np.nan)

        cols = list(df.columns)
        ws.append(cols)
        for col_idx in range(1, len(cols) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for row_vals in df.itertuples(index=False, name=None):
            clean_vals = [None if (isinstance(v, float) and np.isnan(v)) else v for v in row_vals]
            ws.append(clean_vals)

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        # Auto-adjust column widths (sample top 60 rows for speed)
        for col_idx, col_name in enumerate(cols, start=1):
            max_len = len(str(col_name))
            for r_idx in range(2, min(ws.max_row + 1, 60)):
                val = ws.cell(row=r_idx, column=col_idx).value
                if val is not None:
                    max_len = max(max_len, min(42, len(str(val))))
            ws.column_dimensions[get_column_letter(col_idx)].width = max(11, max_len + 3)

    wb.save(out_xlsx)
    logger.info(f"Saved {out_xlsx} successfully.")

def build_dashboard():
    logger.info("Building interactive 8-view PUMPFUN ALPHA INTELLIGENCE dashboard...")

    df_all = pd.read_csv(BASE_DIR / "ALL_TOKENS.csv")
    df_tm = pd.read_csv(BASE_DIR / "TOKEN_METRICS.csv")
    df_top100 = pd.read_csv(BASE_DIR / "TOP_100_PUMPS.csv")
    df_wallets = pd.read_csv(BASE_DIR / "WALLET_INTELLIGENCE.csv")
    df_clusters = pd.read_csv(BASE_DIR / "WALLET_CLUSTERS.csv")
    df_supply = pd.read_csv(BASE_DIR / "SUPPLY_CONCENTRATION.csv")
    df_ins_prof = pd.read_csv(BASE_DIR / "INSIDER_PROFIT_ANALYSIS.csv")
    df_ins_risk = pd.read_csv(BASE_DIR / "INSIDER_RISK.csv")
    df_hourly = pd.read_csv(BASE_DIR / "HOURLY_PATTERNS.csv")
    df_early = pd.read_csv(BASE_DIR / "EARLY_SIGNALS.csv")
    df_bt = pd.read_csv(BASE_DIR / "BACKTEST_RESULTS.csv")
    df_social = pd.read_csv(BASE_DIR / "SOCIAL_ANALYSIS.csv")

    with open(CACHE_DIR / "analytics_summary.json", "r", encoding="utf-8") as f:
        summary_json = json.load(f)
    with open(BASE_DIR / "research_metadata.json", "r", encoding="utf-8") as f:
        meta_json = json.load(f)

    # Daily market overview series (Group A 30d)
    df_ga = df_all[df_all["group_a_new_30d"] == 1].copy()
    df_ga["date"] = df_ga["created_utc"].str.slice(0, 10)
    daily_grp = df_ga.groupby("date", as_index=False).agg(
        new_tokens=("mint", "count"),
        pumps_2x=("group_b_pump_event", "sum"),
        migrated=("status_migrated_dex", "sum"),
        median_ath=("ath_mcap_usd", "median"),
    ).sort_values("date")

    # Embed candle series for top 25 pumps for interactive chart switching in View 2!
    candle_series_top = {}
    for m in df_top100["mint"].head(25).tolist():
        cp = CANDLES_CACHE_DIR / f"{m}.json"
        if cp.exists():
            cd = json.loads(cp.read_text(encoding="utf-8"))
            bars = cd.get("candles_4h") or cd.get("candles_15m") or cd.get("candles_1m") or []
            candle_series_top[m] = [
                {
                    "t": pd.to_datetime(int(b["openTimeMs"]), unit="ms", utc=True).strftime("%m-%d %H:%M"),
                    "c": round(float(b["close"]), 8),
                    "v": round(float(b.get("volumeUsd") or 0), 1)
                }
                for b in bars[-60:] if float(b.get("close") or 0) > 0
            ]

    # Narrative summary
    narr_grp = df_tm.groupby("narrative_category", as_index=False).agg(
        count=("mint", "count"),
        pumps_5x=("hit_5x", "sum"),
        median_mult=("reliable_market_multiple", "median"),
        mean_mult=("reliable_market_multiple", "mean"),
        avg_buyers_15m=("unique_buyers_15m", "mean"),
    ).sort_values("pumps_5x", ascending=False)
    narr_grp["rate_5x"] = (narr_grp["pumps_5x"] / narr_grp["count"]).round(4)

    # Supply trajectory across 7 checkpoints (Pumps 5x+ vs Controls)
    pump_mints_set = set(df_tm[df_tm["hit_5x"] == 1]["mint"])
    ctrl_mints_set = set(df_tm[df_tm["cohort_role"] == "control_matched"]["mint"])
    df_supply["grp_type"] = np.where(df_supply["mint"].isin(pump_mints_set), "Pumps_5x", np.where(df_supply["mint"].isin(ctrl_mints_set), "Controls", "Other"))
    sup_traj = df_supply[df_supply["grp_type"].isin(["Pumps_5x", "Controls"])].groupby(["checkpoint", "grp_type"], as_index=False).agg(
        top10_pct=("top10_holders_pct", "mean"),
        insiders_pct=("potential_insiders_pct", "mean"),
        clusters_pct=("detected_clusters_pct", "mean"),
    )

    dash_payload = {
        "meta": meta_json,
        "summary": summary_json,
        "daily_overview": daily_grp.replace({np.nan: None}).to_dict(orient="records"),
        "tokens": df_tm.replace({np.nan: None}).to_dict(orient="records"),
        "candle_series_top": candle_series_top,
        "early_5m": df_early[df_early["horizon"] == "5m"].sort_values("pump_potential_score", ascending=False).head(160).replace({np.nan: None}).to_dict(orient="records"),
        "wallets": df_wallets.head(120).replace({np.nan: None}).to_dict(orient="records"),
        "clusters": df_clusters.sort_values("accumulated_supply_pct", ascending=False).head(100).replace({np.nan: None}).to_dict(orient="records"),
        "insider_profits": df_ins_prof.sort_values("realized_profit_sol", ascending=False).head(80).replace({np.nan: None}).to_dict(orient="records"),
        "insider_risk": df_ins_risk.sort_values("insider_supply_risk_score", ascending=False).head(120).replace({np.nan: None}).to_dict(orient="records"),
        "supply_trajectory": sup_traj.replace({np.nan: None}).to_dict(orient="records"),
        "narratives": narr_grp.replace({np.nan: None}).to_dict(orient="records"),
        "socials": df_social.head(150).replace({np.nan: None}).to_dict(orient="records"),
        "hourly": df_hourly.replace({np.nan: None}).to_dict(orient="records"),
        "backtest_signals": df_bt.head(120).replace({np.nan: None}).to_dict(orient="records"),
    }

    data_js = "window.PUMP_ALPHA_DATA = " + json.dumps(dash_payload, ensure_ascii=False) + ";\n"
    (DASHBOARD_DIR / "dashboard_data.js").write_text(data_js, encoding="utf-8")

    html_content = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PUMPFUN ALPHA INTELLIGENCE — Research Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script src="dashboard_data.js"></script>
<style>
  :root {
    --bg: #0b0f19; --panel: #131a2a; --panel2: #1a2438; --border: #26334d;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #10b981; --blue: #3b82f6;
    --warn: #f59e0b; --danger: #ef4444; --purple: #8b5cf6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
  header { background: linear-gradient(90deg, #0f172a, #162036); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
  .brand h1 { font-size: 1.25rem; letter-spacing: 0.04em; color: #fff; display: flex; align-items: center; gap: 10px; }
  .badge { background: rgba(16,185,129,0.16); color: var(--accent); border: 1px solid rgba(16,185,129,0.35); padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }
  .meta-info { font-size: 0.78rem; color: var(--muted); text-align: right; }
  .filter-bar { background: var(--panel); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .f-group { display: flex; flex-direction: column; gap: 4px; }
  .f-group label { font-size: 0.7rem; text-transform: uppercase; color: var(--muted); font-weight: 600; letter-spacing: 0.04em; }
  select, input { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 0.82rem; }
  button.btn { background: var(--blue); color: #fff; border: none; border-radius: 6px; padding: 7px 14px; font-size: 0.82rem; font-weight: 600; cursor: pointer; }
  button.btn-sec { background: var(--panel2); border: 1px solid var(--border); }
  nav.tabs { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 24px 0; border-bottom: 1px solid var(--border); background: #0d1322; }
  .tab-btn { background: transparent; color: var(--muted); border: 1px solid transparent; border-bottom: none; padding: 9px 14px; font-size: 0.82rem; font-weight: 600; cursor: pointer; border-radius: 8px 8px 0 0; }
  .tab-btn.active { background: var(--panel); color: var(--accent); border-color: var(--border); }
  main { padding: 20px 24px; max-width: 1650px; margin: 0 auto; }
  .view { display: none; }
  .view.active { display: block; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 20px; }
  .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
  .kpi .lbl { font-size: 0.74rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em; }
  .kpi .val { font-size: 1.55rem; font-weight: 700; margin-top: 4px; color: #fff; }
  .kpi .sub { font-size: 0.75rem; color: var(--accent); margin-top: 2px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 20px; }
  @media(max-width: 1100px) { .grid-2 { grid-template-columns: 1fr; } }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 18px; }
  .card h3 { font-size: 0.95rem; margin-bottom: 12px; color: #f8fafc; display: flex; justify-content: space-between; align-items: center; }
  .table-wrap { overflow-x: auto; max-height: 460px; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid rgba(38,51,77,0.65); white-space: nowrap; }
  th { position: sticky; top: 0; background: #0f172a; color: var(--muted); font-weight: 600; z-index: 2; }
  tr:hover td { background: rgba(59,130,246,0.08); cursor: pointer; }
  .pill { padding: 2px 7px; border-radius: 4px; font-weight: 600; font-size: 0.72rem; }
  .p-green { background: rgba(16,185,129,0.18); color: #34d399; }
  .p-amber { background: rgba(245,158,11,0.18); color: #fbbf24; }
  .p-red { background: rgba(239,68,68,0.18); color: #f87171; }
  .p-blue { background: rgba(59,130,246,0.18); color: #60a5fa; }
  .heatmap-table td, .heatmap-table th { text-align: center; padding: 6px 4px; font-size: 0.73rem; }
  canvas { max-height: 320px; }
  svg#bubbleGraph { width: 100%; height: 340px; background: #090d16; border-radius: 8px; border: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1>PUMPFUN ALPHA INTELLIGENCE <span class="badge">SOLANA ON-CHAIN & EARLY SIGNAL ENGINE</span></h1>
  </div>
  <div class="meta-info" id="metaHeader">Ładowanie metadanych badania...</div>
</header>

<div class="filter-bar">
  <div class="f-group"><label>Data od (UTC)</label><input type="date" id="fDateFrom"></div>
  <div class="f-group"><label>Data do (UTC)</label><input type="date" id="fDateTo"></div>
  <div class="f-group"><label>Min. Mnożnik</label>
    <select id="fMult">
      <option value="0">Wszystkie (w tym Control)</option>
      <option value="2">>= 2x (Pump Events)</option>
      <option value="5">>= 5x</option>
      <option value="10">>= 10x</option>
      <option value="20">>= 20x</option>
      <option value="50">>= 50x</option>
    </select>
  </div>
  <div class="f-group"><label>Min. Płynność (USD)</label>
    <select id="fLiq">
      <option value="0">Dowolna</option>
      <option value="5000">>= $5,000</option>
      <option value="15000">>= $15,000</option>
      <option value="50000">>= $50,000</option>
    </select>
  </div>
  <div class="f-group"><label>Narracja</label><select id="fNarr"><option value="ALL">Wszystkie narracje</option></select></div>
  <div class="f-group"><label>Profil Pumpa</label><select id="fProf"><option value="ALL">Wszystkie profile</option></select></div>
  <div class="f-group"><label>Poziom Ryzyka Insider/Manip.</label>
    <select id="fRisk">
      <option value="ALL">Wszystkie poziomy</option>
      <option value="LOW">Niskie (< 35)</option>
      <option value="MED">Średnie (35 - 60)</option>
      <option value="HIGH">Wysokie (> 60)</option>
    </select>
  </div>
  <button class="btn" onclick="applyFilters()">Filtruj dane</button>
  <button class="btn btn-sec" onclick="resetFilters()">Reset</button>
</div>

<nav class="tabs">
  <button class="tab-btn active" onclick="switchView(1, this)">1. Market Overview</button>
  <button class="tab-btn" onclick="switchView(2, this)">2. Top Pumps</button>
  <button class="tab-btn" onclick="switchView(3, this)">3. Early Signals</button>
  <button class="tab-btn" onclick="switchView(4, this)">4. Wallet Intelligence</button>
  <button class="tab-btn" onclick="switchView(5, this)">5. Insider & Supply</button>
  <button class="tab-btn" onclick="switchView(6, this)">6. Social & Narratives</button>
  <button class="tab-btn" onclick="switchView(7, this)">7. Time & Market Patterns</button>
  <button class="tab-btn" onclick="switchView(8, this)">8. Model Performance</button>
</nav>

<main>
  <!-- VIEW 1 -->
  <section id="view-1" class="view active">
    <div class="kpi-grid" id="v1Kpis"></div>
    <div class="grid-2">
      <div class="card"><h3>Dzienna aktywność premier i pumpów (30 dni)</h3><canvas id="cDailyOverview"></canvas></div>
      <div class="card"><h3>Rozkład profili pumpów w próbie badawczej</h3><canvas id="cProfilesDist"></canvas></div>
    </div>
    <div class="card"><h3>Największe zweryfikowane wzrosty w oknie 30-dniowym (kliknij w zakładce Top Pumps po wykres świecowy)</h3><div class="table-wrap" id="v1TopTable"></div></div>
  </section>

  <!-- VIEW 2 -->
  <section id="view-2" class="view">
    <div class="grid-2">
      <div class="card"><h3 id="selectedCoinTitle">Wykres przebiegu ceny USD (wybierz token z tabeli)</h3><canvas id="cTokenPrice"></canvas></div>
      <div class="card"><h3>Porównanie: Mnożnik Rynkowy vs Zrealizowany po Poślizgu ($500)</h3><canvas id="cSlippageComp"></canvas></div>
    </div>
    <div class="card"><h3>Ranking Tokenów (z uwzględnieniem aktywnych filtrów)</h3><div class="table-wrap" id="v2Table"></div></div>
  </section>

  <!-- VIEW 3 -->
  <section id="view-3" class="view">
    <div class="card"><h3>TOP 10 Sygnałów Wczesnego Wykrywania (1–15 min życia tokena, przed głównym ruchem ceny)</h3><div class="table-wrap" id="v3Top10Signals"></div></div>
    <div class="card"><h3>Obserwacje w punkcie t = 5 min: Pump Potential Score vs Ryzyko Manipulacji & Podaży</h3><div class="table-wrap" id="v3EarlyTable"></div></div>
  </section>

  <!-- VIEW 4 -->
  <section id="view-4" class="view">
    <div class="grid-2">
      <div class="card"><h3>Mapa Klastrów Portfeli (Bubblemaps-style: rozmiar = % podaży, kolor = pewność dowodów)</h3><svg id="bubbleGraph"></svg></div>
      <div class="card"><h3>Wykryte Klastry Powiązanych Portfeli (On-Chain + Same-Block Bundles)</h3><div class="table-wrap" id="v4ClustersTable"></div></div>
    </div>
    <div class="card"><h3>Smart Money & Powtarzające się Portfele Wczesnych Nabywców (min. wielokrotne wejścia)</h3><div class="table-wrap" id="v4WalletsTable"></div></div>
  </section>

  <!-- VIEW 5 -->
  <section id="view-5" class="view">
    <div class="grid-2">
      <div class="card"><h3>Ewolucja Koncentracji Podaży w 7 Punktach Życia Tokena (Pumpy 5x+ vs Control)</h3><canvas id="cSupplyTraj"></canvas></div>
      <div class="card"><h3>Scenariusze Presji Sprzedażowej (1%, 5%, 10%, 25% podaży) & Insider Risk Score</h3><div class="table-wrap" id="v5RiskTable"></div></div>
    </div>
    <div class="card"><h3>Rekonstrukcja Zysków Klastrów Insiderów (Zysk Zrealizowany SOL vs Niezrealizowana Wycena Pozostałej Podaży)</h3><div class="table-wrap" id="v5ProfitTable"></div></div>
  </section>

  <!-- VIEW 6 -->
  <section id="view-6" class="view">
    <div class="grid-2">
      <div class="card"><h3>Skuteczność Narracji (Liczba Pumpów 5x+ oraz Odsetek Sukcesu)</h3><canvas id="cNarratives"></canvas></div>
      <div class="card"><h3>Statystyki Kategorii Narracyjnych</h3><div class="table-wrap" id="v6NarrTable"></div></div>
    </div>
    <div class="card"><h3>Analiza Społecznościowa, Viralność Nazw i Powiązania z Wydarzeniami Zewnętrznymi</h3><div class="table-wrap" id="v6SocialTable"></div></div>
  </section>

  <!-- VIEW 7 -->
  <section id="view-7" class="view">
    <div class="card">
      <h3>Heatmapa Prawdopodobieństwa Warunkowego Pumpa 5x+ (Dzień Tygodnia × Godzina)
        <span>
          <button class="btn btn-sec" onclick="renderHeatmap('warsaw')">Czas Polski (CET)</button>
          <button class="btn btn-sec" onclick="renderHeatmap('utc')">UTC</button>
        </span>
      </h3>
      <div class="table-wrap" id="v7Heatmap"></div>
    </div>
  </section>

  <!-- VIEW 8 -->
  <section id="view-8" class="view">
    <div class="kpi-grid" id="v8Kpis"></div>
    <div class="grid-2">
      <div class="card"><h3>Walk-Forward Out-of-Sample: Model vs 6 Benchmarków (Precision@10, Precision@20, ROC-AUC)</h3><canvas id="cBenchmarks"></canvas></div>
      <div class="card"><h3>Tabela Porównawcza Benchmarków (z uwzględnieniem kosztów i poślizgu)</h3><div class="table-wrap" id="v8BenchTable"></div></div>
    </div>
    <div class="card"><h3>Historia Sygnałów Out-of-Sample (Walk-Forward Backtest)</h3><div class="table-wrap" id="v8SignalsTable"></div></div>
    <div class="card"><h3>Wyniki Formalnego Testowania 35 Hipotez Badawczych (Korekta Benjamini-Hochberg FDR)</h3><div class="table-wrap" id="v8HypTable"></div></div>
  </section>
</main>

<script>
const D = window.PUMP_ALPHA_DATA;
let filteredTokens = [...D.tokens];
let charts = {};

function init() {
  document.getElementById('metaHeader').innerHTML =
    `Okno badawcze UTC: <b>${D.meta.research_window_start_utc.slice(0,16)}</b> → <b>${D.meta.research_window_end_utc.slice(0,16)}</b><br>` +
    `Czas Polski: <b>${D.meta.research_window_start_warsaw.slice(0,16)}</b> → <b>${D.meta.research_window_end_warsaw.slice(0,16)}</b>`;

  const narrs = [...new Set(D.tokens.map(t => t.narrative_category))].sort();
  const nSel = document.getElementById('fNarr');
  narrs.forEach(n => { const o = document.createElement('option'); o.value = n; o.textContent = n; nSel.appendChild(o); });

  const profs = [...new Set(D.tokens.map(t => t.pump_profile))].sort();
  const pSel = document.getElementById('fProf');
  profs.forEach(p => { const o = document.createElement('option'); o.value = p; o.textContent = p; pSel.appendChild(o); });

  renderStaticViews();
  applyFilters();
}

function switchView(n, btn) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + n).classList.add('active');
  btn.classList.add('active');
}

function riskPill(val) {
  const v = Number(val || 0);
  if (v >= 60) return `<span class="pill p-red">${v.toFixed(1)}</span>`;
  if (v >= 35) return `<span class="pill p-amber">${v.toFixed(1)}</span>`;
  return `<span class="pill p-green">${v.toFixed(1)}</span>`;
}

function applyFilters() {
  const dFrom = document.getElementById('fDateFrom').value;
  const dTo = document.getElementById('fDateTo').value;
  const minM = parseFloat(document.getElementById('fMult').value || '0');
  const minL = parseFloat(document.getElementById('fLiq').value || '0');
  const narr = document.getElementById('fNarr').value;
  const prof = document.getElementById('fProf').value;
  const risk = document.getElementById('fRisk').value;

  filteredTokens = D.tokens.filter(t => {
    const dt = (t.launch_utc || '').slice(0, 10);
    if (dFrom && dt && dt < dFrom) return false;
    if (dTo && dt && dt > dTo) return false;
    if ((t.reliable_market_multiple || 0) < minM) return false;
    if ((t.liquidity_usd || 0) < minL) return false;
    if (narr !== 'ALL' && t.narrative_category !== narr) return false;
    if (prof !== 'ALL' && t.pump_profile !== prof) return false;
    const maxR = Math.max(t.insider_supply_risk_score || 0, t.manipulation_risk_score || 0);
    if (risk === 'LOW' && maxR >= 35) return false;
    if (risk === 'MED' && (maxR < 35 || maxR > 60)) return false;
    if (risk === 'HIGH' && maxR <= 60) return false;
    return true;
  }).sort((a,b) => (b.reliable_market_multiple || 0) - (a.reliable_market_multiple || 0));

  renderDynamicViews();
}

function resetFilters() {
  document.getElementById('fDateFrom').value = '';
  document.getElementById('fDateTo').value = '';
  document.getElementById('fMult').value = '0';
  document.getElementById('fLiq').value = '0';
  document.getElementById('fNarr').value = 'ALL';
  document.getElementById('fProf').value = 'ALL';
  document.getElementById('fRisk').value = 'ALL';
  applyFilters();
}

function renderDynamicViews() {
  const totVol = filteredTokens.reduce((s, t) => s + (t.total_volume_usd || 0), 0);
  const pumpsCnt = filteredTokens.filter(t => (t.reliable_market_multiple || 0) >= 2).length;
  const u = D.summary.universe_counts;

  document.getElementById('v1Kpis').innerHTML = `
    <div class="kpi"><div class="lbl">Zebrane Uniwersum Pump.fun</div><div class="val">${u.total_tokens.toLocaleString()}</div><div class="sub">Grupa A (Nowe 30d): ${u.group_a_new_30d.toLocaleString()}</div></div>
    <div class="kpi"><div class="lbl">Aktywny Filtr (Kohorta Głęboka)</div><div class="val">${filteredTokens.length} / ${u.deep_cohort_total}</div><div class="sub">Pumpy >=2x w filtrze: ${pumpsCnt}</div></div>
    <div class="kpi"><div class="lbl">Skumulowany Wolumen Kohorty</div><div class="val">$${(totVol/1e6).toFixed(2)}M</div><div class="sub">Grupa Kontrolna: ${u.matched_controls_cohort} tokenów</div></div>
    <div class="kpi"><div class="lbl">Max Zweryfikowany Mnożnik</div><div class="val">${filteredTokens.length ? filteredTokens[0].reliable_market_multiple.toFixed(1)+'x' : '-'}</div><div class="sub">${filteredTokens.length ? filteredTokens[0].symbol : ''}</div></div>
  `;

  const topRows = filteredTokens.slice(0, 60).map((t, i) => `
    <tr onclick="plotCoin('${t.mint}')">
      <td>${i+1}</td><td><b>${t.symbol || '-'}</b></td><td>${(t.name || '').slice(0,24)}</td>
      <td><span class="pill p-green">${(t.reliable_market_multiple||1).toFixed(2)}x</span></td>
      <td>${(t.realizable_liquidity_adj_multiple||1).toFixed(2)}x</td>
      <td>$${Number(t.max_mcap_usd||0).toLocaleString()}</td>
      <td>$${Number(t.liquidity_usd||0).toLocaleString()}</td>
      <td>$${Number(t.total_volume_usd||0).toLocaleString()}</td>
      <td>${t.unique_buyers_30m || 0}</td>
      <td>${t.time_to_ath_min || '-'}m</td>
      <td>${t.narrative_category}</td>
      <td>${riskPill(t.insider_supply_risk_score)}</td>
      <td>${riskPill(t.manipulation_risk_score)}</td>
    </tr>`).join('');

  const tblHead = `<table><thead><tr><th>#</th><th>Ticker</th><th>Nazwa</th><th>Mnożnik Rynkowy</th><th>Mnożnik Po Poślizgu</th><th>Max Mcap</th><th>Płynność</th><th>Wolumen</th><th>Kupujący 30m</th><th>Czas ATH</th><th>Narracja</th><th>Insider Risk</th><th>Manip. Risk</th></tr></thead><tbody>${topRows}</tbody></table>`;
  document.getElementById('v1TopTable').innerHTML = tblHead;
  document.getElementById('v2Table').innerHTML = tblHead;

  // Profile chart
  const pCounts = {};
  filteredTokens.forEach(t => { pCounts[t.pump_profile] = (pCounts[t.pump_profile] || 0) + 1; });
  if (charts.prof) charts.prof.destroy();
  charts.prof = new Chart(document.getElementById('cProfilesDist'), {
    type: 'bar',
    data: { labels: Object.keys(pCounts), datasets: [{ label: 'Liczba tokenów', data: Object.values(pCounts), backgroundColor: '#3b82f6' }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#e2e8f0', font: { size: 10 } } } } }
  });

  // Slippage comparison top 12
  const top12 = filteredTokens.slice(0, 12);
  if (charts.slip) charts.slip.destroy();
  charts.slip = new Chart(document.getElementById('cSlippageComp'), {
    type: 'bar',
    data: {
      labels: top12.map(t => t.symbol),
      datasets: [
        { label: 'Mnożnik Rynkowy', data: top12.map(t => t.reliable_market_multiple), backgroundColor: '#10b981' },
        { label: 'Mnożnik Zrealizowany ($500 exit)', data: top12.map(t => t.realizable_liquidity_adj_multiple), backgroundColor: '#3b82f6' }
      ]
    },
    options: { scales: { x: { ticks: { color: '#e2e8f0' } }, y: { ticks: { color: '#94a3b8' } } } }
  });

  const firstWithCandles = filteredTokens.find(t => D.candle_series_top[t.mint]);
  if (firstWithCandles) plotCoin(firstWithCandles.mint);
}

function plotCoin(mint) {
  const ser = D.candle_series_top[mint];
  const tok = D.tokens.find(t => t.mint === mint);
  if (!ser || !ser.length) return;
  document.getElementById('selectedCoinTitle').textContent = `Przebieg ceny USD: ${tok ? tok.symbol + ' (' + tok.name + ')' : mint.slice(0,8)}`;
  if (charts.price) charts.price.destroy();
  charts.price = new Chart(document.getElementById('cTokenPrice'), {
    type: 'line',
    data: {
      labels: ser.map(x => x.t),
      datasets: [{ label: 'Cena USD', data: ser.map(x => x.c), borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.12)', fill: true, tension: 0.2 }]
    },
    options: { scales: { x: { ticks: { color: '#94a3b8', maxTicksLimit: 8 } }, y: { ticks: { color: '#94a3b8' } } } }
  });
}

function renderStaticViews() {
  // Daily chart
  charts.daily = new Chart(document.getElementById('cDailyOverview'), {
    type: 'bar',
    data: {
      labels: D.daily_overview.map(d => d.date.slice(5)),
      datasets: [
        { label: 'Nowe tokeny w próbie', data: D.daily_overview.map(d => d.new_tokens), backgroundColor: 'rgba(59,130,246,0.5)' },
        { label: 'Pumpy >=2x', data: D.daily_overview.map(d => d.pumps_2x), backgroundColor: '#10b981' }
      ]
    },
    options: { scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } }
  });

  // View 3: Top 10 Signals & 5m Early table
  document.getElementById('v3Top10Signals').innerHTML = `<table><thead><tr><th>Sygnał (1–15 min)</th><th>Okno</th><th>Liczba Obserwacji</th><th>Skuteczność 3x+</th><th>Lift vs Baza</th><th>Mediana Mnożnika Po Sygnale</th><th>Max Obsunięcie (Mediana)</th><th>Dowód</th><th>Odporność na Manipulację</th></tr></thead><tbody>` +
    D.summary.top_10_early_signals.map(s => `<tr><td><b>${s.signal_name}</b></td><td>${s.availability_window}</td><td>${s.n_tokens_triggered}</td><td><span class="pill p-green">${(s.hit_rate_future_3x*100).toFixed(1)}%</span></td><td><b>${s.lift_vs_baseline}x</b></td><td>${s.median_future_multiple}x</td><td>${s.median_max_drawdown_pct}%</td><td><span class="pill p-blue">${s.evidence_grade}</span></td><td>${s.manipulation_resilience_and_risk}</td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v3EarlyTable').innerHTML = `<table><thead><tr><th>Ticker</th><th>Pump Potential (5m)</th><th>Manip. Risk</th><th>Insider Risk</th><th>Niezależni Kupujący</th><th>Przyspieszenie Kupujących</th><th>Buy/Sell USD</th><th>Dotychczasowy Ruch</th><th>Przyszły Max Mnożnik (po 5m!)</th></tr></thead><tbody>` +
    D.early_5m.slice(0, 80).map(e => `<tr><td><b>${e.symbol || '-'}</b></td><td><span class="pill p-green">${e.pump_potential_score}</span></td><td>${riskPill(e.realtime_manipulation_risk)}</td><td>${riskPill(e.realtime_insider_risk)}</td><td>${e.independent_buyers_cum}</td><td>${Number(e.buyer_acceleration_ratio).toFixed(2)}x</td><td>${Number(e.buy_sell_usd_ratio).toFixed(2)}</td><td>${e.already_moved_multiple}x</td><td><b>${e.future_max_multiple_from_signal}x</b></td></tr>`).join('') + `</tbody></table>`;

  // View 4: Bubblemaps SVG + Clusters + Smart Money
  const svg = document.getElementById('bubbleGraph');
  const topCl = D.clusters.slice(0, 22);
  let svgHtml = '';
  topCl.forEach((c, idx) => {
    const cols = 6;
    const cx = 75 + (idx % cols) * 115 + (idx % 2)*12;
    const cy = 60 + Math.floor(idx / cols) * 78;
    const r = Math.max(12, Math.min(34, 10 + Math.sqrt(c.accumulated_supply_pct || 1) * 4.5));
    const col = c.confidence_level === 'HIGH' ? '#ef4444' : '#f59e0b';
    svgHtml += `<line x1="${cx}" y1="${cy}" x2="${cx+18}" y2="${cy-14}" stroke="${col}" stroke-opacity="0.55" stroke-width="1.5"/>`;
    svgHtml += `<circle cx="${cx+18}" cy="${cy-14}" r="${Math.max(5, r*0.38)}" fill="${col}" fill-opacity="0.35" stroke="${col}"/>`;
    svgHtml += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${col}" fill-opacity="0.28" stroke="${col}" stroke-width="2"><title>${c.symbol} (${c.cluster_id}): ${c.accumulated_supply_pct}% podaży, ${c.wallets_count} portfeli, ${c.dominant_link_type}</title></circle>`;
    svgHtml += `<text x="${cx}" y="${cy+4}" text-anchor="middle" fill="#fff" font-size="9" font-weight="bold">${(c.symbol||'').slice(0,6)}</text>`;
  });
  svg.setAttribute('viewBox', '0 0 740 330');
  svg.innerHTML = svgHtml;

  document.getElementById('v4ClustersTable').innerHTML = `<table><thead><tr><th>Klaster</th><th>Ticker</th><th>Portfele</th><th>Typ Powiązania</th><th>Pewność</th><th>Zgromadzona Podaż %</th><th>Zatrzymana Podaż %</th><th>Alternatywne Wyjaśnienie</th></tr></thead><tbody>` +
    D.clusters.slice(0, 60).map(c => `<tr><td>${c.cluster_id}</td><td><b>${c.symbol}</b></td><td>${c.wallets_count}</td><td>${c.dominant_link_type}</td><td><span class="pill ${c.confidence_level==='HIGH'?'p-red':'p-amber'}">${c.confidence_level}</span></td><td>${c.accumulated_supply_pct}%</td><td>${c.retained_supply_pct}%</td><td>${c.alternative_explanation}</td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v4WalletsTable').innerHTML = `<table><thead><tr><th>Portfel</th><th>Klasyfikacja</th><th>Smart Money Score</th><th>Tokeny</th><th>Wczesne Wejścia</th><th>Przed Pumpem</th><th>Hit Rate</th><th>Mediana Mnożnika</th><th>Zrealizowane Netto SOL</th></tr></thead><tbody>` +
    D.wallets.slice(0, 80).map(w => `<tr><td><code>${w.wallet.slice(0,6)}...${w.wallet.slice(-4)}</code></td><td>${w.participant_class}</td><td><span class="pill p-green">${w.smart_money_score}</span></td><td>${w.tokens_analyzed}</td><td>${w.early_entries_top25}</td><td>${w.pre_pump_entries}</td><td>${(w.pre_pump_hit_rate*100).toFixed(0)}%</td><td>${w.median_max_multiple_after_entry}x</td><td>${w.observed_net_sol_flow} SOL</td></tr>`).join('') + `</tbody></table>`;

  // View 5: Supply Trajectory + Risk + Profits
  const cps = ["1_launch","2_pre_pump_early","3_pump_onset","4_peak_volume","5_ath","6_post_ath","7_latest"];
  const sPump = cps.map(cp => (D.supply_trajectory.find(x => x.checkpoint===cp && x.grp_type==='Pumps_5x')||{}).top10_pct || 0);
  const sCtrl = cps.map(cp => (D.supply_trajectory.find(x => x.checkpoint===cp && x.grp_type==='Controls')||{}).top10_pct || 0);
  charts.sup = new Chart(document.getElementById('cSupplyTraj'), {
    type: 'line',
    data: {
      labels: ['Start','Pre-Pump','Onset','Szczyt Wol.','ATH','Po ATH','Ostatni'],
      datasets: [
        { label: 'TOP 10 Holderów % — Pumpy 5x+', data: sPump, borderColor: '#10b981', tension: 0.25 },
        { label: 'TOP 10 Holderów % — Control Group', data: sCtrl, borderColor: '#ef4444', tension: 0.25 }
      ]
    },
    options: { scales: { x: { ticks: { color: '#e2e8f0' } }, y: { ticks: { color: '#94a3b8' } } } }
  });

  document.getElementById('v5RiskTable').innerHTML = `<table><thead><tr><th>Ticker</th><th>Insider Risk</th><th>Manip. Risk</th><th>Insider Peak %</th><th>Insider Teraz %</th><th>Wpływ Zrzutu 1%</th><th>Wpływ 5%</th><th>Wpływ 10%</th><th>Wpływ 25%</th></tr></thead><tbody>` +
    D.insider_risk.slice(0, 70).map(r => `<tr><td><b>${r.symbol}</b></td><td>${riskPill(r.insider_supply_risk_score)}</td><td>${riskPill(r.manipulation_risk_score)}</td><td>${r.potential_insiders_peak_pct}%</td><td>${r.potential_insiders_retained_pct}%</td><td>-${r.sell_impact_1pct_supply_pct}%</td><td>-${r.sell_impact_5pct_supply_pct}%</td><td>-${r.sell_impact_10pct_supply_pct}%</td><td>-${r.sell_impact_25pct_supply_pct}%</td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v5ProfitTable').innerHTML = `<table><thead><tr><th>Klaster</th><th>Ticker</th><th>Wydane SOL</th><th>Uzyskane SOL</th><th>Zrealizowany Zysk SOL</th><th>Zatrzymana Podaż %</th><th>Niezrealizowana Wycena (nie zysk!)</th><th>Wzorzec Retencji</th></tr></thead><tbody>` +
    D.insider_profits.slice(0, 60).map(p => `<tr><td>${p.cluster_id}</td><td><b>${p.symbol}</b></td><td>${p.sol_spent_buys}</td><td>${p.sol_received_sells}</td><td><span class="pill ${p.realized_profit_sol>=0?'p-green':'p-red'}">${p.realized_profit_sol} SOL</span></td><td>${p.retained_supply_pct}%</td><td>$${Number(p.unrealized_mtm_usd_not_realized||0).toLocaleString()}</td><td>${p.retention_pattern}</td></tr>`).join('') + `</tbody></table>`;

  // View 6: Narratives & Socials
  charts.narr = new Chart(document.getElementById('cNarratives'), {
    type: 'bar',
    data: {
      labels: D.narratives.map(n => n.narrative_category),
      datasets: [{ label: 'Pumpy 5x+', data: D.narratives.map(n => n.pumps_5x), backgroundColor: '#8b5cf6' }]
    },
    options: { indexAxis: 'y', scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#e2e8f0', font: { size: 10 } } } } }
  });

  document.getElementById('v6NarrTable').innerHTML = `<table><thead><tr><th>Narracja</th><th>Próba</th><th>Pumpy 5x+</th><th>Skuteczność 5x+</th><th>Mediana Mnożnika</th><th>Śr. Kupujących 15m</th></tr></thead><tbody>` +
    D.narratives.map(n => `<tr><td><b>${n.narrative_category}</b></td><td>${n.count}</td><td>${n.pumps_5x}</td><td>${(n.rate_5x*100).toFixed(1)}%</td><td>${Number(n.median_mult).toFixed(2)}x</td><td>${Number(n.avg_buyers_15m).toFixed(1)}</td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v6SocialTable').innerHTML = `<table><thead><tr><th>Ticker</th><th>Narracja</th><th>X na starcie</th><th>Typ X</th><th>First-Mover</th><th>Shareability</th><th>Wydarzenie Zewnętrzne</th><th>Mnożnik</th></tr></thead><tbody>` +
    D.socials.slice(0, 70).map(s => `<tr><td><b>${s.symbol}</b></td><td>${s.narrative_category}</td><td>${s.has_twitter_at_launch?'TAK':'NIE'}</td><td>${s.twitter_link_type}</td><td>${s.is_ticker_first_mover?'TAK':'Klon'}</td><td>${s.meme_shareability_score}</td><td>${s.external_event_alignment}</td><td>${s.reliable_multiple}x</td></tr>`).join('') + `</tbody></table>`;

  // View 7: Heatmap default Polish time
  renderHeatmap('warsaw');

  // View 8: Model Performance & 35 Hypotheses
  const bm = D.summary.backtest_benchmarks_walk_forward;
  const bestM = bm[0];
  document.getElementById('v8Kpis').innerHTML = `
    <div class="kpi"><div class="lbl">Precision@10 (Walk-Forward OOS)</div><div class="val">${(bestM.precision_at_10*100).toFixed(1)}%</div><div class="sub">Lift vs Losowy: ${bestM.lift_at_10}x</div></div>
    <div class="kpi"><div class="lbl">Precision@20 (Walk-Forward OOS)</div><div class="val">${(bestM.precision_at_20*100).toFixed(1)}%</div><div class="sub">Lift vs Baza: ${bestM.lift_at_20}x</div></div>
    <div class="kpi"><div class="lbl">ROC-AUC / Brier Calibration</div><div class="val">${bestM.roc_auc}</div><div class="sub">Brier OOS: ${D.summary.brier_score_oos}</div></div>
    <div class="kpi"><div class="lbl">Śr. Wynik Netto Po Kosztach (Top 20)</div><div class="val">${bestM.top20_mean_net_return_after_costs_pct}%</div><div class="sub">Po odjęciu poślizgu i opłat DEX</div></div>
  `;

  charts.bm = new Chart(document.getElementById('cBenchmarks'), {
    type: 'bar',
    data: {
      labels: bm.map(b => b.strategy.replace(/^[0-9]_/, '').slice(0, 24)),
      datasets: [
        { label: 'Precision@10', data: bm.map(b => b.precision_at_10), backgroundColor: '#10b981' },
        { label: 'Precision@20', data: bm.map(b => b.precision_at_20), backgroundColor: '#3b82f6' },
        { label: 'ROC-AUC', data: bm.map(b => b.roc_auc), backgroundColor: '#f59e0b' }
      ]
    },
    options: { scales: { x: { ticks: { color: '#e2e8f0', font: { size: 10 } } }, y: { ticks: { color: '#94a3b8' } } } }
  });

  document.getElementById('v8BenchTable').innerHTML = `<table><thead><tr><th>Strategia / Benchmark</th><th>Precision@10</th><th>Precision@20</th><th>Lift@10</th><th>Recall@Top25%</th><th>ROC-AUC</th><th>Śr. Zwrot Netto Po Kosztach (Top20)</th></tr></thead><tbody>` +
    bm.map(b => `<tr><td><b>${b.strategy}</b></td><td>${(b.precision_at_10*100).toFixed(1)}%</td><td>${(b.precision_at_20*100).toFixed(1)}%</td><td><b>${b.lift_at_10}x</b></td><td>${(b.recall_at_top25pct*100).toFixed(1)}%</td><td>${b.roc_auc}</td><td>${b.top20_mean_net_return_after_costs_pct}%</td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v8SignalsTable').innerHTML = `<table><thead><tr><th>Rank OOS</th><th>Czas Sygnału UTC</th><th>Ticker</th><th>Potential Score</th><th>Manip. Risk</th><th>Insider Risk</th><th>Max Mnożnik Po Sygnale</th><th>Zwrot 1h</th><th>Zwrot 4h</th><th>Wynik Netto Po Kosztach</th></tr></thead><tbody>` +
    D.backtest_signals.slice(0, 60).map(s => `<tr><td>${s.oos_rank}</td><td>${s.signal_timestamp_utc}</td><td><b>${s.symbol}</b></td><td><span class="pill p-green">${s.pump_potential_score}</span></td><td>${riskPill(s.manipulation_risk_score)}</td><td>${riskPill(s.insider_supply_risk_score)}</td><td><b>${s.max_multiple_post_signal}x</b></td><td>${s.ret_1h_pct}%</td><td>${s.ret_4h_pct}%</td><td><span class="pill ${s.net_strategy_return_after_costs_pct>=0?'p-green':'p-red'}">${s.net_strategy_return_after_costs_pct}%</span></td></tr>`).join('') + `</tbody></table>`;

  document.getElementById('v8HypTable').innerHTML = `<table><thead><tr><th>ID</th><th>Kategoria</th><th>Hipoteza Badawcza</th><th>Mediana Zwycięzcy</th><th>Mediana Control</th><th>Cliff's d</th><th>q-value (FDR)</th><th>Siła Dowodu</th></tr></thead><tbody>` +
    D.summary.hypotheses_35.map(h => `<tr><td><b>${h.id}</b></td><td>${h.category}</td><td>${h.question}</td><td>${h.median_winners}</td><td>${h.median_controls}</td><td>${h.effect_size_cliffs_d}</td><td>${h.q_value_bh_fdr}</td><td><span class="pill ${h.evidence_grade==='A'?'p-green':(h.evidence_grade==='B'?'p-blue':(h.evidence_grade==='C'?'p-amber':'p-red'))}">${h.evidence_grade}</span></td></tr>`).join('') + `</tbody></table>`;
}

function renderHeatmap(mode) {
  const days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
  const dayPl = {'Monday':'Pon','Tuesday':'Wt','Wednesday':'Śr','Thursday':'Czw','Friday':'Pt','Saturday':'Sob','Sunday':'Niedz'};
  const hrs = Array.from({length:24}, (_,i)=>i);
  let html = `<table class="heatmap-table"><thead><tr><th>Dzień \\ Godz (${mode==='warsaw'?'PL CET':'UTC'})</th>` + hrs.map(h=>`<th>${String(h).padStart(2,'0')}</th>`).join('') + `</tr></thead><tbody>`;
  days.forEach(d => {
    html += `<tr><th>${dayPl[d]}</th>`;
    hrs.forEach(h => {
      const rec = D.hourly.find(x => x.weekday_name===d && (mode==='warsaw' ? x.hour_warsaw_cet===h : x.hour_utc===h));
      const p = rec ? Number(rec.prob_pump_5x || 0) : 0;
      const n = rec ? rec.total_launches_sampled : 0;
      const alpha = Math.min(0.85, Math.max(0.06, p * 1.35));
      html += `<td style="background: rgba(16,185,129,${alpha})" title="${dayPl[d]} ${h}:00 — P(5x+)=${(p*100).toFixed(1)}% (n=${n})">${n ? (p*100).toFixed(0)+'%' : '-'}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;
  document.getElementById('v7Heatmap').innerHTML = html;
}

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""
    (DASHBOARD_DIR / "index.html").write_text(html_content, encoding="utf-8")

    serve_py = """import http.server, socketserver, webbrowser
from pathlib import Path

PORT = 8765
DIRECTORY = Path(__file__).parent

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/index.html"
        print(f"Serving PUMPFUN ALPHA INTELLIGENCE Dashboard at {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()
"""
    (DASHBOARD_DIR / "serve_dashboard.py").write_text(serve_py, encoding="utf-8")
    logger.info("Dashboard files written to dashboard/index.html and dashboard/serve_dashboard.py.")

if __name__ == "__main__":
    build_excel_workbook()
    build_dashboard()
