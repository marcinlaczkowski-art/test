"""
SECTIONS 5, 7, 9.4 & 11.2 (EXACT AMM BACKTEST, HYPOTHESIS VALIDATION H1–H5 & METRICS WITH DENOMINATORS):
- Computes post-signal fixed-horizon outcomes (`2x_1h`, `2x_4h`, `3x_4h`, `5x_24h`, `max_multiple`,
  `max_drawdown`, `time_to_ath_sec`, and realistic reserve-based net profit after costs across `0.1–2.0 SOL`).
- Strictly excludes `RESERVE_RECONSTRUCTION_INCOMPLETE` records from the Exact Backtest (reporting them
  separately as incomplete/estimated only).
- Evaluates H1–H5 individually and combined (`ConfluenceScorer`), plus regime breakdowns (`BULL`/`BEAR`/`SIDEWAYS`,
  `HIGH_VOL`/`LOW_VOL`), formatting every rate with its explicit denominator (e.g. `4/20 = 20.00%`).
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from scipy.stats import rankdata

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import (
    V2_ROOT, V2_1_ROOT, DATA_DIR, BACKTESTING_DIR,
    INTERVAL_MS, POSITION_SIZES_SOL, PAPER_TP_MULT, PAPER_SL_MULT,
)
from data_integrity.temporal_ledger import TemporalIntegrityLedger
from amm_reconstruction.amm_reconstructor import (
    deduplicate_and_order_swaps,
    reconstruct_reserve_state_at,
    compute_realistic_swap_quote,
)
from wallet_intelligence.wallet_intel_v2_2 import WalletIntelligenceEngineV22
from feature_engine.feature_engine import SharedFeatureEngineV22, CausalMarketRegimeTracker
from scoring.confluence_scorer import score_multi_signal_confluence


def wilson_ci_95(k: int, n: int) -> tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return (None, None)
    z = 1.959964
    p = k / n
    den = 1.0 + z * z / n
    ctr = (p + z * z / (2.0 * n)) / den
    hlf = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / den
    return (round(max(0.0, ctr - hlf), 4), round(min(1.0, ctr + hlf), 4))


def fmt_ratio(k: int, n: int) -> str:
    if n <= 0:
        return "0/0 (N/A)"
    return f"{k}/{n} ({100.0 * k / n:.2f}%)"


def compute_post_signal_outcomes_and_exit_state(
    coin: dict,
    trades: list,
    candles_obj: dict,
    cutoff_ts_ms: int,
    entry_state: dict,
    is_tape_complete: bool = True,
) -> dict:
    """
    Computes strictly post-signal (`t > cutoff_ts_ms`) outcomes for:
      - `hit_2x_1h`
      - `hit_2x_4h` (primary target)
      - `hit_3x_4h`
      - `hit_5x_24h`
      - `max_multiple_4h`, `max_drawdown_4h_pct`, `time_to_ath_4h_sec`
    and reconstructs the realistic exit reserve state for position execution across `0.1–2.0 SOL`
    (NEVER assuming exit at ATH — uses conservative SL -> TP -> 4h Time-Stop path!).
    """
    coll_ts = int(candles_obj.get("collection_timestamp_ms") or 0)
    c1m = candles_obj.get("candles_1m") or []
    c15m = candles_obj.get("candles_15m") or []
    c4h = candles_obj.get("candles_4h") or []
    api_ok = bool(candles_obj.get("api_ok", False))

    all_swaps = deduplicate_and_order_swaps(trades, cutoff_ts_ms=None)
    post_swaps = [tr for tr in all_swaps if int(tr["blockTimeMs"]) > cutoff_ts_ms]
    has_feed = api_ok or len(all_swaps) > 0 or (not api_ok and len(all_swaps) == 0 and coll_ts > cutoff_ts_ms)

    sol_px_ref = 70.0
    for tr in reversed(all_swaps):
        if int(tr["blockTimeMs"]) <= cutoff_ts_ms and float(tr.get("quotePriceUsd") or 0) > 5.0:
            sol_px_ref = float(tr["quotePriceUsd"])
            break

    entry_mid_sol = entry_state.get("mid_price_sol")
    if not entry_mid_sol or entry_mid_sol <= 0:
        return {
            "status_1h": "UNKNOWN", "hit_2x_1h": "UNKNOWN",
            "status_4h": "UNKNOWN", "hit_2x_4h": "UNKNOWN", "hit_3x_4h": "UNKNOWN",
            "status_24h": "UNKNOWN", "hit_5x_24h": "UNKNOWN",
            "max_multiple_4h": None, "max_drawdown_4h_pct": None, "time_to_ath_4h_sec": None,
            "exec_by_size": {}, "estimated_exec_by_size": {},
        }

    entry_px_usd = entry_mid_sol * sol_px_ref

    def eval_horizon(h_ms: int, bars_extra: list) -> dict:
        end_ts = cutoff_ts_ms + h_ms
        if coll_ts <= 0 or not has_feed:
            return {"status": "UNKNOWN"}
        if coll_ts < end_ts:
            return {"status": "CENSORED"}

        pts = []  # (ts_ms, hi_mult, lo_mult, cl_mult)
        for bars, dur in [(c1m, INTERVAL_MS["1m"])] + bars_extra:
            for b in bars:
                ot = int(b.get("openTimeMs") or 0)
                ct = ot + dur
                if ot >= cutoff_ts_ms and ct <= end_ts and float(b.get("close") or 0) > 0:
                    cl = float(b["close"])
                    hi = float(b.get("high") or cl)
                    lo = float(b.get("low") or cl)
                    vol = float(b.get("volume") or 0.0)
                    eff_hi = hi if (vol >= 25.0 or hi <= cl * 8.0) else cl
                    pts.append((ct, eff_hi / entry_px_usd, (lo if lo > 0 else cl) / entry_px_usd, cl / entry_px_usd))

        for tr in post_swaps:
            tms = int(tr["blockTimeMs"])
            if cutoff_ts_ms < tms <= end_ts and (float(tr.get("valueNative") or 0) >= 0.05 or float(tr.get("valueUsd") or 0) >= 5.0):
                pq = float(tr.get("priceQuote") or 0.0)
                m_tr = (pq / entry_mid_sol) if pq > 0 else (float(tr.get("priceUsd") or 0.0) / entry_px_usd)
                if m_tr > 0:
                    pts.append((tms, m_tr, m_tr, m_tr))

        pts.sort(key=lambda x: x[0])
        max_m = 1.0
        min_m = 1.0
        ath_ts = cutoff_ts_ms
        for ev_ts, hi_m, lo_m, _ in pts:
            if hi_m > max_m:
                max_m = hi_m
                ath_ts = ev_ts
            if lo_m < min_m:
                min_m = lo_m

        return {
            "status": "COMPLETE",
            "max_mult": round(max_m, 4),
            "max_dd_pct": round((min_m - 1.0) * 100.0, 2),
            "time_to_ath_sec": round((ath_ts - cutoff_ts_ms) / 1000.0, 1) if max_m > 1.0 else 0.0,
            "pts": pts,
        }

    h1 = eval_horizon(INTERVAL_MS["1h"], [])
    h4 = eval_horizon(INTERVAL_MS["4h"], [(c15m, INTERVAL_MS["15m"])])
    h24 = eval_horizon(INTERVAL_MS["24h"], [(c15m, INTERVAL_MS["15m"]), (c4h, INTERVAL_MS["4h"])])

    out = {
        "status_1h": h1["status"],
        "hit_2x_1h": (1 if h1["max_mult"] >= 2.0 else 0) if h1["status"] == "COMPLETE" else h1["status"],
        "status_4h": h4["status"],
        "hit_2x_4h": (1 if h4["max_mult"] >= 2.0 else 0) if h4["status"] == "COMPLETE" else h4["status"],
        "hit_3x_4h": (1 if h4["max_mult"] >= 3.0 else 0) if h4["status"] == "COMPLETE" else h4["status"],
        "status_24h": h24["status"],
        "hit_5x_24h": (1 if h24["max_mult"] >= 5.0 else 0) if h24["status"] == "COMPLETE" else h24["status"],
        "max_multiple_4h": h4.get("max_mult"),
        "max_drawdown_4h_pct": h4.get("max_dd_pct"),
        "time_to_ath_4h_sec": h4.get("time_to_ath_sec"),
        "exec_by_size": {},
        "estimated_exec_by_size": {},
    }

    if h4["status"] == "COMPLETE":
        # Determine realistic non-ATH exit timestamp & price along post-signal path (SL checked BEFORE TP!)
        exit_ts_ms = cutoff_ts_ms + INTERVAL_MS["4h"]
        exit_mult = 1.0
        exit_reason = "CLOSED_TIME_4H"
        for ev_ts, hi_m, lo_m, cl_m in h4["pts"]:
            if lo_m <= PAPER_SL_MULT:
                exit_ts_ms = ev_ts
                exit_mult = PAPER_SL_MULT
                exit_reason = "CLOSED_SL"
                break
            if hi_m >= PAPER_TP_MULT:
                exit_ts_ms = ev_ts
                exit_mult = PAPER_TP_MULT
                exit_reason = "CLOSED_TP"
                break
            exit_mult = cl_m

        # Reconstruct reserve state at `exit_ts_ms` from actual swap tape if available;
        # if candle-triggered between swaps on bonding curve, derive curve state from invariant `k_0` ONLY if still on curve!
        exit_state = reconstruct_reserve_state_at(coin, all_swaps, exit_ts_ms, is_tape_complete_from_genesis=is_tape_complete)
        if exit_state["usable_in_exact_backtest"] and exit_state["market_state"] == "ON_BONDING_CURVE":
            target_exit_sol = max(1e-14, entry_mid_sol * exit_mult)
            # Check graduation threshold (~85 real SOL -> ~5.558e-7 SOL/tok)
            if target_exit_sol < (115.0 / 206_900_000.0):
                from config.settings_v2_2 import PUMPFUN_INIT_K, PUMPFUN_INIT_VIRTUAL_SOL, PUMPFUN_INIT_VIRTUAL_TOKENS, PUMPFUN_INIT_REAL_TOKEN_RESERVES
                v_s = math.sqrt(PUMPFUN_INIT_K * target_exit_sol)
                v_t = math.sqrt(PUMPFUN_INIT_K / target_exit_sol)
                exit_state = dict(
                    exit_state,
                    virtual_sol_reserve=round(v_s, 6),
                    virtual_token_reserve=round(v_t, 2),
                    real_sol_reserve=round(max(0.0, v_s - PUMPFUN_INIT_VIRTUAL_SOL), 6),
                    real_token_reserve=round(max(0.0, v_t - (PUMPFUN_INIT_VIRTUAL_TOKENS - PUMPFUN_INIT_REAL_TOKEN_RESERVES)), 2),
                    mid_price_sol=target_exit_sol,
                )
            else:
                # Crossed graduation into external AMM without LP reserve tape -> mark INCOMPLETE for exact backtest!
                exit_state = dict(
                    exit_state,
                    market_state="MIGRATED_TO_AMM",
                    virtual_sol_reserve=None,
                    virtual_token_reserve=None,
                    estimated_amm_sol_reserve_only=round(math.sqrt(85.0 * 206_900_000.0 * target_exit_sol), 4),
                    estimated_amm_token_reserve_only=round(math.sqrt(85.0 * 206_900_000.0 / target_exit_sol), 2),
                    mid_price_sol=target_exit_sol,
                    reserve_completeness="RESERVE_RECONSTRUCTION_INCOMPLETE",
                    usable_in_exact_backtest=False,
                    execution_confidence="LOW_ESTIMATED_ONLY",
                )

        out["exit_reason_4h"] = exit_reason
        out["exit_reserve_completeness"] = exit_state.get("reserve_completeness")
        for s_sol in POSITION_SIZES_SOL:
            exact_q = compute_realistic_swap_quote(entry_state, exit_state, s_sol, allow_estimated_fallback=False)
            est_q = compute_realistic_swap_quote(entry_state, exit_state, s_sol, allow_estimated_fallback=True)
            out["exec_by_size"][s_sol] = exact_q
            out["estimated_exec_by_size"][s_sol] = est_q

    return out


def compute_full_evaluation_metrics(
    y_true: np.ndarray,
    scores_0_100: np.ndarray,
    net_returns_pct: np.ndarray,
    max_drawdowns_pct: np.ndarray,
    positive_threshold_0_100: float = 36.0,
) -> dict:
    """
    Section 9.4 Complete Metric Suite WITH EXPLICIT DENOMINATORS on every metric:
    ROC-AUC, PR-AUC, Precision@5, Precision@10, Precision@20, Recall, F1, Lift,
    Brier Score, Calibration error, Mean/Median Net Return, Win Rate, Max Drawdown, Expectancy, 95% CI.
    """
    n = int(len(y_true))
    pos = int(np.sum(y_true == 1))
    neg = n - pos
    probs = np.clip(scores_0_100 / 100.0, 0.0, 1.0)

    if n == 0:
        return {"n_total": 0, "positives": 0, "negatives": 0, "base_rate_with_denom": "0/0 (N/A)"}

    base_rate = pos / n
    ci_base = wilson_ci_95(pos, n)

    if 0 < pos < n:
        ranks = rankdata(scores_0_100)
        roc_auc = round(float((np.sum(ranks[y_true == 1]) - pos * (pos + 1) / 2.0) / (pos * neg)), 4)
        order = np.argsort(-scores_0_100, kind="mergesort")
        y_ord = y_true[order]
        cum_tp = np.cumsum(y_ord == 1)
        pr_auc = round(float(np.sum((cum_tp / np.arange(1, n + 1))[y_ord == 1]) / pos), 4)
    else:
        roc_auc = None
        pr_auc = None
        order = np.argsort(-scores_0_100, kind="mergesort")
        y_ord = y_true[order]

    def p_at_k(k: int):
        kk = min(k, n)
        hits = int(np.sum(y_ord[:kk] == 1))
        val = round(hits / kk, 4) if kk > 0 else None
        return val, fmt_ratio(hits, kk), wilson_ci_95(hits, kk)

    p5_v, p5_str, _ = p_at_k(5)
    p10_v, p10_str, p10_ci = p_at_k(10)
    p20_v, p20_str, p20_ci = p_at_k(20)

    pred_pos = scores_0_100 >= positive_threshold_0_100
    tp = int(np.sum((pred_pos == 1) & (y_true == 1)))
    fp = int(np.sum((pred_pos == 1) & (y_true == 0)))
    fn = int(np.sum((pred_pos == 0) & (y_true == 1)))

    rec_v = round(tp / pos, 4) if pos > 0 else None
    prec_bin = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1_v = round(2 * prec_bin * (tp / pos) / (prec_bin + (tp / pos)), 4) if (pos > 0 and (prec_bin + tp / pos) > 0) else 0.0

    brier = round(float(np.mean((probs - y_true) ** 2)), 4)
    # 5-bin Expected Calibration Error (ECE)
    bins = np.linspace(0.0, 1.0, 6)
    ece = 0.0
    for bi in range(5):
        mask = (probs >= bins[bi]) & (probs <= bins[bi + 1] if bi == 4 else probs < bins[bi + 1])
        if np.any(mask):
            ece += (np.sum(mask) / n) * abs(float(np.mean(probs[mask])) - float(np.mean(y_true[mask])))
    ece = round(float(ece), 4)

    # Post-cost execution economics on Top-20 (or selected `pred_pos` if >=5, always reporting exact denominator!)
    k_econ = min(20, n)
    top_idx = order[:k_econ]
    valid_rets = np.array([r for r in net_returns_pct[top_idx] if r is not None and not np.isnan(r)], dtype=float)
    valid_dds = np.array([d for d in max_drawdowns_pct[top_idx] if d is not None and not np.isnan(d)], dtype=float)

    n_econ = len(valid_rets)
    if n_econ > 0:
        wins_net = int(np.sum(valid_rets > 0))
        win_rate_net = wins_net / n_econ
        avg_win = float(np.mean(valid_rets[valid_rets > 0])) if wins_net > 0 else 0.0
        avg_loss = float(np.mean(np.abs(valid_rets[valid_rets <= 0]))) if (n_econ - wins_net) > 0 else 0.0
        expectancy_pct = round(win_rate_net * avg_win - (1.0 - win_rate_net) * avg_loss, 3)
        mean_net = round(float(np.mean(valid_rets)), 3)
        med_net = round(float(np.median(valid_rets)), 3)
        win_str = fmt_ratio(wins_net, n_econ)
    else:
        expectancy_pct = None
        mean_net = None
        med_net = None
        win_str = "0/0 (N/A)"

    max_dd = round(float(np.min(valid_dds)), 2) if len(valid_dds) > 0 else None

    return {
        "n_total": n,
        "positives": pos,
        "negatives": neg,
        "base_rate": round(base_rate, 4),
        "base_rate_with_denom": fmt_ratio(pos, n),
        "base_rate_wilson_95ci": list(ci_base),
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "precision_at_5": p5_str,
        "precision_at_10": p10_str,
        "precision_at_10_ci95": list(p10_ci),
        "precision_at_20": p20_str,
        "precision_at_20_ci95": list(p20_ci),
        "lift_at_10": round(p10_v / base_rate, 3) if (p10_v is not None and base_rate > 0) else None,
        "lift_at_20": round(p20_v / base_rate, 3) if (p20_v is not None and base_rate > 0) else None,
        "recall_at_threshold": fmt_ratio(tp, pos),
        "f1_score": f1_v,
        "brier_score": brier,
        "calibration_ece": ece,
        "top20_exact_exec_denom": f"{n_econ}/{k_econ}",
        "top20_win_rate_net": win_str,
        "top20_mean_net_return_pct": mean_net,
        "top20_median_net_return_pct": med_net,
        "top20_expectancy_pct": expectancy_pct,
        "top20_worst_drawdown_pct": max_dd,
        "_p10_num": p10_v,
        "_p20_num": p20_v,
    }


def run_historical_backtest_and_hypotheses_v2_2() -> dict:
    ds = json.loads((V2_ROOT / "cache" / "raw" / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    tokens = sorted(ds["tokens"], key=lambda x: (int(x.get("created_timestamp") or 0), x["mint"]))
    sol_kl = json.loads((V2_ROOT / "cache" / "raw" / "sol_1h_v2.json").read_text(encoding="utf-8"))
    rpc_full = json.loads((V2_1_ROOT / "cache" / "wallets_v2_1" / "deep_wallets_rpc_v2_1.json").read_text(encoding="utf-8"))

    spl_by_mint = defaultdict(list)
    for w_info in rpc_full.get("wallets", {}).values():
        for tf in w_info.get("spl_transfers", []):
            if tf.get("mint"):
                spl_by_mint[tf["mint"]].append(tf)

    temporal = TemporalIntegrityLedger()
    wi_engine = WalletIntelligenceEngineV22(rpc_full.get("wallets", {}), rpc_full.get("funder_types", {}))
    regime = CausalMarketRegimeTracker()
    regime.ingest_sol_klines_1h(sol_kl)
    fe = SharedFeatureEngineV22(temporal, wi_engine, regime)

    candles_dir = V2_ROOT / "cache" / "candles"
    trades_dir = V2_ROOT / "cache" / "trades"

    token_rows = []
    exact_sizing_rows = []
    estimated_sizing_rows = []

    for coin in tokens:
        mint = coin["mint"]
        cts = int(coin["created_timestamp"])
        cutoff_ms = cts + 180_000  # Fixed 3-minute pre-breakout observation cutoff

        c_obj = json.loads((candles_dir / f"{mint}.json").read_text(encoding="utf-8"))
        t_obj = json.loads((trades_dir / f"{mint}.json").read_text(encoding="utf-8"))
        trades = t_obj.get("trades") or []
        c1m = c_obj.get("candles_1m") or []
        is_complete = not bool(t_obj.get("early_30m_pagination_truncated", False))
        acq_hist_ms = int(c_obj.get("collection_timestamp_ms") or (cutoff_ms + 86_400_000))

        snap = fe.compute_features(
            coin=coin,
            trades=trades,
            candles_1m=c1m,
            decision_cutoff_ts_ms=cutoff_ms,
            acquired_at_ms=acq_hist_ms,
            mode="training",
            source_id="pumpfun_v3_historical_cache",
            source_health_status="HEALTHY",
            is_tape_complete=is_complete,
            spl_transfers=spl_by_mint.get(mint, []),
            has_historical_availability_proof=False,
        )
        conf = score_multi_signal_confluence(snap)
        outcomes = compute_post_signal_outcomes_and_exit_state(
            coin=coin,
            trades=trades,
            candles_obj=c_obj,
            cutoff_ts_ms=cutoff_ms,
            entry_state=snap["amm_state"],
            is_tape_complete=is_complete,
        )

        # Register ecosystem activity & strictly gated +4h wallet/cluster outcomes (`cutoff_ms + 4h`)
        vis_pre = deduplicate_and_order_swaps(trades, cutoff_ts_ms=cutoff_ms)
        regime.register_ecosystem_activity(cts, mint, snap["narrative"]["motif_category"], vis_pre, cutoff_ms)
        if outcomes["status_4h"] == "COMPLETE" and isinstance(outcomes["hit_2x_4h"], int):
            fifo_4h = snap["_fifo_internal"]
            wi_engine.register_completed_token_outcomes(
                mint=mint,
                created_ts_ms=cts,
                signal_ts_ms=cutoff_ms,
                outcome_known_at_ms=cutoff_ms + INTERVAL_MS["4h"],
                hit_2x_4h=int(outcomes["hit_2x_4h"]),
                pre_signal_obs=snap["_wi_obs_internal"],
                fifo_result=fifo_4h,
            )

        for s_sol in POSITION_SIZES_SOL:
            ex_q = outcomes["exec_by_size"].get(s_sol, {})
            est_q = outcomes["estimated_exec_by_size"].get(s_sol, {})
            if ex_q.get("usable_in_exact_backtest"):
                exact_sizing_rows.append({"mint": mint, "symbol": snap["token_symbol"], **ex_q})
            elif est_q.get("status") == "ROUND_TRIP_OK":
                estimated_sizing_rows.append({"mint": mint, "symbol": snap["token_symbol"], **est_q})

        ex_025_exact = outcomes["exec_by_size"].get(0.25, {})
        net_025 = ex_025_exact.get("net_return_after_fees_pct") if ex_025_exact.get("usable_in_exact_backtest") else np.nan

        cs = conf["component_scores"]
        hd = conf["hypothesis_details"]
        token_rows.append({
            "mint": mint,
            "symbol": snap["token_symbol"],
            "created_ts_ms": cts,
            "decision_cutoff_ts_ms": cutoff_ms,
            "availability_status": snap["envelope"]["availability_status"],
            "market_state": snap["amm_state"]["market_state"],
            "reserve_completeness": snap["amm_state"]["reserve_completeness"],
            "usable_in_exact_backtest": int(bool(snap["amm_state"]["usable_in_exact_backtest"])),
            "exit_reserve_completeness": outcomes.get("exit_reserve_completeness", "UNKNOWN"),
            "execution_confidence": conf["execution_confidence"],
            "liquidity_sol": snap["liquidity_sol"],
            "sol_trend_regime": snap["market_regime"]["sol_trend_regime"],
            "sol_volatility_regime": snap["market_regime"]["sol_volatility_regime"],
            "narrative_motif": snap["narrative"]["motif_category"],
            "narrative_potential_score": snap["narrative"]["narrative_potential_score"],
            "historical_social_activity": snap["narrative"]["historical_social_activity"],
            "h1_score": cs["buyer_acceleration"],
            "h1_triggered": int(hd["H1_BUYER_ACCELERATION"]["triggered"]),
            "h2_score": cs["wallet_cluster_accumulation"],
            "h2_triggered": int(hd["H2_REPEATED_WALLET_GROUPS"]["triggered"]),
            "h3_score": cs["smart_money_accumulation"],
            "h3_triggered": int(hd["H3_SMART_MONEY_ACCUMULATION"]["triggered"]),
            "h4_score": cs["supply_safety"],
            "h4_triggered": int(hd["H4_SUPPLY_SAFETY"]["triggered"]),
            "h5_score": cs["buy_pressure_absorption"],
            "h5_triggered": int(hd["H5_BUY_PRESSURE_ABSORPTION"]["triggered"]),
            "total_confluence_score": conf["total_score"],
            "confluence_class": conf["confluence_class"],
            "data_quality_score": conf["data_quality_score"],
            "buy_volume_sol": snap["h5_metrics"]["buy_volume_sol"],
            "unique_buyers_count": snap["h1_metrics"]["unique_buyers_count"],
            "independent_buyers_estimate": snap["h1_metrics"]["independent_buyers_estimate"],
            "status_1h": outcomes["status_1h"],
            "hit_2x_1h": outcomes["hit_2x_1h"],
            "status_4h": outcomes["status_4h"],
            "hit_2x_4h": outcomes["hit_2x_4h"],
            "hit_3x_4h": outcomes["hit_3x_4h"],
            "status_24h": outcomes["status_24h"],
            "hit_5x_24h": outcomes["hit_5x_24h"],
            "max_multiple_4h": outcomes["max_multiple_4h"],
            "max_drawdown_4h_pct": outcomes["max_drawdown_4h_pct"],
            "time_to_ath_4h_sec": outcomes["time_to_ath_4h_sec"],
            "exact_net_return_0_25_sol_pct": net_025,
        })

    df_bt = pd.DataFrame(token_rows)
    df_bt.to_csv(BACKTESTING_DIR / "backtest_tokens_v2_2.csv", index=False)
    pd.DataFrame(exact_sizing_rows).to_csv(BACKTESTING_DIR / "exact_amm_sizing_v2_2.csv", index=False)
    pd.DataFrame(estimated_sizing_rows).to_csv(BACKTESTING_DIR / "estimated_incomplete_amm_only_v2_2.csv", index=False)

    # Export Wallet Intelligence 2.0 tables (`profiles`, `edges`, `cluster_track_records`)
    pd.DataFrame(wi_engine.export_wallet_profiles_table()).to_csv(DATA_DIR / "wallet_profiles_v2_2.csv", index=False)
    pd.DataFrame(list(wi_engine.edges.values())).to_csv(DATA_DIR / "wallet_graph_edges_v2_2.csv", index=False)
    pd.DataFrame(wi_engine.export_cluster_track_records()).to_csv(DATA_DIR / "wallet_cluster_track_record_v2_2.csv", index=False)

    # Evaluate H1–H5 individually AND combined on complete 4h rows (`hit_2x_4h`)
    comp = df_bt[df_bt["status_4h"] == "COMPLETE"].copy()
    y_all = comp["hit_2x_4h"].astype(int).to_numpy()
    nets_all = pd.to_numeric(comp["exact_net_return_0_25_sol_pct"], errors="coerce").to_numpy()
    dds_all = pd.to_numeric(comp["max_drawdown_4h_pct"], errors="coerce").to_numpy()

    hyp_results = []
    for h_code, sc_col, tr_col in [
        ("H1_ACCELERATION_INDEPENDENT_BUYERS", "h1_score", "h1_triggered"),
        ("H2_REPEATED_WALLET_GROUP_ACCUM", "h2_score", "h2_triggered"),
        ("H3_SMART_MONEY_ACCUMULATION", "h3_score", "h3_triggered"),
        ("H4_SUPPLY_SAFETY_LOW_OVERHANG", "h4_score", "h4_triggered"),
        ("H5_BUY_PRESSURE_ABSORPTION", "h5_score", "h5_triggered"),
        ("COMBINED_MULTI_SIGNAL_CONFLUENCE", "total_confluence_score", None),
    ]:
        raw_sc = comp[sc_col].astype(float).to_numpy()
        scaled = raw_sc * 5.0 if sc_col != "total_confluence_score" else raw_sc
        thresh = 50.0 if sc_col != "total_confluence_score" else 36.0
        m = compute_full_evaluation_metrics(y_all, scaled, nets_all, dds_all, positive_threshold_0_100=thresh)
        if tr_col:
            trig_sub = comp[comp[tr_col] == 1]
            t_pos = int(trig_sub["hit_2x_4h"].astype(int).sum()) if len(trig_sub) else 0
            trig_rate_str = fmt_ratio(t_pos, len(trig_sub))
            trig_ci = wilson_ci_95(t_pos, len(trig_sub))
        else:
            med_hi = comp[comp["confluence_class"].isin(["MEDIUM_CONFLUENCE", "HIGH_CONFLUENCE"])]
            t_pos = int(med_hi["hit_2x_4h"].astype(int).sum()) if len(med_hi) else 0
            trig_rate_str = fmt_ratio(t_pos, len(med_hi))
            trig_ci = wilson_ci_95(t_pos, len(med_hi))
        hyp_results.append({"hypothesis_or_model": h_code, "triggered_hit_rate_2x_4h": trig_rate_str, "triggered_ci95": list(trig_ci), **m})

    pd.DataFrame(hyp_results).to_csv(BACKTESTING_DIR / "hypothesis_results_v2_2.csv", index=False)

    # Regime breakdown (Section 11.2: BULL / BEAR / SIDEWAYS & HIGH_VOL / LOW_VOL)
    regime_rows = []
    for col_reg in ("sol_trend_regime", "sol_volatility_regime"):
        for val_reg, grp in comp.groupby(col_reg):
            yy = grp["hit_2x_4h"].astype(int).to_numpy()
            ss = grp["total_confluence_score"].astype(float).to_numpy()
            nn = pd.to_numeric(grp["exact_net_return_0_25_sol_pct"], errors="coerce").to_numpy()
            dd = pd.to_numeric(grp["max_drawdown_4h_pct"], errors="coerce").to_numpy()
            rm = compute_full_evaluation_metrics(yy, ss, nn, dd)
            regime_rows.append({"regime_dimension": col_reg, "regime_value": val_reg, **rm})
    pd.DataFrame(regime_rows).to_csv(BACKTESTING_DIR / "regime_breakdown_v2_2.csv", index=False)

    return {
        "n_cohort": len(df_bt),
        "exact_backtest_usable_count": int(df_bt["usable_in_exact_backtest"].sum()),
        "incomplete_excluded_count": int((df_bt["usable_in_exact_backtest"] == 0).sum()),
        "hypothesis_results": hyp_results,
        "regime_breakdown": regime_rows,
        "wi_engine": wi_engine,
        "regime_tracker": regime,
    }


if __name__ == "__main__":
    res = run_historical_backtest_and_hypotheses_v2_2()
    print(f"Backtest V2.2 complete: n={res['n_cohort']} | exact_usable={res['exact_backtest_usable_count']} | incomplete_excluded={res['incomplete_excluded_count']}")
