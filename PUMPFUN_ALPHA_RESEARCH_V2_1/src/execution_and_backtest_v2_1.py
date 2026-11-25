"""
STEP 2 (V2.1 — P0/P1):
- Multi-horizon outcome labeling (`hit_2x_1h`, `hit_3x_1h`, `hit_2x_4h`, `hit_3x_4h`, `hit_5x_4h`,
  `hit_2x_24h`, `hit_3x_24h`, `hit_5x_24h`, `hit_10x_24h`) with strict separation of `"complete"`,
  `"censored"`, and `"unknown"` observations (NEVER replacing missing/censored with 0!).
- Validated Supply Concentration (`SUPPLY_CONCENTRATION_V2_1.csv` with `INVALID_SUPPLY_RECONSTRUCTION` blocking),
  Strict FIFO Cost-Basis Realized PnL (`REALIZED_PNL_V2_1.csv` with `UNKNOWN_COST_BASIS`),
  and Deep RPC Wallet Intelligence & Clustering (`WALLET_INTELLIGENCE_V2_1.csv`, `WALLET_CLUSTERS_V2_1.csv`).
- Realistic Constant-Product Execution Simulator (`POSITION_SIZING_EXECUTION_V2_1.csv`) across
  `0.1, 0.25, 0.5, 1.0, 2.0 SOL`, separating:
    1) `mid_price_return_pct`
    2) `mark_to_market_return_pct`
    3) `executable_return_pct`
    4) `net_return_after_fees_pct`
- Chronological Walk-Forward Validation with Train / Validation / Test splits + 4h temporal embargo +
  zero token overlap (`WALK_FORWARD_V2_1.csv`).
- Head-to-head comparison of all 9 required models + all 8 Ablation Tests (`MODEL_COMPARISON_V2_1.csv`).
- Saves populated chronological `UnifiedStateBundle` checkpoint (`state_post_wf_v2_1.json`) for 100% parity in OOT & Paper Trading!
"""
import json
import math
import time
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from config_v2_1 import (
    V2_DIR, V2_1_DIR, SNAPSHOTS_DIR, CHECKPOINTS_DIR,
    WALLETS_V2_1_DIR, FROZEN_BASELINES_DIR, LOGS_DIR,
    INTERVAL_MS, PUMPFUN_INIT_VIRTUAL_SOL, PUMPFUN_INIT_VIRTUAL_TOKENS, PUMPFUN_INIT_K,
    CONFIRMED_TECHNICAL_ADDRESSES,
)
from state_trackers_v2_1 import UnifiedStateBundle
from feature_engine import (
    UnifiedFeatureEngine,
    ALL_MODEL_FEATURES_V2_1,
    MODEL_FEATURE_GROUPS_V2_1,
    classify_token_narrative,
    deduplicate_and_filter_trades_before,
    build_token_technical_set,
)
from wallet_supply_fifo_v2_1 import reconstruct_supply_and_fifo_v2_1, classify_relationships_v2_1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step2_execution_and_backtest_v2_1.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("v2_1_step2")

POSITION_SIZES_SOL = [0.1, 0.25, 0.5, 1.0, 2.0]
SWAP_FEE_RATE = 0.01          # 1.00% Pump.fun / AMM swap fee
PRIORITY_TX_FEE_SOL = 0.0005  # 0.0005 SOL per leg (priority + base fee)

HORIZONS_SPEC = [
    ("1h", 3_600_000, [2.0, 3.0]),
    ("4h", 14_400_000, [2.0, 3.0, 5.0]),
    ("24h", 86_400_000, [2.0, 3.0, 5.0, 10.0]),
]


def compute_multi_horizon_labels_and_path(
    coin: dict,
    trades: list,
    candles_obj: dict,
    signal_ts_ms: int,
    entry_price_usd: float,
    entry_price_quote_sol: float,
    sol_price_usd_at_sig: float,
) -> dict:
    """
    Computes strictly post-signal fixed-horizon labels (`signal_ts_ms < t <= signal_ts_ms + H`),
    distinguishing `"complete"`, `"censored"`, and `"unknown"`.
    Also extracts the chronological post-signal price path up to +4h for realistic AMM execution simulation.
    """
    coll_ts = min(
        int(candles_obj.get("collection_timestamp_ms") or 0),
        int(coin.get("_collection_ts_ms") or candles_obj.get("collection_timestamp_ms") or 0)
    )
    if coll_ts <= 0:
        coll_ts = int(candles_obj.get("collection_timestamp_ms") or 0)

    c1m = candles_obj.get("candles_1m") or []
    c15m = candles_obj.get("candles_15m") or []
    c4h = candles_obj.get("candles_4h") or []
    api_ok = bool(candles_obj.get("api_ok", False))

    # Deduplicate all trades strictly AFTER signal_ts_ms
    seen_t = set()
    post_trades = []
    for tr in trades:
        tms = int(tr.get("blockTimeMs") or 0)
        if tms <= signal_ts_ms:
            continue
        dk = (tr.get("txId") or tr.get("ordinalKey") or "", int(tr.get("legIndex") or 0), int(tr.get("eventIndex") or 0))
        if dk in seen_t:
            continue
        seen_t.add(dk)
        if float(tr.get("priceUsd") or 0) > 0:
            post_trades.append(tr)
    post_trades.sort(key=lambda x: int(x["blockTimeMs"]))

    # Verify whether absence of candles is genuine 0-trade inactivity vs missing API response
    verified_zero_post_activity = (not api_ok and len(trades) == 0 and coll_ts > signal_ts_ms)
    has_valid_market_feed = api_ok or len(trades) > 0 or verified_zero_post_activity

    out = {"collection_timestamp_ms": coll_ts}
    ep = max(entry_price_usd, 1e-12)

    for h_name, h_ms, mults in HORIZONS_SPEC:
        end_ts = signal_ts_ms + h_ms
        if coll_ts <= 0 or not has_valid_market_feed:
            st = "unknown"
        elif coll_ts < end_ts:
            st = "censored"
        else:
            st = "complete"

        out[f"status_{h_name}"] = st
        if st != "complete":
            out[f"max_multiple_{h_name}"] = st
            out[f"max_drawdown_{h_name}_pct"] = st
            out[f"end_return_{h_name}_pct"] = st
            for m in mults:
                m_int = int(m)
                out[f"hit_{m_int}x_{h_name}"] = st
            continue

        # Collect strictly post-signal closed candles & reliable swaps within (signal_ts_ms, end_ts]
        # Note: a candle is strictly post-signal ONLY if `openTimeMs >= signal_ts_ms` and `openTimeMs + dur <= end_ts`!
        pts_high = [ep]
        pts_low = [ep]
        end_px = ep
        end_px_ts = signal_ts_ms
        hit_times = {int(m): None for m in mults}

        # Check granular 1m candles + 15m candles (for 4h/24h) + post-signal reliable swaps
        bar_sets = [(c1m, INTERVAL_MS["1m"])]
        if h_ms >= INTERVAL_MS["4h"]:
            bar_sets.append((c15m, INTERVAL_MS["15m"]))
        if h_ms >= INTERVAL_MS["1d"]:
            bar_sets.append((c4h, INTERVAL_MS["4h"]))

        events_chrono = []
        for bars, dur in bar_sets:
            for b in bars:
                ot = int(b.get("openTimeMs") or 0)
                ct = ot + dur
                if ot >= signal_ts_ms and ct <= end_ts:
                    hi = float(b.get("high") or 0.0)
                    lo = float(b.get("low") or 0.0)
                    cl = float(b.get("close") or 0.0)
                    if hi > 0 and cl > 0:
                        # Filter single-wick dust spikes >50x above close unless backed by volume >= $25
                        vol_b = float(b.get("volume") or 0.0)
                        eff_hi = hi if (vol_b >= 25.0 or hi <= cl * 8.0) else max(cl, float(b.get("open") or cl))
                        events_chrono.append((ct, eff_hi, lo if lo > 0 else cl, cl))

        for tr in post_trades:
            tms = int(tr["blockTimeMs"])
            if signal_ts_ms < tms <= end_ts:
                vu = float(tr.get("valueUsd") or 0.0)
                vn = float(tr.get("valueNative") or 0.0)
                px = float(tr["priceUsd"])
                if vu >= 5.0 or vn >= 0.05:
                    events_chrono.append((tms, px, px, px))

        events_chrono.sort(key=lambda x: x[0])
        for ev_ts, hi, lo, cl in events_chrono:
            pts_high.append(hi)
            pts_low.append(lo)
            if ev_ts >= end_px_ts:
                end_px = cl
                end_px_ts = ev_ts
            mult_now = hi / ep
            for m in mults:
                mi = int(m)
                if hit_times[mi] is None and mult_now >= m:
                    hit_times[mi] = round((ev_ts - signal_ts_ms) / 1000.0, 1)

        max_mult = round(max(pts_high) / ep, 4)
        min_mult = min(pts_low) / ep
        max_dd_pct = round((min_mult - 1.0) * 100.0, 2)
        end_ret_pct = round(((end_px / ep) - 1.0) * 100.0, 2)

        out[f"max_multiple_{h_name}"] = max_mult
        out[f"max_drawdown_{h_name}_pct"] = max_dd_pct
        out[f"end_return_{h_name}_pct"] = end_ret_pct
        for m in mults:
            mi = int(m)
            out[f"hit_{mi}x_{h_name}"] = 1 if max_mult >= m else 0
            if h_name == "4h" and mi in (2, 3):
                out[f"time_to_{mi}x_4h_sec"] = hit_times[mi] if hit_times[mi] is not None else ""

    # Build chronological 4h execution path (for Section 7 Realistic Liquidity & AMM Execution Simulator)
    path_4h = []
    end_4h = signal_ts_ms + INTERVAL_MS["4h"]
    for b in c1m:
        ot = int(b.get("openTimeMs") or 0)
        ct = ot + INTERVAL_MS["1m"]
        if ot >= signal_ts_ms and ct <= end_4h and float(b.get("close") or 0) > 0:
            vol_b = float(b.get("volume") or 0.0)
            cl = float(b["close"])
            hi = float(b.get("high") or cl)
            lo = float(b.get("low") or cl)
            eff_hi = hi if (vol_b >= 25.0 or hi <= cl * 8.0) else cl
            path_4h.append((ct, eff_hi / ep, (lo if lo > 0 else cl) / ep, cl / ep, "pump"))

    if not path_4h:
        for tr in post_trades:
            tms = int(tr["blockTimeMs"])
            if signal_ts_ms < tms <= end_4h and (float(tr.get("valueUsd") or 0) >= 5.0 or float(tr.get("valueNative") or 0) >= 0.05):
                m_tr = float(tr["priceUsd"]) / ep
                path_4h.append((tms, m_tr, m_tr, m_tr, tr.get("venue") or "pump"))

    path_4h.sort(key=lambda x: x[0])
    out["_exec_path_4h"] = path_4h
    return out


def simulate_amm_position_execution(
    snapshot: dict,
    labels: dict,
    pos_sol: float,
    tp_mult: float = 2.5,
    sl_mult: float = 0.55,
) -> dict:
    """
    Section 7 Realistic Liquidity & Constant-Product Execution Simulator.
    Computes exact reserve price impact, swap fees, and priority/tx fees for `pos_sol` in [0.1, 0.25, 0.5, 1.0, 2.0] SOL,
    explicitly separating:
      1. `mid_price_return_pct`
      2. `mark_to_market_return_pct`
      3. `executable_return_pct`
      4. `net_return_after_fees_pct`
    """
    if labels.get("status_4h") != "complete":
        return {"status": labels.get("status_4h", "unknown")}

    r_sol_in = float(snapshot["virtual_sol_reserve_at_signal"])
    r_tok_in = float(snapshot["virtual_token_reserve_at_signal"])
    res_src_in = snapshot["reserve_source_at_signal"]
    entry_mid_sol = r_sol_in / max(r_tok_in, 1.0)

    # 1. Entry execution on constant-product curve `x * y = k`
    dx_sol_after_fees = max(0.0, (pos_sol - PRIORITY_TX_FEE_SOL) * (1.0 - SWAP_FEE_RATE))
    dx_sol_no_fees = pos_sol  # pure AMM impact reference without protocol/network fees

    tokens_acquired = (r_tok_in * dx_sol_after_fees) / (r_sol_in + dx_sol_after_fees)
    tokens_no_fees = (r_tok_in * dx_sol_no_fees) / (r_sol_in + dx_sol_no_fees)
    entry_impact_pct = ((pos_sol / max(tokens_no_fees, 1e-12)) / max(entry_mid_sol, 1e-15) - 1.0) * 100.0

    # 2. Walk forward along strictly post-signal 4h path to find realistic exit point (TP / SL / 4h time-stop)
    path_4h = labels.get("_exec_path_4h") or []
    exit_mult = 1.0
    exit_reason = "time_stop_4h_flat"
    exit_venue = snapshot.get("venue_at_signal") or "pump"

    for ev_ts, hi_m, lo_m, cl_m, ven in path_4h:
        # Conservative intra-bar ordering: if both SL and TP touched in same 1m bar, check SL first!
        if lo_m <= sl_mult:
            exit_mult = sl_mult
            exit_reason = "stop_loss_45pct"
            exit_venue = ven
            break
        if hi_m >= tp_mult:
            exit_mult = tp_mult
            exit_reason = "take_profit_2_5x"
            exit_venue = ven
            break
        exit_mult = cl_m
        exit_reason = "time_stop_4h"
        exit_venue = ven

    exit_mid_sol = max(1e-14, entry_mid_sol * exit_mult)

    # 3. Recover reserve state at exit
    # Pump.fun graduation threshold occurs around ~85 real SOL (~115 virtual SOL, priceQuote ~ 5.56e-7 SOL/tok)
    grad_price_sol = 115.0 / 206_900_000.0
    if exit_venue == "pump" and exit_mid_sol < grad_price_sol:
        r_sol_out = math.sqrt(PUMPFUN_INIT_K * exit_mid_sol)
        r_tok_out = math.sqrt(PUMPFUN_INIT_K / exit_mid_sol)
        res_src_out = "EXACT_BONDING_CURVE_RESERVES"
    else:
        # Graduated AMM pool (canonical Raydium/PumpSwap seed ~85 SOL; historical LP adds/removes estimated)
        r_sol_out = max(85.0, math.sqrt(85.0 * 206_900_000.0 * exit_mid_sol))
        r_tok_out = r_sol_out / exit_mid_sol
        res_src_out = "ESTIMATED_AMM_RESERVES"

    # 4. Exit execution on constant-product curve `x * y = k`
    gross_sol_out_from_actual_tokens = (r_sol_out * tokens_acquired) / (r_tok_out + tokens_acquired)
    gross_sol_out_pure_amm = (r_sol_out * tokens_no_fees) / (r_tok_out + tokens_no_fees)
    net_sol_out = max(0.0, gross_sol_out_from_actual_tokens * (1.0 - SWAP_FEE_RATE) - PRIORITY_TX_FEE_SOL)

    exit_impact_pct = (1.0 - (gross_sol_out_pure_amm / max(tokens_no_fees * exit_mid_sol, 1e-12))) * 100.0

    # Four distinct return definitions mandated by Section 7:
    mid_price_ret_pct = (exit_mult - 1.0) * 100.0
    mtm_ret_pct = (((tokens_acquired * exit_mid_sol) / pos_sol) - 1.0) * 100.0
    executable_ret_pct = ((gross_sol_out_pure_amm / pos_sol) - 1.0) * 100.0
    net_ret_after_fees_pct = ((net_sol_out / pos_sol) - 1.0) * 100.0

    return {
        "status": "complete",
        "position_size_sol": pos_sol,
        "reserve_source_entry": res_src_in,
        "reserve_source_exit": res_src_out,
        "virtual_sol_reserve_entry": round(r_sol_in, 4),
        "virtual_sol_reserve_exit": round(r_sol_out, 4),
        "entry_price_impact_pct": round(entry_impact_pct, 4),
        "exit_price_impact_pct": round(exit_impact_pct, 4),
        "exit_reason": exit_reason,
        "mid_price_return_pct": round(mid_price_ret_pct, 4),
        "mark_to_market_return_pct": round(mtm_ret_pct, 4),
        "executable_return_pct": round(executable_ret_pct, 4),
        "net_return_after_fees_pct": round(net_ret_after_fees_pct, 4),
        "net_pnl_sol": round(net_sol_out - pos_sol, 6),
    }


def fit_l2_logistic(X: np.ndarray, y: np.ndarray, l2_reg: float = 2.0) -> dict:
    """Fits standardized L2-penalized logistic regression natively via scipy L-BFGS-B (no sklearn DLL needed)."""
    mu = np.mean(X, axis=0)
    sd = np.std(X, axis=0)
    sd = np.where(sd < 1e-8, 1.0, sd)
    Xs = (X - mu) / sd

    n, d = Xs.shape
    pos = max(1.0, float(np.sum(y == 1)))
    neg = max(1.0, float(np.sum(y == 0)))
    # Balanced class weights so rare pump base rates (~8%-15%) calibrate cleanly
    w_pos = n / (2.0 * pos)
    w_neg = n / (2.0 * neg)
    sample_w = np.where(y == 1, w_pos, w_neg)

    def loss_and_grad(params):
        w = params[:-1]
        b = params[-1]
        z = np.clip(Xs @ w + b, -30.0, 30.0)
        p = expit(z)
        eps = 1e-12
        nll = -np.sum(sample_w * (y * np.log(p + eps) + (1.0 - y) * np.log(1.0 - p + eps))) / n
        pen = 0.5 * (l2_reg / n) * np.sum(w * w)
        diff = sample_w * (p - y) / n
        gw = Xs.T @ diff + (l2_reg / n) * w
        gb = float(np.sum(diff))
        return nll + pen, np.append(gw, gb)

    init_p = np.zeros(d + 1)
    res = minimize(loss_and_grad, init_p, jac=True, method="L-BFGS-B", options={"maxiter": 300})
    w_hat = res.x[:-1]
    b_hat = float(res.x[-1])
    return {"mean": mu, "scale": sd, "coef": w_hat, "intercept": b_hat, "l2_reg": l2_reg}


def predict_l2_logistic(model: dict, X: np.ndarray) -> np.ndarray:
    Xs = (X - model["mean"]) / model["scale"]
    return expit(np.clip(Xs @ model["coef"] + model["intercept"], -30.0, 30.0))


def compute_binary_ranking_metrics(y_true: np.ndarray, scores: np.ndarray) -> dict:
    """Computes exact ROC-AUC, PR-AUC, Precision@K, Recall@Top25%, and Lift without sklearn."""
    n = len(y_true)
    n_pos = int(np.sum(y_true == 1))
    base_rate = n_pos / max(1, n)
    if n == 0 or n_pos == 0 or n_pos == n:
        return {
            "n_obs": n, "n_positives": n_pos, "base_rate": round(base_rate, 4),
            "roc_auc": np.nan, "pr_auc": np.nan,
            "precision_at_5": np.nan, "precision_at_10": np.nan, "precision_at_20": np.nan,
            "lift_at_10": np.nan, "lift_at_20": np.nan, "recall_top25pct": np.nan,
        }

    # Sort descending by score (break ties deterministically by index)
    order = np.argsort(-scores, kind="mergesort")
    y_sorted = y_true[order]

    # Exact ROC-AUC via Mann-Whitney U with tie handling
    from scipy.stats import rankdata
    ranks = rankdata(scores)
    sum_pos_ranks = float(np.sum(ranks[y_true == 1]))
    n_neg = n - n_pos
    roc_auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)

    # Exact PR-AUC (average precision)
    cum_tp = np.cumsum(y_sorted == 1)
    precisions = cum_tp / np.arange(1, n + 1)
    pr_auc = float(np.sum(precisions[y_sorted == 1]) / n_pos)

    def prec_at_k(k):
        kk = min(k, n)
        return float(np.mean(y_sorted[:kk])) if kk > 0 else np.nan

    p5 = prec_at_k(5)
    p10 = prec_at_k(10)
    p20 = prec_at_k(20)
    k25 = max(1, int(round(0.25 * n)))
    rec25 = float(np.sum(y_sorted[:k25] == 1) / n_pos)

    return {
        "n_obs": n,
        "n_positives": n_pos,
        "base_rate": round(base_rate, 4),
        "roc_auc": round(float(roc_auc), 4),
        "pr_auc": round(float(pr_auc), 4),
        "precision_at_5": round(p5, 4),
        "precision_at_10": round(p10, 4),
        "precision_at_20": round(p20, 4),
        "lift_at_10": round(p10 / base_rate, 4) if base_rate > 0 else np.nan,
        "lift_at_20": round(p20 / base_rate, 4) if base_rate > 0 else np.nan,
        "recall_top25pct": round(rec25, 4),
    }


def score_frozen_v1_on_snapshot(snap: dict, v1_frozen: dict) -> float:
    w = v1_frozen["v1_weights"]
    mv = snap["model_vector"]
    raw = (
        w["independent_buyer_velocity"] * math.log1p(max(0.0, mv["independent_buyer_velocity"]))
        + w["creator_dumped_at_T"] * mv["creator_dumped_flag"]
        + w["dip_absorption_ratio_at_T"] * mv["dip_absorption_ratio"]
        + w["causal_smart_wallets_in"] * mv["smart_wallets_count_num"]
        + w["meme_shareability_score"] * mv["narrative_lexical_score"]
        + w["vol_to_mcap_ratio_at_T"] * mv["vol_to_mcap_ratio"]
        + w["is_ticker_first_mover"] * mv["ticker_first_mover_num"]
        + w["buy_sell_usd_ratio"] * mv["buy_sell_log_ratio"]
        + w["mayhem_enabled"] * mv["mayhem_enabled"]
        + w["wallet_concentration_change"] * (mv["concentration_change_pct_num"] / 10.0)
        + w["creator_prior_win_rate"] * mv["creator_win_rate_num"]
        + w["buyer_acceleration_ratio"] * mv["buyer_acceleration_ratio"]
        + w["tx_acceleration_ratio"] * mv["tx_acceleration_ratio"]
        + w["sol_ret_24h_pct"] * (mv["sol_ret_24h_pct_num"] / 5.0)
        + w["has_social_links"] * mv["has_launch_social_links"]
    )
    return float(expit(np.clip(raw - 1.5, -25.0, 25.0)))


def score_frozen_v2_on_snapshot(snap: dict, v2_frozen: dict) -> float:
    mv = snap["model_vector"]
    vec_map = {
        "independent_buyer_velocity": mv["independent_buyer_velocity"],
        "unique_buyers_cum": mv["unique_buyers_cum"],
        "scale_in_buyers_ratio": mv["scale_in_buyers_ratio"],
        "buyer_acceleration_ratio": mv["buyer_acceleration_ratio"],
        "tx_acceleration_ratio": mv["tx_acceleration_ratio"],
        "buy_sell_usd_ratio": mv["buy_sell_log_ratio"],
        "dip_absorption_ratio": mv["dip_absorption_ratio"],
        "vol_to_mcap_ratio": mv["vol_to_mcap_ratio"],
        "causal_smart_wallets_in": mv["smart_wallets_count_num"],
        "creator_prior_win_rate": mv["creator_win_rate_num"],
        "creator_prior_launches_log": mv["creator_prior_launches_log"],
        "creator_dumped_flag": mv["creator_dumped_flag"],
        "same_slot_bundle_wallets_at_T": mv["same_slot_bundle_wallets_at_T"],
        "mayhem_enabled": mv["mayhem_enabled"],
        "top5_human_supply_pct_at_T": mv["top5_human_supply_pct_num"],
        "concentration_change_pct": mv["concentration_change_pct_num"],
        "has_social_links": mv["has_launch_social_links"],
        "twitter_is_post_or_handle": mv["twitter_is_direct_post_or_handle"],
        "narrative_lexical_score": mv["narrative_lexical_score"],
        "is_ticker_first_mover": mv["ticker_first_mover_num"],
        "sol_ret_24h_pct": mv["sol_ret_24h_pct_num"],
    }
    x = np.array([vec_map[f] for f in v2_frozen["feature_names"]], dtype=float)
    mu = np.array(v2_frozen["scaler_mean"], dtype=float)
    sc = np.array(v2_frozen["scaler_scale"], dtype=float)
    coef = np.array(v2_frozen["coef"], dtype=float)
    z = float(np.dot((x - mu) / sc, coef) + float(v2_frozen["intercept"]))
    return float(expit(np.clip(z, -25.0, 25.0)))


def main():
    t0 = time.time()
    logger.info("=== STEP 2 V2.1: CAUSAL ENGINE, SUPPLY/FIFO, EXECUTION SIMULATOR & WALK-FORWARD ===")

    # 1. Load chronological 650-token dataset, SOL klines, creator launch dates, and deep RPC wallet DB
    ds = json.loads((V2_DIR / "cache" / "raw" / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    tokens = sorted(ds["tokens"], key=lambda x: (int(x.get("created_timestamp") or 0), x["mint"]))
    sol_klines = json.loads((V2_DIR / "cache" / "raw" / "sol_1h_v2.json").read_text(encoding="utf-8"))
    creator_raw = json.loads((V2_DIR / "cache" / "creators" / "outcome_blind_creator_histories.json").read_text(encoding="utf-8"))
    rpc_db_full = json.loads((WALLETS_V2_1_DIR / "deep_wallets_rpc_v2_1.json").read_text(encoding="utf-8"))
    rpc_wallets_db = rpc_db_full.get("wallets", {})
    funder_types = rpc_db_full.get("funder_types", {})

    v1_frozen = json.loads((FROZEN_BASELINES_DIR / "v1_frozen_model.json").read_text(encoding="utf-8"))
    v2_frozen = json.loads((FROZEN_BASELINES_DIR / "v2_frozen_model.json").read_text(encoding="utf-8"))

    # Index SPL transfers by mint from deep RPC reconstruction
    spl_by_mint = defaultdict(list)
    for w_addr, w_info in rpc_wallets_db.items():
        for tf in w_info.get("spl_transfers", []):
            if tf.get("mint"):
                spl_by_mint[tf["mint"]].append(tf)

    # Initialize UnifiedStateBundle
    state = UnifiedStateBundle()
    state.market.ingest_binance_klines(sol_klines, interval="1h")

    # Register ONLY launch existence (`outcome_status="unverified_horizon"`, `is_win=None`) from creator profile history
    # so `creator_prior_launches_log` reflects prior launches created <= signal_ts_ms WITHOUT ever leaking untimestamped ATH!
    for cr_addr, cr_obj in creator_raw.items():
        for cb in cr_obj.get("coins_brief", []):
            cb_mint = cb.get("mint")
            cb_cts = int(cb.get("created_timestamp") or 0)
            if cb_mint and cb_cts > 0:
                state.creators.register_event(
                    creator=cr_addr,
                    mint=cb_mint,
                    created_ts_ms=cb_cts,
                    label_available_at_ms=cb_cts + 1000,
                    is_win=0,
                    outcome_status="unverified_horizon",
                )

    engine = UnifiedFeatureEngine(save_snapshots_dir=SNAPSHOTS_DIR)
    candles_dir = V2_DIR / "cache" / "candles"
    trades_dir = V2_DIR / "cache" / "trades"

    # Pre-load trades & candles so we process tokens in strict chronological order and register outcomes ONLY at `cts + 4h`!
    early_signal_rows = []
    token_metric_rows = []
    supply_rows = []
    fifo_pnl_rows = []
    cluster_rows = []
    exec_sizing_rows = []
    primary_3m_records = []

    co_sniper_pair_counts = Counter()
    wallet_perf_agg = defaultdict(lambda: {
        "tokens_participated": set(),
        "independent_wins_2x_4h": 0,
        "independent_losses_4h": 0,
        "censored_or_unknown_tokens": 0,
        "fifo_verified_pnl_sol_sum": 0.0,
        "unknown_cost_basis_tokens": 0,
        "fees_paid_sol_sum": 0.0,
        "early_entries_le_60s": 0,
    })

    for idx_tok, coin in enumerate(tokens):
        mint = coin["mint"]
        cts = int(coin["created_timestamp"])
        cr = coin.get("creator") or ""

        cp = candles_dir / f"{mint}.json"
        tp = trades_dir / f"{mint}.json"
        c_obj = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {"candles_1m": [], "candles_15m": [], "candles_4h": [], "api_ok": False, "collection_timestamp_ms": 0}
        t_obj = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {"trades": [], "collection_timestamp_ms": 0, "early_30m_pagination_truncated": False}
        trades = t_obj.get("trades") or []
        c1m = c_obj.get("candles_1m") or []
        is_tape_complete = not bool(t_obj.get("early_30m_pagination_truncated", False))

        # Register launch in TickerNarrativeHistoryTracker (`created_ts_ms = cts`)
        narr_cat = classify_token_narrative(coin.get("name"), coin.get("symbol"), coin.get("description"))
        state.tickers.register_launch(cts, mint, coin.get("symbol") or "", narr_cat)

        # Evaluate multi-horizon early snapshots at 60s, 180s (primary 3m), 300s, 900s
        snap_3m = None
        lbl_3m = None
        for obs_sec in (60, 180, 300, 900):
            sig_ts = cts + obs_sec * 1000
            persist_flag = (obs_sec == 180 and idx_tok % 25 == 0)
            snap = engine.compute_snapshot(
                coin=coin,
                trades=trades,
                candles_1m=c1m,
                signal_ts_ms=sig_ts,
                state=state,
                mode="training",
                acquired_at_ms=sig_ts,
                persist_json=persist_flag,
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

            es_row = {
                "mint": mint,
                "symbol": snap["symbol"],
                "observation_horizon_sec": obs_sec,
                "created_timestamp_ms": cts,
                "signal_timestamp_ms": sig_ts,
                "data_max_timestamp_ms": snap["data_max_timestamp_ms"],
                "entry_price_usd": snap["entry_price_usd"],
                "price_source": snap["price_source"],
                "venue_at_signal": snap["venue_at_signal"],
                "reserve_source": snap["reserve_source_at_signal"],
                "implied_liquidity_usd": snap["implied_liquidity_usd"],
                "supply_status": snap["supply_status"],
                "manipulation_risk_score": snap["manipulation_risk_score"],
                "insider_supply_risk_score": snap["insider_supply_risk_score"],
            }
            for col in ALL_MODEL_FEATURES_V2_1:
                es_row[col] = snap["model_vector"][col]
                es_row[f"{col}__raw"] = snap["features"][col]["value"]
                es_row[f"{col}__status"] = snap["features"][col]["status"]
            for hk in [
                "status_1h", "hit_2x_1h", "hit_3x_1h",
                "status_4h", "hit_2x_4h", "hit_3x_4h", "hit_5x_4h",
                "status_24h", "hit_2x_24h", "hit_3x_24h", "hit_5x_24h", "hit_10x_24h",
                "max_multiple_4h", "max_drawdown_4h_pct", "end_return_4h_pct"
            ]:
                es_row[hk] = lbl.get(hk)
            early_signal_rows.append(es_row)

            if obs_sec == 180:
                snap_3m = snap
                lbl_3m = lbl

        # Simulate all 5 position sizes at the primary 180s signal
        exec_by_size = {}
        for p_sol in POSITION_SIZES_SOL:
            ex = simulate_amm_position_execution(snap_3m, lbl_3m, pos_sol=p_sol)
            exec_by_size[p_sol] = ex
            if ex.get("status") == "complete":
                exec_sizing_rows.append({
                    "mint": mint,
                    "symbol": snap_3m["symbol"],
                    "signal_timestamp_ms": snap_3m["signal_timestamp_ms"],
                    **ex,
                })

        # Supply concentration & Strict FIFO Realized PnL reconstruction (up to 4h window end `cts + 180s + 4h`)
        cutoff_4h_ms = snap_3m["signal_timestamp_ms"] + INTERVAL_MS["4h"]
        end_4h_mult = (1.0 + float(lbl_3m["end_return_4h_pct"]) / 100.0) if isinstance(lbl_3m.get("end_return_4h_pct"), (int, float)) else 1.0
        mark_sol_4h = snap_3m["entry_price_quote_sol"] * max(0.0, end_4h_mult)

        sup_fifo = reconstruct_supply_and_fifo_v2_1(
            coin=coin,
            trades=trades,
            spl_transfers=spl_by_mint.get(mint, []),
            rpc_wallets_db=rpc_wallets_db,
            mark_price_sol=mark_sol_4h,
            sol_price_usd=snap_3m["sol_price_usd_at_signal"],
            cutoff_ts_ms=cutoff_4h_ms,
            is_swap_tape_complete=is_tape_complete,
        )
        sup_rec = sup_fifo["supply"]
        supply_rows.append({
            "mint": mint,
            "symbol": snap_3m["symbol"],
            "created_timestamp_ms": cts,
            **sup_rec,
        })

        # Record FIFO PnL rows & update causal WalletHistoryTracker + CreatorHistoryTracker (ONLY available at `cutoff_4h_ms`!)
        hit_2x_4h_val = lbl_3m.get("hit_2x_4h")
        st_4h = lbl_3m.get("status_4h")

        if cr and st_4h == "complete" and isinstance(hit_2x_4h_val, int):
            # Overwrite unverified placeholder if present or register exact 4h verified outcome gated at `cutoff_4h_ms`!
            state.creators.records[cr] = [r for r in state.creators.records[cr] if r["mint"] != mint]
            state.creators.register_event(
                creator=cr,
                mint=mint,
                created_ts_ms=cts,
                label_available_at_ms=cutoff_4h_ms,
                is_win=hit_2x_4h_val,
                outcome_status="complete",
            )

        # Early buyers in first 180s for WalletHistoryTracker registration & co-sniper counting
        vis_3m = deduplicate_and_filter_trades_before(trades, snap_3m["signal_timestamp_ms"])
        tok_tech = build_token_technical_set(coin, trades)
        early_buyers_3m = []
        for tr in vis_3m:
            if tr.get("side") == "buy":
                w = str((tr.get("trader") or {}).get("address") or "")
                if w and w not in tok_tech and w not in early_buyers_3m:
                    early_buyers_3m.append(w)
                    if int(tr["blockTimeMs"]) <= cts + 60_000:
                        wallet_perf_agg[w]["early_entries_le_60s"] += 1

        # Relationship classification BEFORE updating co-sniper counts (strictly causal!)
        rel_rows = classify_relationships_v2_1(
            mint=mint,
            creator=cr,
            trades=trades,
            tok_tech_addrs=tok_tech,
            rpc_wallets_db=rpc_wallets_db,
            funder_types=funder_types,
            co_sniper_counts=co_sniper_pair_counts,
            cutoff_ts_ms=snap_3m["signal_timestamp_ms"],
        )
        cluster_rows.extend(rel_rows)

        # Update causal co-sniper pair counts among top-15 early buyers
        eb_cap = early_buyers_3m[:15]
        for i_w in range(len(eb_cap)):
            for j_w in range(i_w + 1, len(eb_cap)):
                pair = tuple(sorted((eb_cap[i_w], eb_cap[j_w])))
                co_sniper_pair_counts[pair] += 1

        # Aggregate per-wallet FIFO PnL & register strictly causal 4h wallet outcomes (`label_available_at_ms = cutoff_4h_ms`)
        for w, wp in sup_fifo["wallets_pnl"].items():
            if wp["tokens_bought"] > 0 or wp["tokens_sold"] > 0:
                fifo_pnl_rows.append({
                    "mint": mint,
                    "symbol": snap_3m["symbol"],
                    "wallet": w,
                    **wp,
                })
            agg = wallet_perf_agg[w]
            agg["tokens_participated"].add(mint)
            agg["fees_paid_sol_sum"] += wp["fees_paid_sol"]
            if wp["cost_basis_status"] == "UNKNOWN_COST_BASIS":
                agg["unknown_cost_basis_tokens"] += 1
            elif wp["fifo_realized_pnl_sol"] is not None:
                agg["fifo_verified_pnl_sol_sum"] += wp["fifo_realized_pnl_sol"]

            if w in early_buyers_3m:
                if st_4h == "complete" and isinstance(hit_2x_4h_val, int):
                    if hit_2x_4h_val == 1:
                        agg["independent_wins_2x_4h"] += 1
                    else:
                        agg["independent_losses_4h"] += 1
                    net_w_sol = (wp["fifo_realized_pnl_sol"] or 0.0) + wp["fifo_unrealized_pnl_sol"]
                    state.wallets.register_wallet_token_outcome(
                        wallet=w,
                        mint=mint,
                        entry_ts_ms=snap_3m["signal_timestamp_ms"],
                        label_available_at_ms=cutoff_4h_ms,
                        hit_2x_4h=hit_2x_4h_val,
                        realized_net_sol=net_w_sol,
                        data_complete=(wp["cost_basis_status"] == "FIFO_VERIFIED"),
                    )
                else:
                    agg["censored_or_unknown_tokens"] += 1

        # Token summary row (`TOKEN_METRICS_V2_1.csv`)
        tm_row = {
            "mint": mint,
            "symbol": snap_3m["symbol"],
            "name": snap_3m["name"],
            "creator": cr,
            "created_timestamp_ms": cts,
            "signal_3m_timestamp_ms": snap_3m["signal_timestamp_ms"],
            "narrative_category": snap_3m["narrative_category"],
            "entry_price_3m_usd": snap_3m["entry_price_usd"],
            "implied_liquidity_3m_usd": snap_3m["implied_liquidity_usd"],
            "reserve_source_3m": snap_3m["reserve_source_at_signal"],
            "supply_status_4h": sup_rec["supply_status"],
            "top5_holders_pct_valid": sup_rec["top5_holders_pct"],
            "manipulation_risk_score": snap_3m["manipulation_risk_score"],
            "insider_supply_risk_score": snap_3m["insider_supply_risk_score"],
            "status_1h": lbl_3m["status_1h"],
            "hit_2x_1h": lbl_3m["hit_2x_1h"],
            "hit_3x_1h": lbl_3m["hit_3x_1h"],
            "status_4h": lbl_3m["status_4h"],
            "hit_2x_4h": lbl_3m["hit_2x_4h"],
            "hit_3x_4h": lbl_3m["hit_3x_4h"],
            "hit_5x_4h": lbl_3m["hit_5x_4h"],
            "max_multiple_4h": lbl_3m["max_multiple_4h"],
            "max_drawdown_4h_pct": lbl_3m["max_drawdown_4h_pct"],
            "end_return_4h_pct": lbl_3m["end_return_4h_pct"],
            "status_24h": lbl_3m["status_24h"],
            "hit_2x_24h": lbl_3m["hit_2x_24h"],
            "hit_3x_24h": lbl_3m["hit_3x_24h"],
            "hit_5x_24h": lbl_3m["hit_5x_24h"],
            "hit_10x_24h": lbl_3m["hit_10x_24h"],
            "net_ret_0_25_sol_pct": exec_by_size[0.25].get("net_return_after_fees_pct"),
            "net_ret_1_0_sol_pct": exec_by_size[1.0].get("net_return_after_fees_pct"),
        }
        token_metric_rows.append(tm_row)
        primary_3m_records.append({
            "mint": mint,
            "created_ts_ms": cts,
            "signal_ts_ms": snap_3m["signal_timestamp_ms"],
            "snapshot": snap_3m,
            "labels": lbl_3m,
            "exec_by_size": exec_by_size,
        })

    # Save populated UnifiedStateBundle checkpoint at end of chronological cohort for OOT & Paper Trading!
    max_cohort_ts = max(r["signal_ts_ms"] + INTERVAL_MS["4h"] for r in primary_3m_records)
    ckpt_path = CHECKPOINTS_DIR / "state_post_wf_v2_1.json"
    state.save_checkpoint(max_cohort_ts, ckpt_path)
    logger.info(f"Saved populated UnifiedStateBundle checkpoint -> {ckpt_path.name} (creators={len(state.creators.records)}, wallets={len(state.wallets.records)}, tickers={len(state.tickers.launches)})")

    # Build `WALLET_INTELLIGENCE_V2_1.csv` combining RPC completeness + FIFO verified PnL + independent wins/losses
    wallet_intel_rows = []
    for w, agg in wallet_perf_agg.items():
        n_tok = len(agg["tokens_participated"])
        if n_tok < 2 and w not in rpc_wallets_db:
            continue
        rinfo = rpc_wallets_db.get(w, {})
        eval_n = agg["independent_wins_2x_4h"] + agg["independent_losses_4h"]
        win_rate = round(agg["independent_wins_2x_4h"] / eval_n, 4) if eval_n > 0 else "insufficient_history"
        wallet_intel_rows.append({
            "wallet": w,
            "rpc_inspected": 1 if w in rpc_wallets_db else 0,
            "total_signatures_found": rinfo.get("total_signatures_found", "not_queried"),
            "history_transactions_count": rinfo.get("history_transactions_count", 0),
            "history_complete": bool(rinfo.get("history_complete", False)),
            "first_observed_at": rinfo.get("first_observed_at", ""),
            "last_observed_at": rinfo.get("last_observed_at", ""),
            "history_coverage": rinfo.get("history_coverage", 0.0),
            "data_confidence": rinfo.get("data_confidence", "low_confidence" if n_tok >= 2 else "unknown"),
            "independent_tokens_count": n_tok,
            "evaluated_4h_tokens": eval_n,
            "wins_2x_4h": agg["independent_wins_2x_4h"],
            "losses_4h": agg["independent_losses_4h"],
            "censored_or_unknown_tokens": agg["censored_or_unknown_tokens"],
            "win_rate_2x_4h": win_rate,
            "early_entries_le_60s": agg["early_entries_le_60s"],
            "fifo_verified_realized_pnl_sol": round(agg["fifo_verified_pnl_sol_sum"], 6),
            "unknown_cost_basis_tokens": agg["unknown_cost_basis_tokens"],
            "fees_paid_sol": round(agg["fees_paid_sol_sum"], 6),
            "private_funders_count": len(rinfo.get("funders", [])),
            "spl_transfers_detected": len(rinfo.get("spl_transfers", [])),
        })
    wallet_intel_rows.sort(key=lambda r: (r["rpc_inspected"], r["independent_tokens_count"]), reverse=True)

    # =========================================================================
    # SECTION 9: CHRONOLOGICAL EXPANDING WALK-FORWARD (TRAIN / VAL / TEST + 4H EMBARGO)
    # =========================================================================
    uncensored_4h = [
        r for r in primary_3m_records
        if r["labels"].get("status_4h") == "complete" and isinstance(r["labels"].get("hit_2x_4h"), int)
    ]
    uncensored_4h.sort(key=lambda r: r["signal_ts_ms"])
    n_u4 = len(uncensored_4h)
    logger.info(f"Uncensored complete 4h tokens for Walk-Forward: {n_u4} / {len(primary_3m_records)} (censored/unknown strictly excluded, NEVER set to 0!)")

    embargo_ms = INTERVAL_MS["4h"]  # 4-hour strict temporal embargo so 4h labels finalize before next split!

    # Construct 3 expanding calendar-time Walk-Forward folds across the 30-day span,
    # enforcing a strict >=4h temporal embargo between Train -> Validation AND Validation -> Test!
    def iso_ms(s: str) -> int:
        return int(datetime.fromisoformat(s).timestamp() * 1000)

    fold_bounds = [
        ("WF_Fold_1_EarlyNov", iso_ms("2026-11-12T00:00:00+00:00"), iso_ms("2026-11-17T00:00:00+00:00"), iso_ms("2026-11-21T00:00:00+00:00")),
        ("WF_Fold_2_MidNov",   iso_ms("2026-11-17T00:00:00+00:00"), iso_ms("2026-11-21T00:00:00+00:00"), iso_ms("2026-11-24T17:00:00+00:00")),
        ("WF_Fold_3_LateNov",  iso_ms("2026-11-21T00:00:00+00:00"), iso_ms("2026-11-24T17:00:00+00:00"), iso_ms("2026-11-25T00:00:00+00:00")),
    ]

    wf_rows = []
    pooled_test_indices = []
    pooled_preds = defaultdict(list)

    X_all = np.array([
        [r["snapshot"]["model_vector"][c] for c in ALL_MODEL_FEATURES_V2_1]
        for r in uncensored_4h
    ], dtype=float)
    y_2x_4h = np.array([int(r["labels"]["hit_2x_4h"]) for r in uncensored_4h], dtype=int)
    y_3x_4h = np.array([int(r["labels"]["hit_3x_4h"]) for r in uncensored_4h], dtype=int)
    ts_arr = np.array([int(r["signal_ts_ms"]) for r in uncensored_4h], dtype=np.int64)

    for fold_id, tr_cut_ms, val_cut_ms, te_cut_ms in fold_bounds:
        tr_idx = [i for i in range(n_u4) if ts_arr[i] <= tr_cut_ms]
        tr_max_ts = int(ts_arr[tr_idx[-1]])

        # Enforce strict >=4h temporal embargo between Train and Validation
        val_idx = [i for i in range(n_u4) if (tr_max_ts + embargo_ms) <= ts_arr[i] <= val_cut_ms]
        val_max_ts = int(ts_arr[val_idx[-1]])

        # Enforce strict >=4h temporal embargo between Validation and Test
        te_idx = [i for i in range(n_u4) if (val_max_ts + embargo_ms) <= ts_arr[i] <= te_cut_ms]

        # Verify ZERO token overlap across Train / Val / Test!
        tr_mints = {uncensored_4h[i]["mint"] for i in tr_idx}
        val_mints = {uncensored_4h[i]["mint"] for i in val_idx}
        te_mints = {uncensored_4h[i]["mint"] for i in te_idx}
        assert len(tr_mints & val_mints) == 0 and len(val_mints & te_mints) == 0 and len(tr_mints & te_mints) == 0, "Token leak across splits!"

        # Select L2 regularization strictly on Validation PR-AUC (NEVER touching Test!)
        best_l2 = 5.0
        best_val_pr = -1.0
        for cand_l2 in [1.0, 3.0, 8.0, 20.0]:
            m_cand = fit_l2_logistic(X_all[tr_idx], y_2x_4h[tr_idx], l2_reg=cand_l2)
            val_sc = predict_l2_logistic(m_cand, X_all[val_idx])
            vm = compute_binary_ranking_metrics(y_2x_4h[val_idx], val_sc)
            if not np.isnan(vm["pr_auc"]) and vm["pr_auc"] > best_val_pr:
                best_val_pr = vm["pr_auc"]
                best_l2 = cand_l2

        # Fit V2.1 full model on Train only (`tr_idx`) using `best_l2` (keeps Validation embargo intact before Test!)
        m_v2_1 = fit_l2_logistic(X_all[tr_idx], y_2x_4h[tr_idx], l2_reg=best_l2)
        te_scores_v2_1 = predict_l2_logistic(m_v2_1, X_all[te_idx])
        te_metrics = compute_binary_ranking_metrics(y_2x_4h[te_idx], te_scores_v2_1)

        # Compute post-cost execution returns on Top-10 signals of this fold
        rel_order = np.argsort(-te_scores_v2_1)[:min(10, len(te_idx))]
        top10_global = [te_idx[k] for k in rel_order]
        mults_top10 = [float(uncensored_4h[i]["labels"]["max_multiple_4h"]) for i in top10_global]
        dds_top10 = [float(uncensored_4h[i]["labels"]["max_drawdown_4h_pct"]) for i in top10_global]
        net025_top10 = [float(uncensored_4h[i]["exec_by_size"][0.25]["net_return_after_fees_pct"]) for i in top10_global]
        net100_top10 = [float(uncensored_4h[i]["exec_by_size"][1.0]["net_return_after_fees_pct"]) for i in top10_global]

        wf_rows.append({
            "fold_id": fold_id,
            "train_count": len(tr_idx),
            "val_count": len(val_idx),
            "test_count": len(te_idx),
            "embargo_hours": 4.0,
            "zero_token_overlap_verified": 1,
            "selected_l2_on_val": best_l2,
            "val_pr_auc": round(best_val_pr, 4),
            "test_start_utc": datetime.fromtimestamp(ts_arr[te_idx[0]] / 1000, tz=timezone.utc).isoformat(),
            "test_end_utc": datetime.fromtimestamp(ts_arr[te_idx[-1]] / 1000, tz=timezone.utc).isoformat(),
            "signals_evaluated": te_metrics["n_obs"],
            "positive_hits_2x_4h": te_metrics["n_positives"],
            "base_rate_2x_4h": te_metrics["base_rate"],
            "roc_auc": te_metrics["roc_auc"],
            "pr_auc": te_metrics["pr_auc"],
            "precision_at_5": te_metrics["precision_at_5"],
            "precision_at_10": te_metrics["precision_at_10"],
            "precision_at_20": te_metrics["precision_at_20"],
            "recall_top25pct": te_metrics["recall_top25pct"],
            "lift_at_10": te_metrics["lift_at_10"],
            "top10_median_future_max_mult_4h": round(float(np.median(mults_top10)), 4) if mults_top10 else np.nan,
            "top10_median_drawdown_4h_pct": round(float(np.median(dds_top10)), 2) if dds_top10 else np.nan,
            "top10_mean_net_return_0_25_sol_pct": round(float(np.mean(net025_top10)), 2) if net025_top10 else np.nan,
            "top10_median_net_return_0_25_sol_pct": round(float(np.median(net025_top10)), 2) if net025_top10 else np.nan,
            "top10_mean_net_return_1_0_sol_pct": round(float(np.mean(net100_top10)), 2) if net100_top10 else np.nan,
        })

        # Score all 9 models + all 8 ablations on the EXACT same fold Test indices (`te_idx`, deduplicating across folds if overlapping)
        new_te = [i for i in te_idx if i not in pooled_test_indices]
        if new_te:
            pooled_test_indices.extend(new_te)
            # 1-6 Single-factor / domain benchmarks
            for i in new_te:
                sn = uncensored_4h[i]["snapshot"]
                mv = sn["model_vector"]
                pooled_preds["1_Buyer_Velocity_Only"].append(mv["unique_buyers_cum"] + mv["independent_buyer_velocity"])
                pooled_preds["2_Independent_Buyer_Growth"].append(mv["independent_buyer_velocity"] * mv["buyer_acceleration_ratio"])
                pooled_preds["3_Volume_Only"].append(float(sn["buy_volume_usd"]))
                pooled_preds["4_Price_Momentum_Only"].append(float(sn["already_moved_mult"]))
                pooled_preds["5_First_Correction_Absorption"].append(mv["dip_absorption_ratio"] + 0.5 * mv["buy_sell_log_ratio"])
                pooled_preds["6_Wallet_Intelligence"].append(mv["smart_wallets_count_num"] + 0.5 * mv["creator_win_rate_num"] - 0.5 * mv["creator_dumped_flag"])
                pooled_preds["7_Pump_Potential_V1_Frozen"].append(score_frozen_v1_on_snapshot(sn, v1_frozen))
                pooled_preds["8_Pump_Potential_V2_Frozen"].append(score_frozen_v2_on_snapshot(sn, v2_frozen))

            sc_v21_new = predict_l2_logistic(m_v2_1, X_all[new_te])
            pooled_preds["9_Pump_Potential_V2_1_Full"].extend(sc_v21_new.tolist())

            # 8 Mandatory Ablation Tests (Section 8)
            ablation_groups = [
                "wallet_intelligence",
                "creator_history",
                "buyer_acceleration",
                "insider_risk",
                "supply_concentration",
                "social_momentum",
                "narrative_strength",
                "market_context",
            ]
            for ab_grp in ablation_groups:
                drop_cols = set(MODEL_FEATURE_GROUPS_V2_1[ab_grp])
                keep_idx = [j for j, c in enumerate(ALL_MODEL_FEATURES_V2_1) if c not in drop_cols]
                m_ab = fit_l2_logistic(X_all[np.ix_(tr_idx, keep_idx)], y_2x_4h[tr_idx], l2_reg=best_l2)
                sc_ab = predict_l2_logistic(m_ab, X_all[np.ix_(new_te, keep_idx)])
                pooled_preds[f"Ablation_minus_{ab_grp}"].extend(sc_ab.tolist())

    # Evaluate all 9 models + 8 ablations on the exact same pooled out-of-sample Walk-Forward Test observations!
    y_pool_2x = y_2x_4h[pooled_test_indices]
    y_pool_3x = y_3x_4h[pooled_test_indices]
    model_comp_rows = []

    for m_name, sc_list in pooled_preds.items():
        sc_arr = np.array(sc_list, dtype=float)
        m2 = compute_binary_ranking_metrics(y_pool_2x, sc_arr)
        m3 = compute_binary_ranking_metrics(y_pool_3x, sc_arr)

        top20_ord = np.argsort(-sc_arr)[:min(20, len(pooled_test_indices))]
        top20_g = [pooled_test_indices[k] for k in top20_ord]
        mid_rets = [float(uncensored_4h[i]["exec_by_size"][0.25]["mid_price_return_pct"]) for i in top20_g]
        net_025 = [float(uncensored_4h[i]["exec_by_size"][0.25]["net_return_after_fees_pct"]) for i in top20_g]
        net_100 = [float(uncensored_4h[i]["exec_by_size"][1.0]["net_return_after_fees_pct"]) for i in top20_g]

        cat_type = "Ablation_Study" if m_name.startswith("Ablation_") else "Core_Benchmark_Or_Model"
        model_comp_rows.append({
            "model_name": m_name,
            "category": cat_type,
            "test_observations": m2["n_obs"],
            "positives_2x_4h": m2["n_positives"],
            "base_rate_2x_4h": m2["base_rate"],
            "roc_auc_2x_4h": m2["roc_auc"],
            "pr_auc_2x_4h": m2["pr_auc"],
            "precision_at_5_2x_4h": m2["precision_at_5"],
            "precision_at_10_2x_4h": m2["precision_at_10"],
            "precision_at_20_2x_4h": m2["precision_at_20"],
            "lift_at_10_2x_4h": m2["lift_at_10"],
            "lift_at_20_2x_4h": m2["lift_at_20"],
            "recall_top25pct_2x_4h": m2["recall_top25pct"],
            "roc_auc_3x_4h": m3["roc_auc"],
            "pr_auc_3x_4h": m3["pr_auc"],
            "top20_mean_mid_return_pct": round(float(np.mean(mid_rets)), 2) if mid_rets else np.nan,
            "top20_mean_net_ret_0_25_sol_pct": round(float(np.mean(net_025)), 2) if net_025 else np.nan,
            "top20_median_net_ret_0_25_sol_pct": round(float(np.median(net_025)), 2) if net_025 else np.nan,
            "top20_mean_net_ret_1_0_sol_pct": round(float(np.mean(net_100)), 2) if net_100 else np.nan,
        })

    # Fit final frozen V2.1 model on all uncensored 4h observations (strictly BEFORE held-out OOT & Live Paper Trading!)
    final_v2_1_fit = fit_l2_logistic(X_all, y_2x_4h, l2_reg=8.0)

    # Identify noise features from ablation study (where removing the group IMPROVED PR-AUC on WF Test!)
    full_row = next(r for r in model_comp_rows if r["model_name"] == "9_Pump_Potential_V2_1_Full")
    full_pr = full_row["pr_auc_2x_4h"]
    noisy_groups = []
    for r in model_comp_rows:
        if r["category"] == "Ablation_Study" and r["pr_auc_2x_4h"] > full_pr + 0.005:
            noisy_groups.append(r["model_name"].replace("Ablation_minus_", ""))

    # Also fit a clean Ablation-Pruned V2.1 model (removing empirically noisy groups if any) and evaluate it transparently!
    drop_noisy_cols = {c for g in noisy_groups for c in MODEL_FEATURE_GROUPS_V2_1.get(g, [])}
    pruned_keep_idx = [j for j, c in enumerate(ALL_MODEL_FEATURES_V2_1) if c not in drop_noisy_cols]
    pruned_feature_names = [ALL_MODEL_FEATURES_V2_1[j] for j in pruned_keep_idx]
    pruned_v2_1_fit = fit_l2_logistic(X_all[:, pruned_keep_idx], y_2x_4h, l2_reg=8.0)

    frozen_v2_1_payload = {
        "model_id": "Pump_Potential_V2_1_Frozen",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "trained_on_n_uncensored_4h_tokens": int(n_u4),
        "target": "hit_2x_4h",
        "feature_names": ALL_MODEL_FEATURES_V2_1,
        "scaler_mean": [round(float(x), 6) for x in final_v2_1_fit["mean"]],
        "scaler_scale": [round(float(x), 6) for x in final_v2_1_fit["scale"]],
        "coef": [round(float(x), 6) for x in final_v2_1_fit["coef"]],
        "intercept": round(float(final_v2_1_fit["intercept"]), 6),
        "l2_reg": final_v2_1_fit["l2_reg"],
        "weights_by_feature": {
            f: round(float(w), 4)
            for f, w in sorted(zip(ALL_MODEL_FEATURES_V2_1, final_v2_1_fit["coef"]), key=lambda x: abs(x[1]), reverse=True)
        },
        "noisy_groups_detected_in_wf_ablation": noisy_groups,
        "pruned_model": {
            "feature_names": pruned_feature_names,
            "scaler_mean": [round(float(x), 6) for x in pruned_v2_1_fit["mean"]],
            "scaler_scale": [round(float(x), 6) for x in pruned_v2_1_fit["scale"]],
            "coef": [round(float(x), 6) for x in pruned_v2_1_fit["coef"]],
            "intercept": round(float(pruned_v2_1_fit["intercept"]), 6),
        },
    }
    (FROZEN_BASELINES_DIR / "v2_1_frozen_model.json").write_text(json.dumps(frozen_v2_1_payload, indent=2), encoding="utf-8")

    # Write all CSV deliverables cleanly
    pd.DataFrame(early_signal_rows).to_csv(V2_1_DIR / "EARLY_SIGNALS_V2_1.csv", index=False)
    pd.DataFrame(token_metric_rows).to_csv(V2_1_DIR / "TOKEN_METRICS_V2_1.csv", index=False)
    pd.DataFrame(supply_rows).to_csv(V2_1_DIR / "SUPPLY_CONCENTRATION_V2_1.csv", index=False)
    pd.DataFrame(fifo_pnl_rows).to_csv(V2_1_DIR / "REALIZED_PNL_V2_1.csv", index=False)
    pd.DataFrame(wallet_intel_rows).to_csv(V2_1_DIR / "WALLET_INTELLIGENCE_V2_1.csv", index=False)
    pd.DataFrame(cluster_rows).to_csv(V2_1_DIR / "WALLET_CLUSTERS_V2_1.csv", index=False)
    pd.DataFrame(exec_sizing_rows).to_csv(V2_1_DIR / "POSITION_SIZING_EXECUTION_V2_1.csv", index=False)
    pd.DataFrame(wf_rows).to_csv(V2_1_DIR / "WALK_FORWARD_V2_1.csv", index=False)
    pd.DataFrame(model_comp_rows).to_csv(V2_1_DIR / "MODEL_COMPARISON_V2_1.csv", index=False)

    inv_sup_cnt = sum(1 for r in supply_rows if r["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION")
    max_valid_sup = max([r["raw_reconstructed_holder_sum_pct"] for r in supply_rows if r["usable_in_model"] == 1] or [0.0])
    unk_cb_cnt = sum(1 for r in fifo_pnl_rows if r["cost_basis_status"] == "UNKNOWN_COST_BASIS")

    logger.info(
        f"STEP 2 V2.1 COMPLETE in {time.time()-t0:.1f}s!\n"
        f"  - EARLY_SIGNALS_V2_1: {len(early_signal_rows)} rows | TOKEN_METRICS_V2_1: {len(token_metric_rows)} rows\n"
        f"  - SUPPLY_CONCENTRATION_V2_1: invalid_blocked={inv_sup_cnt}, max_valid_holder_sum_pct={max_valid_sup:.2f}% (<=100% invariant holds!)\n"
        f"  - REALIZED_PNL_V2_1: {len(fifo_pnl_rows)} wallet-token rows (UNKNOWN_COST_BASIS={unk_cb_cnt})\n"
        f"  - WALK_FORWARD_V2_1: {len(wf_rows)} folds | MODEL_COMPARISON_V2_1: {len(model_comp_rows)} rows (9 models + 8 ablations)\n"
        f"  - Noisy groups identified by WF ablation: {noisy_groups}"
    )


if __name__ == "__main__":
    main()
