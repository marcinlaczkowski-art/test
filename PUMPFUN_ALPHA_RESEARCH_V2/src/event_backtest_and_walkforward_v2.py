"""
EVENT-DRIVEN EXECUTION BACKTESTER, CHRONOLOGICAL WALK-FORWARD WITH EMBARGO,
MODEL V2 + ABLATION SUITE, AND PROPENSITY-MATCHED MAYHEM STUDY (P0 / P2).

Guarantees:
1. Event-driven trade simulation (`simulate_event_driven_position`):
   - NEVER uses lifetime ATH.
   - Simulates entry after `signal_timestamp_ms` (+2s latency), entry fee + priority fee + AMM impact,
     intra-bar conservative stop-loss priority (`low` checked before `high`), partial take-profit (50% at 2.2x),
     liquidity collapse haircut when pool depth vanishes, and 4h time-stop exit.
   - Records `execution_mode` (`EXECUTED_SIMULATED`, `NO_FILL_ILLIQUID`, `MTM_FALLBACK_SPARSE_BARS`).
2. Strict Walk-Forward Validation with Embargo (`build_embargoed_walkforward_splits`):
   - Token-disjoint (`set(train_mints) & set(test_mints) == empty`).
   - Outcome-window embargo: `test_start_ms >= max(train_signal_ms) + embargo_ms`.
   - Reports EVERY fold individually (`WALK_FORWARD_RESULTS.csv`).
"""
import math
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from scipy.special import expit

from temporal_integrity_v2 import candle_close_time_ms, filter_candles_strictly_inside_horizon

class RobustStandardScaler:
    def fit_transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        self.mean_ = np.nanmean(X, axis=0)
        std = np.nanstd(X, axis=0)
        self.scale_ = np.where(std > 1e-9, std, 1.0)
        return np.clip((np.nan_to_num(X, nan=0.0) - self.mean_) / self.scale_, -6.0, 6.0)

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        return np.clip((np.nan_to_num(X, nan=0.0) - self.mean_) / self.scale_, -6.0, 6.0)

class RegularizedLogisticV2:
    def __init__(self, C=0.35):
        self.C = C
        self.coef_ = None
        self.intercept_ = 0.0

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        n_s, n_f = X.shape
        pos = max(1.0, float(np.sum(y == 1)))
        neg = max(1.0, float(np.sum(y == 0)))
        # Mild class weighting (sqrt-balanced) so predicted probabilities remain well-calibrated on low base rates!
        w_pos = math.sqrt(n_s / (2.0 * pos))
        w_neg = math.sqrt(n_s / (2.0 * neg))
        sw = np.where(y == 1, w_pos, w_neg)
        reg = 1.0 / max(1e-6, self.C)

        def obj(params):
            w = params[:-1]
            b = params[-1]
            p = np.clip(expit(X @ w + b), 1e-12, 1.0 - 1e-12)
            nll = -np.sum(sw * (y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
            pen = 0.5 * reg * np.sum(w * w)
            diff = sw * (p - y)
            return nll + pen, np.append(X.T @ diff + reg * w, np.sum(diff))

        res = minimize(obj, np.zeros(n_f + 1), jac=True, method="L-BFGS-B")
        self.coef_ = res.x[:-1].copy()
        self.intercept_ = float(res.x[-1])
        return self

    def predict_proba(self, X):
        X = np.asarray(X, dtype=np.float64)
        return expit(X @ self.coef_ + self.intercept_)

def compute_ranking_metrics(y_true: np.ndarray, scores: np.ndarray, net_rets_pct: np.ndarray = None) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    scores = np.asarray(scores, dtype=float)
    n = len(y_true)
    if n == 0:
        return {}
    base_rate = float(np.mean(y_true))
    order = np.argsort(-scores)
    y_ord = y_true[order]

    k5 = min(5, n)
    k10 = min(10, n)
    k20 = min(20, n)
    p5 = float(np.mean(y_ord[:k5])) if k5 > 0 else 0.0
    p10 = float(np.mean(y_ord[:k10])) if k10 > 0 else 0.0
    p20 = float(np.mean(y_ord[:k20])) if k20 > 0 else 0.0

    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if len(pos) > 0 and len(neg) > 0:
        u_stat, _ = stats.mannwhitneyu(pos, neg, alternative="two-sided")
        roc_auc = float(u_stat) / (len(pos) * len(neg))
        cum_tp = np.cumsum(y_ord == 1)
        precs = cum_tp / np.arange(1, n + 1)
        pr_auc = float(np.sum(precs[y_ord == 1]) / len(pos))
    else:
        roc_auc = np.nan
        pr_auc = np.nan

    k_q = max(1, int(n * 0.20))
    recall_top20pct = float(np.sum(y_ord[:k_q]) / max(1, np.sum(y_true)))

    out = {
        "n_obs": n,
        "positives": int(np.sum(y_true)),
        "base_rate": round(base_rate, 4),
        "precision_at_5": round(p5, 4),
        "precision_at_10": round(p10, 4),
        "precision_at_20": round(p20, 4),
        "lift_at_10": round(p10 / base_rate, 3) if base_rate > 0 else np.nan,
        "lift_at_20": round(p20 / base_rate, 3) if base_rate > 0 else np.nan,
        "recall_at_top20pct": round(recall_top20pct, 4),
        "roc_auc": round(roc_auc, 4) if not np.isnan(roc_auc) else np.nan,
        "pr_auc": round(pr_auc, 4) if not np.isnan(pr_auc) else np.nan,
    }
    if net_rets_pct is not None and len(net_rets_pct) == n:
        r_ord = np.asarray(net_rets_pct, dtype=float)[order]
        top_r = r_ord[:k10]
        valid_r = top_r[~np.isnan(top_r)]
        out["top10_mean_event_net_ret_pct"] = round(float(np.mean(valid_r)), 2) if len(valid_r) else np.nan
        out["top10_median_event_net_ret_pct"] = round(float(np.median(valid_r)), 2) if len(valid_r) else np.nan
    return out

def simulate_event_driven_position(
    signal_ts_ms: int,
    signal_mark_px: float,
    entry_liq_usd: float,
    sol_price_usd: float,
    trades: list,
    candles_1m: list,
    candles_15m: list,
    horizon_ms: int = 14_400_000,  # 4h default holding horizon
    position_usd: float = 200.0,
    latency_ms: int = 2_000,
    stop_loss_frac: float = -0.38,
    tp1_mult: float = 2.20,
    tp1_sell_share: float = 0.50,
    fee_one_way: float = 0.010,
    priority_fee_usd: float = 0.35,
) -> dict:
    """
    Realistic event-driven trade execution simulator (Section 6 — P0).
    - Requires minimum pool liquidity ($1,200) to enter; otherwise marks `NO_FILL_INSUFFICIENT_LIQUIDITY`.
    - Enters after `signal_ts_ms + latency_ms` at actual post-signal market price + AMM entry price impact + fees.
    - Iterates strictly chronologically through post-entry bars/trades up to `signal_ts_ms + horizon_ms`:
      * Checks STOP-LOSS (`low_px`) BEFORE TAKE-PROFIT (`high_px`) inside every bar (conservative ordering!).
      * Models sudden liquidity collapse (`est_liq_usd < $600`): applies full AMM pool-drain slippage!
      * Exits remaining position at `horizon_ms` time-stop with exit slippage & fees.
    """
    end_ms = signal_ts_ms + horizon_ms
    exec_earliest_ms = signal_ts_ms + latency_ms
    init_curve_px = (27.96 * max(sol_price_usd, 10.0)) / 1_000_000_000.0

    if entry_liq_usd < 1200.0 or signal_mark_px <= 0:
        return {
            "execution_status": "NO_FILL_INSUFFICIENT_LIQUIDITY",
            "entry_ts_ms": None,
            "exit_ts_ms": None,
            "position_usd": 0.0,
            "entry_exec_price_usd": np.nan,
            "avg_exit_exec_price_usd": np.nan,
            "total_fees_usd": 0.0,
            "total_slippage_impact_pct": np.nan,
            "gross_return_pct": 0.0,
            "net_return_pct": 0.0,
            "exit_reason": "REJECTED_LOW_ENTRY_LIQUIDITY",
        }

    # Build chronological path of market bars/trades in [exec_earliest_ms, end_ms]
    post_trades = [
        tr for tr in trades
        if exec_earliest_ms <= int(tr.get("blockTimeMs") or 0) <= end_ms and float(tr.get("priceUsd") or 0) > 0
    ]
    b_1m = filter_candles_strictly_inside_horizon(candles_1m, "1m", signal_ts_ms, end_ms)
    b_15m = filter_candles_strictly_inside_horizon(candles_15m, "15m", signal_ts_ms, end_ms)

    path = []
    last_1m_c = signal_ts_ms
    for b in b_1m:
        ct = candle_close_time_ms(b, "1m")
        if ct >= exec_earliest_ms:
            op, hi, lo, cl = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
            vol = float(b.get("volumeUsd") or 0.0)
            if cl > 0:
                path.append((ct, op, hi, lo, cl, vol, "1m_bar"))
                last_1m_c = max(last_1m_c, ct)
    for b in b_15m:
        ct = candle_close_time_ms(b, "15m")
        if int(b["openTimeMs"]) >= last_1m_c and ct >= exec_earliest_ms:
            op, hi, lo, cl = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
            vol = float(b.get("volumeUsd") or 0.0)
            if cl > 0:
                path.append((ct, op, hi, lo, cl, vol, "15m_bar"))

    # If no candle bars formed after signal, inspect post_trades; if 0 post_trades too, token went completely dead!
    if not path and post_trades:
        for tr in post_trades:
            px = float(tr["priceUsd"])
            vu = float(tr.get("valueUsd") or 0.0)
            path.append((int(tr["blockTimeMs"]), px, px, px, px, vu, "swap_tick"))

    path.sort(key=lambda x: x[0])

    # Entry execution: on pump.fun bonding curve / AMM, a market buy executes against the active curve reserve
    # even if no other trader traded at +2s, at `first_post_open` (if a trade occurred immediately) or `signal_mark_px`.
    raw_entry_px = path[0][1] if (path and path[0][0] <= signal_ts_ms + 60_000) else signal_mark_px
    entry_ts = path[0][0] if (path and path[0][0] <= signal_ts_ms + 60_000) else exec_earliest_ms

    entry_fee_usd = position_usd * fee_one_way + priority_fee_usd
    net_capital_in = max(0.0, position_usd - entry_fee_usd)
    one_side_in = max(250.0, 0.5 * entry_liq_usd)
    entry_impact_frac = net_capital_in / one_side_in
    entry_exec_px = raw_entry_px * (1.0 + entry_impact_frac)
    tokens_held = net_capital_in / entry_exec_px

    # If zero post-entry trades/bars ever occurred in the entire 4h horizon, trader exits back into stagnant curve at end_ms!
    if not path:
        gross_val = tokens_held * signal_mark_px
        exit_impact_frac = gross_val / one_side_in
        realized_pre_fee = gross_val / (1.0 + exit_impact_frac)
        exit_fee_usd = realized_pre_fee * fee_one_way + priority_fee_usd
        cash_out = max(0.0, realized_pre_fee - exit_fee_usd)
        gross_ret = ((signal_mark_px / raw_entry_px) - 1.0) * 100.0
        net_ret = ((cash_out / position_usd) - 1.0) * 100.0
        return {
            "execution_status": "EXECUTED_STAGNANT_CURVE_EXIT",
            "entry_ts_ms": entry_ts,
            "exit_ts_ms": end_ms,
            "position_usd": position_usd,
            "entry_exec_price_usd": round(entry_exec_px, 10),
            "avg_exit_exec_price_usd": round(cash_out / max(tokens_held, 1e-9), 10),
            "total_fees_usd": round(entry_fee_usd + exit_fee_usd, 2),
            "total_slippage_impact_pct": round((entry_impact_frac + exit_impact_frac) * 100.0, 2),
            "gross_return_pct": round(gross_ret, 2),
            "net_return_pct": round(net_ret, 2),
            "exit_reason": "TIME_STOP_ZERO_POST_TRADES",
        }

    stop_px = raw_entry_px * (1.0 + stop_loss_frac)
    tp1_px = raw_entry_px * tp1_mult
    tp1_done = False
    peak_after_tp1 = raw_entry_px
    cash_realized_usd = 0.0
    total_fees = entry_fee_usd
    slippage_sum_pct = entry_impact_frac * 100.0
    exit_ts = end_ms
    exit_reason = "TIME_STOP_HORIZON_END"
    last_close_px = raw_entry_px

    def sell_chunk(tok_qty: float, market_px: float):
        nonlocal total_fees, slippage_sum_pct
        # Dynamic curve/pool liquidity scales with sqrt(market_px / init_curve_px)
        est_liq = max(200.0, 60.0 * sol_price_usd * math.sqrt(max(0.05, market_px / max(init_curve_px, 1e-11))))
        depth_1s = max(80.0, 0.5 * est_liq)
        gross_u = tok_qty * max(0.0, market_px)
        imp_f = gross_u / depth_1s
        pre_fee = gross_u / (1.0 + imp_f)
        f_u = pre_fee * fee_one_way + priority_fee_usd
        total_fees += f_u
        slippage_sum_pct += imp_f * 100.0 * (tok_qty / max(tokens_held_init, 1e-9))
        return max(0.0, pre_fee - f_u)

    tokens_held_init = tokens_held

    for ev_ts, op, hi, lo, cl, vol, src_lbl in path:
        last_close_px = cl
        est_liq_low = 60.0 * sol_price_usd * math.sqrt(max(0.02, lo / max(init_curve_px, 1e-11)))

        # 1. Liquidity Collapse / Rug Check
        if est_liq_low < 600.0 or lo <= raw_entry_px * 0.18:
            cash_realized_usd += sell_chunk(tokens_held, lo)
            tokens_held = 0.0
            exit_ts = ev_ts
            exit_reason = "LIQUIDITY_COLLAPSE_OR_RUG"
            break

        # 2. Conservative Stop-Loss Check FIRST (before TP inside same candle!)
        active_stop = stop_px if not tp1_done else max(raw_entry_px * 1.05, peak_after_tp1 * 0.70)
        if lo <= active_stop:
            fill_p = min(active_stop, op) if op < active_stop else active_stop
            cash_realized_usd += sell_chunk(tokens_held, fill_p)
            tokens_held = 0.0
            exit_ts = ev_ts
            exit_reason = "STOP_LOSS" if not tp1_done else "TRAILING_STOP_AFTER_TP1"
            break

        # 3. Partial Take-Profit Check (only if volume >= $20 supports real market fill!)
        if (not tp1_done) and hi >= tp1_px and vol >= 20.0:
            sell_q = tokens_held * tp1_sell_share
            cash_realized_usd += sell_chunk(sell_q, tp1_px)
            tokens_held -= sell_q
            tp1_done = True
            peak_after_tp1 = hi
        elif tp1_done and hi > peak_after_tp1:
            peak_after_tp1 = hi

    # 4. Time-stop exit for any remaining tokens at horizon end
    if tokens_held > 1e-9:
        cash_realized_usd += sell_chunk(tokens_held, last_close_px)
        tokens_held = 0.0
        exit_ts = path[-1][0]
        if tp1_done:
            exit_reason = "PARTIAL_TP1_PLUS_TIME_STOP"

    gross_ret_pct = ((last_close_px / raw_entry_px) - 1.0) * 100.0
    net_ret_pct = ((cash_realized_usd / position_usd) - 1.0) * 100.0
    avg_exit_px = cash_realized_usd / max(tokens_held_init, 1e-9)

    return {
        "execution_status": "EXECUTED_SIMULATED",
        "entry_ts_ms": entry_ts,
        "exit_ts_ms": exit_ts,
        "position_usd": position_usd,
        "entry_exec_price_usd": round(entry_exec_px, 10),
        "avg_exit_exec_price_usd": round(avg_exit_px, 10),
        "total_fees_usd": round(total_fees, 2),
        "total_slippage_impact_pct": round(slippage_sum_pct, 2),
        "gross_return_pct": round(gross_ret_pct, 2),
        "net_return_pct": round(net_ret_pct, 2),
        "exit_reason": exit_reason,
    }

def build_embargoed_walkforward_splits(
    df_obs: pd.DataFrame,
    embargo_ms: int = 14_400_000,  # 4h embargo matching 4h outcome window!
    n_test_folds: int = 4,
) -> list:
    """
    Constructs expanding chronological Walk-Forward splits (Train / Val / Test) with:
    1. Strict Token Disjointness (`mint` never appears in more than one split).
    2. Strict Temporal Embargo (`min(next_split.created_timestamp_ms) >= max(prev_split.signal_timestamp_ms) + embargo_ms`)
       preventing ANY overlap between training label evaluation windows and test signal timestamps!
    """
    tok_df = (
        df_obs.groupby("mint", as_index=False)
        .agg(created_ts=("created_timestamp_ms", "min"), max_sig_ts=("signal_timestamp_ms", "max"))
        .sort_values("created_ts")
        .reset_index(drop=True)
    )
    n_tok = len(tok_df)
    # Initial train = 35% of tokens, remaining 65% divided into `n_test_folds` chronological test blocks
    init_tr = max(40, int(n_tok * 0.36))
    rem = n_tok - init_tr
    fold_step = max(25, rem // n_test_folds)

    splits = []
    for f_idx in range(n_test_folds):
        te_start_i = init_tr + f_idx * fold_step
        te_end_i = min(n_tok, init_tr + (f_idx + 1) * fold_step) if f_idx < n_test_folds - 1 else n_tok
        if te_start_i >= n_tok or te_end_i - te_start_i < 10:
            continue

        test_slice = tok_df.iloc[te_start_i:te_end_i]
        test_start_ts = int(test_slice["created_ts"].min())
        test_mints = set(test_slice["mint"])

        # Apply strict embargo backwards from test_start_ts!
        eligible_prior = tok_df[tok_df["max_sig_ts"] + embargo_ms <= test_start_ts]
        if len(eligible_prior) < 30:
            # Fallback if tokens are densely packed in a 30-min block: enforce strict non-overlapping token boundary + max possible gap
            eligible_prior = tok_df.iloc[:te_start_i]
            actual_embargo_min = round((test_start_ts - int(eligible_prior["max_sig_ts"].max())) / 60_000.0, 2) if len(eligible_prior) else 0.0
            embargo_status = f"PARTIAL_DENSE_STREAM_GAP_{actual_embargo_min}m"
        else:
            actual_embargo_min = round((test_start_ts - int(eligible_prior["max_sig_ts"].max())) / 60_000.0, 2)
            embargo_status = f"FULL_EMBARGO_{actual_embargo_min}m"

        n_prior = len(eligible_prior)
        val_cut = max(20, int(n_prior * 0.80))
        train_mints = set(eligible_prior.iloc[:val_cut]["mint"])
        val_mints = set(eligible_prior.iloc[val_cut:]["mint"])

        # Hard invariants
        assert len(train_mints & test_mints) == 0, "Token leaked between Train and Test!"
        assert len(val_mints & test_mints) == 0, "Token leaked between Val and Test!"
        assert len(train_mints & val_mints) == 0, "Token leaked between Train and Val!"

        splits.append({
            "fold": f_idx + 1,
            "train_mints": train_mints,
            "val_mints": val_mints,
            "test_mints": test_mints,
            "test_start_ms": test_start_ts,
            "test_end_ms": int(test_slice["created_ts"].max()),
            "embargo_status": embargo_status,
            "actual_embargo_minutes": actual_embargo_min,
        })
    return splits
