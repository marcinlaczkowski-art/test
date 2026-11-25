"""
STEP 3 (V2.1 — SECTION 4 HIGH-COMPLETENESS OUT-OF-TIME TEST & SECTION 10 PAPER TRADING):
Fixes V2's low OOT completeness (21/100) and empty OOT tracker drift!

1. Loads the populated chronological `UnifiedStateBundle` checkpoint (`state_post_wf_v2_1.json`)
   and frozen models (`v1_frozen_model.json`, `v2_frozen_model.json`, `v2_1_frozen_model.json`).
   ZERO refitting or parameter changes!
2. Harvests candles & trades politely (`Semaphore(3)` + 429 retry backoff + incremental cache) for
   220 strictly unseen chronological tokens:
   - 190 consecutive held-out chronological emissions strictly AFTER V2's cutoff (`>10h` elapsed ->
     BOTH `1h` and `4h` horizons 100% elapsed!),
   - 30 fresh `2026-11-25` morning emissions (~75–100m elapsed -> `1h` complete, `4h` & `24h` `"censored"`).
   Zero filtering by ATH, mcap, migration, or volume!
3. Evaluates via the EXACT SAME `UnifiedFeatureEngine` (`mode="oot"`) across all 9 targets:
   `hit_2x_1h`, `hit_3x_1h`, `hit_2x_4h`, `hit_3x_4h`, `hit_5x_4h`,
   `hit_2x_24h`, `hit_3x_24h`, `hit_5x_24h`, `hit_10x_24h`,
   with separate `complete` / `censored` / `unknown` denominators, Wilson 95% CIs, and explicit
   `INCONCLUSIVE` flags whenever sample/positive power is insufficient (`positives < 10`).
4. Runs `run_paper_trading_scan_v2_1()` (`paper_trading/paper_alerts_v2_1.csv`).
"""
import asyncio
import aiohttp
import json
import math
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

from config_v2_1 import (
    V1_DIR, V2_DIR, V2_1_DIR, OOT_V2_1_DIR, CHECKPOINTS_DIR,
    FROZEN_BASELINES_DIR, SNAPSHOTS_DIR, LOGS_DIR,
    PUMPFUN_V3_BASE, BINANCE_BASE, SOLANA_CHAIN_ID, INTERVAL_MS,
)
from state_trackers_v2_1 import UnifiedStateBundle
from feature_engine import (
    UnifiedFeatureEngine,
    classify_token_narrative,
    deduplicate_and_filter_trades_before,
    build_token_technical_set,
)
from execution_and_backtest_v2_1 import (
    compute_multi_horizon_labels_and_path,
    simulate_amm_position_execution,
    compute_binary_ranking_metrics,
    score_frozen_v1_on_snapshot,
    score_frozen_v2_on_snapshot,
)
from paper_trader_v2_1 import HEADERS, fetch_polite_json, score_v2_1_frozen, run_paper_trading_scan_v2_1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step3_oot_and_paper_v2_1.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("v2_1_step3")

OOT_CANDLES_DIR = OOT_V2_1_DIR / "candles"
OOT_TRADES_DIR = OOT_V2_1_DIR / "trades"
OOT_CANDLES_DIR.mkdir(parents=True, exist_ok=True)
OOT_TRADES_DIR.mkdir(parents=True, exist_ok=True)


def wilson_ci_95(successes: int, total: int) -> tuple:
    """Exact Wilson score 95% confidence interval for a binomial proportion."""
    if total <= 0:
        return (None, None)
    z = 1.959964
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


async def harvest_single_oot_token(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    coin: dict,
    collection_ms: int,
):
    mint = coin["mint"]
    cts = int(coin["created_timestamp"])
    cp = OOT_CANDLES_DIR / f"{mint}.json"
    tp = OOT_TRADES_DIR / f"{mint}.json"

    need_c = True
    if cp.exists():
        c_existing = json.loads(cp.read_text(encoding="utf-8"))
        if c_existing.get("api_ok") == 1 and int(c_existing.get("collection_timestamp_ms") or 0) >= cts + 4 * 3_600_000 + 200_000:
            need_c = False

    if need_c:
        to_1m = min(collection_ms, cts + 260 * 60_000)
        to_15m = min(collection_ms, cts + 28 * 3_600_000)
        r_1m, r_15m = await asyncio.gather(
            fetch_polite_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={to_1m}", sem, retries=5),
            fetch_polite_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=15m&to={to_15m}", sem, retries=5),
        )
        c_payload = {
            "mint": mint,
            "collection_timestamp_ms": collection_ms,
            "candles_1m": sorted((r_1m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
            "candles_15m": sorted((r_15m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
            "candles_4h": [],
            "api_ok": int(r_1m is not None or r_15m is not None),
        }
        cp.write_text(json.dumps(c_payload), encoding="utf-8")

    if not tp.exists():
        cursor_key = f"1-0-0-{max(0, cts - 10_000)}"
        trades_acc = []
        for page in range(2):
            r_tr = await fetch_polite_json(
                session,
                f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after={cursor_key}",
                sem,
                retries=5,
            )
            batch = (r_tr or {}).get("trades", [])
            if not batch:
                break
            trades_acc.extend(batch)
            cursor_key = batch[-1]["ordinalKey"]
            if len(batch) < 100:
                break
        tp.write_text(json.dumps({
            "mint": mint,
            "collection_timestamp_ms": collection_ms,
            "trades": trades_acc,
            "early_30m_pagination_truncated": False,
        }), encoding="utf-8")


async def main():
    t0 = time.time()
    logger.info("=== STEP 3 V2.1: HIGH-COMPLETENESS UNSEEN OOT EVALUATION & PAPER TRADING ===")

    # 1. Load frozen baselines & populated chronological UnifiedStateBundle checkpoint!
    v1_frozen = json.loads((FROZEN_BASELINES_DIR / "v1_frozen_model.json").read_text(encoding="utf-8"))
    v2_frozen = json.loads((FROZEN_BASELINES_DIR / "v2_frozen_model.json").read_text(encoding="utf-8"))
    v2_1_frozen = json.loads((FROZEN_BASELINES_DIR / "v2_1_frozen_model.json").read_text(encoding="utf-8"))
    state = UnifiedStateBundle.load_checkpoint(CHECKPOINTS_DIR / "state_post_wf_v2_1.json")

    train_ds = json.loads((V2_DIR / "cache" / "raw" / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    seen_train_mints = {x["mint"] for x in train_ds["tokens"]}
    max_train_cts = max(int(x["created_timestamp"]) for x in train_ds["tokens"])

    # Also ensure zero overlap with V1's deep cohort (`BACKTEST_RESULTS.csv` & `EARLY_SIGNALS.csv`)!
    v1_deep_mints = set()
    for v1_fn in ("BACKTEST_RESULTS.csv", "EARLY_SIGNALS.csv"):
        v1_p = V1_DIR / v1_fn
        if v1_p.exists():
            df_v1_sub = pd.read_csv(v1_p, usecols=["mint"])
            v1_deep_mints.update(df_v1_sub["mint"].dropna().astype(str))
    forbidden_mints = seen_train_mints | v1_deep_mints

    # Select 190 consecutive strictly unseen chronological emissions after `max_train_cts` (`>10h` elapsed -> complete 1h & 4h!)
    v1_univ = json.loads((V1_DIR / "cache" / "raw" / "pumpfun_universe_raw.json").read_text(encoding="utf-8"))
    univ_items = v1_univ if isinstance(v1_univ, list) else list(v1_univ.values())
    heldout_candidates = sorted(
        [
            c for c in univ_items
            if isinstance(c, dict)
            and c.get("_discovery_source") == "sweep_created_timestamp_None"
            and c.get("mint") not in forbidden_mints
            and int(c.get("created_timestamp") or 0) > max_train_cts
        ],
        key=lambda x: (int(x["created_timestamp"]), x["mint"]),
    )[:190]

    sem = asyncio.Semaphore(3)
    conn = aiohttp.TCPConnector(limit=8, ssl=False, force_close=True)
    collection_ms = int(time.time() * 1000)

    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        # Refresh strictly closed SOL 1h bars up to `collection_ms`
        kl = await fetch_polite_json(session, f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&limit=48", sem)
        if isinstance(kl, list) and kl:
            state.market.ingest_binance_klines(kl, interval="1h")

        # Also pull 30 fresh live `2026-11-25` morning emissions (~75–110m old -> 1h complete, 4h & 24h censored!)
        live_morning = []
        for off in (1350, 1420):
            batch = await fetch_polite_json(
                session,
                f"{PUMPFUN_V3_BASE}/coins?offset={off}&limit=25&sort=created_timestamp&order=DESC&includeNsfw=true",
                sem,
            )
            if isinstance(batch, list):
                for c in batch:
                    m = c.get("mint")
                    if m and m not in forbidden_mints and m not in {x["mint"] for x in heldout_candidates}:
                        live_morning.append(c)
        live_morning = sorted(live_morning, key=lambda x: int(x.get("created_timestamp") or 0))[:30]

        oot_tokens = sorted(heldout_candidates + live_morning, key=lambda x: (int(x["created_timestamp"]), x["mint"]))
        logger.info(f"Polite OOT harvest starting for {len(oot_tokens)} strictly unseen chronological tokens (sem=3)...")

        for i in range(0, len(oot_tokens), 12):
            chunk = oot_tokens[i:i+12]
            await asyncio.gather(*[harvest_single_oot_token(session, sem, c, collection_ms) for c in chunk])
            if (i + 12) % 48 == 0 or (i + 12) >= len(oot_tokens):
                logger.info(f"OOT harvest progress: {min(i+12, len(oot_tokens))}/{len(oot_tokens)} ({time.time()-t0:.1f}s)")
            await asyncio.sleep(0.15)

    # 2. Evaluate all unseen OOT tokens chronologically via the EXACT SAME `UnifiedFeatureEngine`!
    engine = UnifiedFeatureEngine(save_snapshots_dir=SNAPSHOTS_DIR)
    oot_rows = []
    oot_eval_objs = []

    for idx, coin in enumerate(oot_tokens):
        mint = coin["mint"]
        assert mint not in forbidden_mints, f"CRITICAL: Token {mint} overlapped with Train/V1!"
        cts = int(coin["created_timestamp"])
        sig_ts = cts + 180_000  # Fixed 3-minute causal signal point

        cp = OOT_CANDLES_DIR / f"{mint}.json"
        tp = OOT_TRADES_DIR / f"{mint}.json"
        c_obj = json.loads(cp.read_text(encoding="utf-8"))
        t_obj = json.loads(tp.read_text(encoding="utf-8"))
        c1m = c_obj.get("candles_1m") or []
        trades = t_obj.get("trades") or []

        narr_cat = classify_token_narrative(coin.get("name"), coin.get("symbol"), coin.get("description"))
        state.tickers.register_launch(cts, mint, coin.get("symbol") or "", narr_cat)

        snap = engine.compute_snapshot(
            coin=coin,
            trades=trades,
            candles_1m=c1m,
            signal_ts_ms=sig_ts,
            state=state,
            mode="oot",
            acquired_at_ms=sig_ts,
            persist_json=(idx < 5),
        )
        lbl = compute_multi_horizon_labels_and_path(
            coin=coin,
            trades=trades,
            candles_obj=c_obj,
            signal_ts_ms=sig_ts,
            entry_price_usd=snap["entry_price_usd"],
            entry_price_quote_sol=snap["entry_price_quote_sol"],
            sol_price_usd_at_sig=snap["sol_price_usd_at_signal"],
        )
        ex_025 = simulate_amm_position_execution(snap, lbl, pos_sol=0.25)
        ex_100 = simulate_amm_position_execution(snap, lbl, pos_sol=1.0)

        # Register completed 4h outcomes ONLY at `sig_ts + 4h` so future OOT tokens >4h later see them causally!
        cutoff_4h = sig_ts + INTERVAL_MS["4h"]
        cr = coin.get("creator") or ""
        if lbl.get("status_4h") == "complete" and isinstance(lbl.get("hit_2x_4h"), int):
            if cr:
                state.creators.register_event(cr, mint, cts, cutoff_4h, int(lbl["hit_2x_4h"]), outcome_status="complete")
            tok_tech = build_token_technical_set(coin, trades)
            for tr in deduplicate_and_filter_trades_before(trades, sig_ts):
                if tr.get("side") == "buy":
                    w = str((tr.get("trader") or {}).get("address") or "")
                    if w and w not in tok_tech:
                        state.wallets.register_wallet_token_outcome(w, mint, sig_ts, cutoff_4h, int(lbl["hit_2x_4h"]), 0.0, True)

        mv = snap["model_vector"]
        sc_v21_pruned = score_v2_1_frozen(snap, v2_1_frozen, use_pruned=True) / 100.0
        sc_v21_full = score_v2_1_frozen(snap, v2_1_frozen, use_pruned=False) / 100.0
        sc_v2_froz = score_frozen_v2_on_snapshot(snap, v2_frozen)
        sc_v1_froz = score_frozen_v1_on_snapshot(snap, v1_frozen)
        sc_ind_growth = mv["independent_buyer_velocity"] * mv["buyer_acceleration_ratio"]

        row = {
            "mint": mint,
            "symbol": snap["symbol"],
            "created_timestamp_ms": cts,
            "signal_timestamp_ms": sig_ts,
            "data_max_timestamp_ms": snap["data_max_timestamp_ms"],
            "entry_price_usd": snap["entry_price_usd"],
            "implied_liquidity_usd": snap["implied_liquidity_usd"],
            "supply_status": snap["supply_status"],
            "score_v2_1_pruned": round(sc_v21_pruned, 6),
            "score_v2_1_full": round(sc_v21_full, 6),
            "score_v2_frozen": round(sc_v2_froz, 6),
            "score_v1_frozen": round(sc_v1_froz, 6),
            "score_independent_buyer_growth": round(sc_ind_growth, 6),
            "score_buyer_velocity": round(mv["unique_buyers_cum"] + mv["independent_buyer_velocity"], 6),
            "score_volume_only": snap["buy_volume_usd"],
            "score_price_momentum": snap["already_moved_mult"],
            "score_first_correction_absorption": round(mv["dip_absorption_ratio"] + 0.5 * mv["buy_sell_log_ratio"], 6),
            "score_wallet_intelligence": round(mv["smart_wallets_count_num"] + 0.5 * mv["creator_win_rate_num"] - 0.5 * mv["creator_dumped_flag"], 6),
            "status_1h": lbl["status_1h"],
            "hit_2x_1h": lbl["hit_2x_1h"],
            "hit_3x_1h": lbl["hit_3x_1h"],
            "status_4h": lbl["status_4h"],
            "hit_2x_4h": lbl["hit_2x_4h"],
            "hit_3x_4h": lbl["hit_3x_4h"],
            "hit_5x_4h": lbl["hit_5x_4h"],
            "status_24h": lbl["status_24h"],
            "hit_2x_24h": lbl["hit_2x_24h"],
            "hit_3x_24h": lbl["hit_3x_24h"],
            "hit_5x_24h": lbl["hit_5x_24h"],
            "hit_10x_24h": lbl["hit_10x_24h"],
            "max_multiple_4h": lbl.get("max_multiple_4h"),
            "end_return_4h_pct": lbl.get("end_return_4h_pct"),
            "net_ret_0_25_sol_pct": ex_025.get("net_return_after_fees_pct"),
            "net_ret_1_0_sol_pct": ex_100.get("net_return_after_fees_pct"),
        }
        oot_rows.append(row)
        oot_eval_objs.append(row)

    df_oot = pd.DataFrame(oot_rows)
    df_oot.to_csv(V2_1_DIR / "OUT_OF_TIME_V2_1.csv", index=False)

    # 3. Compute 9-target OOT Denominator, Base-Rate, Wilson 95% CI, and Model Comparison Summary!
    all_9_targets = [
        ("hit_2x_1h", "status_1h"),
        ("hit_3x_1h", "status_1h"),
        ("hit_2x_4h", "status_4h"),
        ("hit_3x_4h", "status_4h"),
        ("hit_5x_4h", "status_4h"),
        ("hit_2x_24h", "status_24h"),
        ("hit_3x_24h", "status_24h"),
        ("hit_5x_24h", "status_24h"),
        ("hit_10x_24h", "status_24h"),
    ]

    target_summary = []
    for t_col, st_col in all_9_targets:
        n_tot = len(oot_rows)
        comp_rows = [r for r in oot_rows if r[st_col] == "complete" and isinstance(r[t_col], int)]
        cens_cnt = sum(1 for r in oot_rows if r[st_col] == "censored")
        unk_cnt = sum(1 for r in oot_rows if r[st_col] == "unknown")
        n_comp = len(comp_rows)
        n_pos = sum(int(r[t_col]) for r in comp_rows)
        n_neg = n_comp - n_pos
        ci_lo, ci_hi = wilson_ci_95(n_pos, n_comp)

        if n_comp >= 50 and n_pos >= 10:
            power_status = "SUFFICIENT_POWER"
            y_arr = np.array([int(r[t_col]) for r in comp_rows], dtype=int)
            s_pruned = np.array([float(r["score_v2_1_pruned"]) for r in comp_rows], dtype=float)
            m_res = compute_binary_ranking_metrics(y_arr, s_pruned)
            top20_hits = int(round((m_res["precision_at_20"] or 0.0) * min(20, n_comp)))
            p20_lo, p20_hi = wilson_ci_95(top20_hits, min(20, n_comp))
        elif n_comp > 0 and n_pos > 0:
            power_status = "INCONCLUSIVE_LOW_POSITIVES"
            y_arr = np.array([int(r[t_col]) for r in comp_rows], dtype=int)
            s_pruned = np.array([float(r["score_v2_1_pruned"]) for r in comp_rows], dtype=float)
            m_res = compute_binary_ranking_metrics(y_arr, s_pruned)
            top20_hits = int(round((m_res["precision_at_20"] or 0.0) * min(20, n_comp)))
            p20_lo, p20_hi = wilson_ci_95(top20_hits, min(20, n_comp))
        else:
            power_status = "INCONCLUSIVE_CENSORED_HORIZON" if cens_cnt > 0 else "INCONCLUSIVE_ZERO_POSITIVES"
            m_res = {"roc_auc": None, "pr_auc": None, "precision_at_10": None, "precision_at_20": None, "lift_at_20": None}
            p20_lo, p20_hi = (None, None)

        target_summary.append({
            "target": t_col,
            "total_oot_tokens": n_tot,
            "complete_count": n_comp,
            "censored_count": cens_cnt,
            "unknown_count": unk_cnt,
            "completeness_of_elapsed_pct": round(100.0 * n_comp / max(1, n_tot - cens_cnt), 2) if (n_tot - cens_cnt) > 0 else None,
            "positives": n_pos,
            "negatives": n_neg,
            "base_rate": round(n_pos / n_comp, 4) if n_comp > 0 else None,
            "base_rate_wilson_95ci": [ci_lo, ci_hi],
            "v2_1_pruned_roc_auc": m_res["roc_auc"],
            "v2_1_pruned_pr_auc": m_res["pr_auc"],
            "v2_1_pruned_precision_at_10": m_res["precision_at_10"],
            "v2_1_pruned_precision_at_20": m_res["precision_at_20"],
            "v2_1_pruned_p20_wilson_95ci": [p20_lo, p20_hi],
            "v2_1_pruned_lift_at_20": m_res["lift_at_20"],
            "statistical_verdict": power_status,
        })

    # Head-to-head comparison of all 10 models on strictly unseen complete 4h OOT (`hit_2x_4h`)
    comp_4h = [r for r in oot_rows if r["status_4h"] == "complete" and isinstance(r["hit_2x_4h"], int)]
    oot_model_head_to_head = []
    if comp_4h and sum(r["hit_2x_4h"] for r in comp_4h) > 0:
        y4 = np.array([int(r["hit_2x_4h"]) for r in comp_4h], dtype=int)
        model_cols = [
            ("1_Buyer_Velocity_Only", "score_buyer_velocity"),
            ("2_Independent_Buyer_Growth", "score_independent_buyer_growth"),
            ("3_Volume_Only", "score_volume_only"),
            ("4_Price_Momentum_Only", "score_price_momentum"),
            ("5_First_Correction_Absorption", "score_first_correction_absorption"),
            ("6_Wallet_Intelligence", "score_wallet_intelligence"),
            ("7_Pump_Potential_V1_Frozen", "score_v1_frozen"),
            ("8_Pump_Potential_V2_Frozen", "score_v2_frozen"),
            ("9_Pump_Potential_V2_1_Full", "score_v2_1_full"),
            ("10_Pump_Potential_V2_1_Pruned", "score_v2_1_pruned"),
        ]
        for m_lbl, col_k in model_cols:
            sc = np.array([float(r[col_k]) for r in comp_4h], dtype=float)
            mm = compute_binary_ranking_metrics(y4, sc)
            ord20 = np.argsort(-sc)[:min(20, len(comp_4h))]
            net025 = [float(comp_4h[i]["net_ret_0_25_sol_pct"]) for i in ord20 if comp_4h[i]["net_ret_0_25_sol_pct"] is not None]
            net100 = [float(comp_4h[i]["net_ret_1_0_sol_pct"]) for i in ord20 if comp_4h[i]["net_ret_1_0_sol_pct"] is not None]
            hits20 = int(round((mm["precision_at_20"] or 0.0) * min(20, len(comp_4h))))
            ci20 = wilson_ci_95(hits20, min(20, len(comp_4h)))
            oot_model_head_to_head.append({
                "model_name": m_lbl,
                "unseen_oot_4h_complete_n": mm["n_obs"],
                "positives_2x_4h": mm["n_positives"],
                "base_rate_2x_4h": mm["base_rate"],
                "oot_roc_auc_2x_4h": mm["roc_auc"],
                "oot_pr_auc_2x_4h": mm["pr_auc"],
                "oot_precision_at_10": mm["precision_at_10"],
                "oot_precision_at_20": mm["precision_at_20"],
                "oot_p20_wilson_95ci_low": ci20[0],
                "oot_p20_wilson_95ci_high": ci20[1],
                "oot_lift_at_20": mm["lift_at_20"],
                "oot_recall_top25pct": mm["recall_top25pct"],
                "oot_top20_mean_net_0_25_sol_pct": round(float(np.mean(net025)), 2) if net025 else None,
                "oot_top20_mean_net_1_0_sol_pct": round(float(np.mean(net100)), 2) if net100 else None,
            })

    # 4. Run Live Paper Trading V2.1 Scan (or reuse freshly populated live scan)!
    pa_csv = V2_1_DIR / "paper_trading" / "paper_alerts_v2_1.csv"
    if pa_csv.exists():
        df_paper = pd.read_csv(pa_csv)
    else:
        df_paper = await run_paper_trading_scan_v2_1(max_candidates=25)

    summary_payload = {
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_unseen_oot_tokens": len(oot_rows),
        "heldout_4h_elapsed_tokens": len(heldout_candidates),
        "live_morning_tokens": len(live_morning),
        "targets_9_summary": target_summary,
        "oot_head_to_head_4h_models": oot_model_head_to_head,
        "paper_trading_logged_count": len(df_paper),
        "paper_trading_alerts_triggered": int(df_paper["alert_triggered"].sum()) if len(df_paper) else 0,
    }
    (OOT_V2_1_DIR / "oot_summary_v2_1.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    # Also update `MODEL_COMPARISON_V2_1.csv` to append the strictly unseen OOT head-to-head results & `10_Pump_Potential_V2_1_Pruned`!
    df_mc = pd.read_csv(V2_1_DIR / "MODEL_COMPARISON_V2_1.csv")
    df_mc["in_sample_overlap_on_wf650"] = df_mc["model_name"].apply(lambda s: 1 if "V2_Frozen" in str(s) else 0)
    oot_map = {r["model_name"]: r for r in oot_model_head_to_head}
    df_mc["unseen_oot_n"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("unseen_oot_4h_complete_n"))
    df_mc["unseen_oot_roc_auc_2x_4h"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("oot_roc_auc_2x_4h"))
    df_mc["unseen_oot_pr_auc_2x_4h"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("oot_pr_auc_2x_4h"))
    df_mc["unseen_oot_precision_at_20"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("oot_precision_at_20"))
    df_mc["unseen_oot_lift_at_20"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("oot_lift_at_20"))
    df_mc["unseen_oot_top20_net_0_25_sol_pct"] = df_mc["model_name"].map(lambda s: oot_map.get(s, {}).get("oot_top20_mean_net_0_25_sol_pct"))

    # Add row for `10_Pump_Potential_V2_1_Pruned` (which equals `Ablation_minus_creator_history` on WF + OOT!)
    ab_cr = df_mc[df_mc["model_name"] == "Ablation_minus_creator_history"].copy()
    if not ab_cr.empty and "10_Pump_Potential_V2_1_Pruned" not in set(df_mc["model_name"]):
        ab_cr["model_name"] = "10_Pump_Potential_V2_1_Pruned"
        ab_cr["category"] = "Core_Benchmark_Or_Model"
        pr_oot = oot_map.get("10_Pump_Potential_V2_1_Pruned", {})
        ab_cr["unseen_oot_n"] = pr_oot.get("unseen_oot_4h_complete_n")
        ab_cr["unseen_oot_roc_auc_2x_4h"] = pr_oot.get("oot_roc_auc_2x_4h")
        ab_cr["unseen_oot_pr_auc_2x_4h"] = pr_oot.get("oot_pr_auc_2x_4h")
        ab_cr["unseen_oot_precision_at_20"] = pr_oot.get("oot_precision_at_20")
        ab_cr["unseen_oot_lift_at_20"] = pr_oot.get("oot_lift_at_20")
        ab_cr["unseen_oot_top20_net_0_25_sol_pct"] = pr_oot.get("oot_top20_mean_net_0_25_sol_pct")
        df_mc = pd.concat([df_mc, ab_cr], ignore_index=True)

    df_mc.to_csv(V2_1_DIR / "MODEL_COMPARISON_V2_1.csv", index=False)

    t4h = next(t for t in target_summary if t["target"] == "hit_2x_4h")
    t1h = next(t for t in target_summary if t["target"] == "hit_2x_1h")
    logger.info(
        f"STEP 3 V2.1 COMPLETE in {time.time()-t0:.1f}s!\n"
        f"  - OOT 1h complete: {t1h['complete_count']}/{t1h['total_oot_tokens']} (elapsed completeness={t1h['completeness_of_elapsed_pct']}%, pos={t1h['positives']})\n"
        f"  - OOT 4h complete: {t4h['complete_count']}/{t4h['total_oot_tokens']} (elapsed completeness={t4h['completeness_of_elapsed_pct']}%, pos={t4h['positives']}, ROC-AUC={t4h['v2_1_pruned_roc_auc']}, PR-AUC={t4h['v2_1_pruned_pr_auc']})\n"
        f"  - Paper Trading V2.1: {len(df_paper)} candidates logged ({summary_payload['paper_trading_alerts_triggered']} alerts)"
    )


if __name__ == "__main__":
    asyncio.run(main())
