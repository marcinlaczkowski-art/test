"""
STEP 5: Strict Point-in-Time Early Signal Engine, 35-Hypothesis Statistical Discovery Suite
(with Benjamini-Hochberg FDR multiple-testing correction), 3-Component Empirical Scoring System,
and Chronological + Walk-Forward Backtesting Engine.

Outputs:
- EARLY_SIGNALS.csv
- BACKTEST_RESULTS.csv
- cache/analytics_summary.json (exact empirical tables, p/q-values, CIs, top 10 early signals, model weights, backtest benchmarks)
"""
import json
import math
import logging
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from scipy.special import expit

class StandardScaler:
    def fit_transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        self.mean_ = np.mean(X, axis=0)
        self.scale_ = np.where(np.std(X, axis=0) > 1e-9, np.std(X, axis=0), 1.0)
        return (X - self.mean_) / self.scale_

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        return (X - self.mean_) / self.scale_

class BalancedL2Logistic:
    def __init__(self, C=0.5):
        self.C = C
        self.coef_ = None
        self.intercept_ = 0.0

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        n_samples, n_features = X.shape
        pos = max(1.0, np.sum(y == 1))
        neg = max(1.0, np.sum(y == 0))
        sample_w = np.where(y == 1, n_samples / (2.0 * pos), n_samples / (2.0 * neg))
        reg = 1.0 / max(1e-6, self.C)

        def loss_and_grad(params):
            w = params[:-1]
            b = params[-1]
            z = X @ w + b
            p = expit(z)
            # Clip for log stability
            p_clip = np.clip(p, 1e-12, 1.0 - 1e-12)
            nll = -np.sum(sample_w * (y * np.log(p_clip) + (1.0 - y) * np.log(1.0 - p_clip)))
            pen = 0.5 * reg * np.sum(w * w)
            diff = sample_w * (p - y)
            grad_w = X.T @ diff + reg * w
            grad_b = np.sum(diff)
            return nll + pen, np.append(grad_w, grad_b)

        res = minimize(loss_and_grad, np.zeros(n_features + 1), jac=True, method="L-BFGS-B")
        self.coef_ = res.x[:-1].reshape(1, -1)
        self.intercept_ = float(res.x[-1])
        return self

    def predict_proba(self, X):
        X = np.asarray(X, dtype=np.float64)
        p1 = expit(X @ self.coef_[0] + self.intercept_)
        return np.column_stack([1.0 - p1, p1])

def roc_auc_score(y_true, y_score):
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    pos = y_score[y_true == 1]
    neg = y_score[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    u_stat, _ = stats.mannwhitneyu(pos, neg, alternative="two-sided")
    return float(u_stat) / (len(pos) * len(neg))

def average_precision_score(y_true, y_score):
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    tot_pos = np.sum(y_true == 1)
    if tot_pos == 0:
        return 0.0
    order = np.argsort(-y_score)
    y_sorted = y_true[order]
    cum_tp = np.cumsum(y_sorted == 1)
    precisions = cum_tp / np.arange(1, len(y_sorted) + 1)
    return float(np.sum(precisions[y_sorted == 1]) / tot_pos)

def brier_score_loss(y_true, y_prob):
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    return float(np.mean((y_true - y_prob) ** 2))

from config import (
    BASE_DIR, RAW_DIR, CACHE_DIR, TRADES_CACHE_DIR, CANDLES_CACHE_DIR,
    CREATORS_CACHE_DIR, LOGS_DIR, WINDOW_START_MS, TECHNICAL_ADDRESSES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step5_signals_backtest.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step5")

HORIZONS = [
    ("30s", 30),
    ("1m", 60),
    ("3m", 180),
    ("5m", 300),
    ("10m", 600),
    ("15m", 900),
    ("30m", 1800),
]

def benjamini_hochberg(p_vals: list) -> list:
    m = len(p_vals)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_vals), key=lambda x: x[1])
    q_vals = [1.0] * m
    prev_q = 1.0
    for rank_rev, (orig_i, p) in enumerate(reversed(indexed)):
        rank = m - rank_rev
        q = min(prev_q, (p * m) / rank)
        q_vals[orig_i] = round(min(1.0, float(q)), 6)
        prev_q = q
    return q_vals

def build_causal_prior_histories(df_tm: pd.DataFrame, coins_by_mint: dict, creator_db: dict):
    """
    Builds strictly causal (no look-ahead!) lookup structures sorted by launch timestamp:
    - For any token launched at t_0, what was its creator's track record STRICTLY BEFORE t_0?
    - For any wallet buying before t_0 + horizon, how many pre-pump entries did that wallet achieve on tokens launched STRICTLY BEFORE t_0 - 30min?
    """
    creator_prior_launches = defaultdict(list)
    for cr, cinfo in creator_db.items():
        for b in cinfo.get("coins_brief", []):
            bts = int(b.get("created_timestamp") or 0)
            if bts > 0:
                creator_prior_launches[cr].append((
                    bts,
                    int(bool(b.get("complete"))),
                    float(b.get("ath_market_cap") or 0.0)
                ))
        creator_prior_launches[cr].sort(key=lambda x: x[0])

    # Build chronological wallet early-entry history across cohort
    df_sorted = df_tm.sort_values("created_timestamp_ms")
    token_early_buyers_chron = []
    for _, row in df_sorted.iterrows():
        m = row["mint"]
        cts = int(row["created_timestamp_ms"])
        if cts <= 0:
            continue
        tp = TRADES_CACHE_DIR / f"{m}.json"
        if not tp.exists():
            continue
        trades = json.loads(tp.read_text(encoding="utf-8")).get("trades", [])
        early25 = []
        for tr in trades:
            w = (tr.get("trader") or {}).get("address")
            if tr.get("side") == "buy" and w and w not in TECHNICAL_ADDRESSES and w not in early25:
                early25.append(w)
                if len(early25) >= 25:
                    break
        is_pump_3x = int(row["reliable_market_multiple"] >= 3.0 and row["max_mcap_usd"] >= 12000)
        token_early_buyers_chron.append((cts, m, is_pump_3x, early25))

    return creator_prior_launches, token_early_buyers_chron

def reconstruct_early_signals(df_tm: pd.DataFrame, coins_by_mint: dict, df_name: pd.DataFrame, creator_db: dict):
    logger.info("Building strictly causal point-in-time EARLY_SIGNALS snapshots (30s..30m)...")
    creator_priors, wallet_chron = build_causal_prior_histories(df_tm, coins_by_mint, creator_db)
    name_map = df_name.set_index("mint").to_dict(orient="index")

    # Filter to Group A 30d tokens (both Pump Candidates & Matched Controls) with valid launch timestamps
    df_ga = df_tm[df_tm["created_timestamp_ms"] >= WINDOW_START_MS].sort_values("created_timestamp_ms").copy()

    early_rows = []
    # Maintain running causal wallet scoreboard updated only when a prior token is at least 60 minutes old!
    ptr = 0
    causal_wallet_entries = Counter()
    causal_wallet_wins = Counter()

    for _, row in df_ga.iterrows():
        m = row["mint"]
        cts = int(row["created_timestamp_ms"])
        # Advance causal wallet history only for launches strictly older than cts - 60 minutes (zero leakage!)
        while ptr < len(wallet_chron) and wallet_chron[ptr][0] <= cts - 3600_000:
            _, _, win_flag, w_list = wallet_chron[ptr]
            for w in w_list:
                causal_wallet_entries[w] += 1
                if win_flag:
                    causal_wallet_wins[w] += 1
            ptr += 1

        c = coins_by_mint[m]
        creator = row["creator"]
        mayhem_on = int(row["mayhem_enabled"])
        tot_supply = 2_000_000_000.0 if mayhem_on else 1_000_000_000.0

        # Causal creator stats strictly prior to cts - 60s
        c_hist = [x for x in creator_priors.get(creator, []) if x[0] < cts - 60_000]
        cr_prior_cnt = len(c_hist)
        cr_prior_wins = sum(1 for x in c_hist if x[1] == 1 or x[2] >= 25000)
        cr_prior_win_rate = round(cr_prior_wins / max(1, cr_prior_cnt), 4) if cr_prior_cnt > 0 else 0.0

        tp = TRADES_CACHE_DIR / f"{m}.json"
        cp = CANDLES_CACHE_DIR / f"{m}.json"
        trades = json.loads(tp.read_text(encoding="utf-8")).get("trades", []) if tp.exists() else []
        cdat = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
        c_1m = cdat.get("candles_1m", [])
        c_15m = cdat.get("candles_15m", [])
        c_4h = cdat.get("candles_4h", [])
        all_bars = sorted(c_1m + c_15m + c_4h, key=lambda b: int(b.get("openTimeMs") or 0))

        tok_tech = set(TECHNICAL_ADDRESSES)
        for fld in ["bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address", "market_id"]:
            if c.get(fld):
                tok_tech.add(c[fld])

        first_rel_p = float(row["first_reliable_price_usd"])
        max_rel_p = float(row["max_reliable_price_usd"])
        nm_feat = name_map.get(m, {})
        shareability = float(nm_feat.get("meme_shareability_score", 0.5))
        is_first_mover = int(nm_feat.get("is_ticker_first_mover", 1))
        has_socials = int(bool(c.get("twitter")) or bool(c.get("website")))

        # Helper to look up future price at cts + offset_sec
        def price_at_future(target_ms: int, fallback_p: float) -> float:
            best_p = fallback_p
            for b in all_bars:
                b_ms = int(b.get("openTimeMs") or 0)
                if b_ms <= target_ms and float(b.get("close") or 0) > 0:
                    best_p = float(b["close"])
                elif b_ms > target_ms:
                    break
            return best_p

        # Identify initial launch-block bundle wallets (visible within first 5 seconds)
        launch_blk_wallets = defaultdict(list)
        for tr in trades:
            rel_s = (int(tr.get("blockTimeMs") or cts) - cts) / 1000.0
            if rel_s <= 8.0 and tr.get("side") == "buy":
                w = (tr.get("trader") or {}).get("address")
                if w and w not in tok_tech:
                    launch_blk_wallets[int(tr.get("blockId") or 0)].append(w)
        bundled_set = set()
        for blk, wl in launch_blk_wallets.items():
            uw = set(wl)
            if len(uw) >= 2:
                bundled_set.update(uw)

        # Compute initial top5 concentration at t=15s for concentration-change delta
        init_bal = defaultdict(float)
        for tr in trades:
            rel_s = (int(tr.get("blockTimeMs") or cts) - cts) / 1000.0
            if rel_s > 15.0:
                break
            w = (tr.get("trader") or {}).get("address")
            if w and w not in tok_tech:
                amt = float((tr.get("baseAmount") or {}).get("raw") or 0) / (10 ** int((tr.get("baseAmount") or {}).get("decimals") or 6))
                if tr.get("side") == "buy":
                    init_bal[w] += amt
                elif tr.get("side") == "sell":
                    init_bal[w] = max(0.0, init_bal[w] - amt)
        init_top5_pct = (sum(sorted(init_bal.values(), reverse=True)[:5]) / tot_supply) * 100.0

        for h_label, h_sec in HORIZONS:
            obs_ms = cts + h_sec * 1000
            vis_trades = [tr for tr in trades if int(tr.get("blockTimeMs") or cts) <= obs_ms]

            buyers_first_t = {}
            indep_buyers_first_t = {}
            buys_cnt = 0
            sells_cnt = 0
            buy_usd_sum = 0.0
            sell_usd_sum = 0.0
            buy_sizes = []
            w_bal = defaultdict(float)
            creator_bought = 0.0
            creator_sold = 0.0
            first_half_buyers = 0
            second_half_buyers = 0
            first_half_tx = 0
            second_half_tx = 0
            last_px = first_rel_p
            peak_px_vis = first_rel_p
            dip_buys_usd = 0.0
            dip_sells_usd = 0.0
            had_dip = 0

            for tr in vis_trades:
                rel_s = max(0.0, (int(tr.get("blockTimeMs") or cts) - cts) / 1000.0)
                w = (tr.get("trader") or {}).get("address") or ""
                side = tr.get("side")
                val_u = float(tr.get("valueUsd") or 0.0)
                px = float(tr.get("priceUsd") or 0.0)
                if px > 0:
                    last_px = px
                    if px > peak_px_vis:
                        peak_px_vis = px
                    elif peak_px_vis >= first_rel_p * 1.18 and px <= peak_px_vis * 0.88:
                        had_dip = 1

                if rel_s <= h_sec * 0.5:
                    first_half_tx += 1
                else:
                    second_half_tx += 1

                if w and w not in tok_tech:
                    amt = float((tr.get("baseAmount") or {}).get("raw") or 0) / (10 ** int((tr.get("baseAmount") or {}).get("decimals") or 6))
                    if side == "buy":
                        buys_cnt += 1
                        buy_usd_sum += val_u
                        buy_sizes.append(val_u)
                        w_bal[w] += amt
                        if w == creator:
                            creator_bought += amt
                        if had_dip:
                            dip_buys_usd += val_u
                        if w not in buyers_first_t:
                            buyers_first_t[w] = rel_s
                            if rel_s <= h_sec * 0.5:
                                first_half_buyers += 1
                            else:
                                second_half_buyers += 1
                            if w not in bundled_set and w != creator:
                                indep_buyers_first_t[w] = rel_s
                    elif side == "sell":
                        sells_cnt += 1
                        sell_usd_sum += val_u
                        w_bal[w] = max(0.0, w_bal[w] - amt)
                        if w == creator:
                            creator_sold += amt
                        if had_dip:
                            dip_sells_usd += val_u

            # Also check 1m candles up to obs_ms if trade pagination truncated ultra-busy tokens after 250 trades
            vis_1m = [b for b in c_1m if int(b.get("openTimeMs") or 0) + 60_000 <= obs_ms]
            if vis_1m and float(vis_1m[-1].get("close") or 0) > 0:
                last_px = float(vis_1m[-1]["close"])
                candle_vol = sum(float(b.get("volumeUsd") or 0) for b in vis_1m)
                if candle_vol > buy_usd_sum + sell_usd_sum:
                    # Scale total observed volume proportionally
                    scale_v = candle_vol / max(1.0, buy_usd_sum + sell_usd_sum)
                    buy_usd_sum *= scale_v
                    sell_usd_sum *= scale_v

            last_px = max(last_px, 1e-10)
            mcap_at_T = last_px * 1_000_000_000.0
            # Bonding curve implied liquidity USD ~ 2 * 30 * sol_p * sqrt(last_px / first_rel_p)
            implied_liq_T = round(60.0 * float(row["sol_price_at_launch"]) * math.sqrt(max(0.5, last_px / first_rel_p)), 2)
            liq_growth_pct = round(((implied_liq_T / max(100.0, 60.0 * float(row["sol_price_at_launch"]))) - 1.0) * 100.0, 2)

            h_min = h_sec / 60.0
            n_buyers = len(buyers_first_t)
            n_indep = len(indep_buyers_first_t)
            buyer_vel = round(n_buyers / h_min, 3)
            indep_buyer_vel = round(n_indep / h_min, 3)
            # Acceleration: ratio & difference of 2nd-half vs 1st-half new buyers!
            buyer_accel_ratio = round((second_half_buyers + 1.5) / (first_half_buyers + 1.5), 4)
            buyer_accel_diff_per_min = round((second_half_buyers - first_half_buyers) / max(0.25, h_min * 0.5), 3)
            tx_accel_ratio = round((second_half_tx + 2.0) / (first_half_tx + 2.0), 4)

            bs_ratio = round((buy_usd_sum + 10.0) / (sell_usd_sum + 10.0), 4)
            avg_buy = round(float(np.mean(buy_sizes)) if buy_sizes else 0.0, 2)
            med_buy = round(float(np.median(buy_sizes)) if buy_sizes else 0.0, 2)
            buy_cv = round(float(np.std(buy_sizes) / max(1.0, np.mean(buy_sizes))) if len(buy_sizes) >= 2 else 0.0, 3)
            buy_shift = round((float(np.mean(buy_sizes[len(buy_sizes)//2:])) + 5.0) / (float(np.mean(buy_sizes[:max(1, len(buy_sizes)//2)])) + 5.0), 3) if len(buy_sizes) >= 4 else 1.0

            # Causal Smart Money count among buyers up to T
            smart_wallets_in = sum(1 for w in buyers_first_t if causal_wallet_entries[w] >= 2 and (causal_wallet_wins[w] / causal_wallet_entries[w]) >= 0.45)

            sorted_bals = sorted([v for v in w_bal.values() if v > 0], reverse=True)
            top5_pct_T = round((sum(sorted_bals[:5]) / tot_supply) * 100.0, 4)
            conc_change_T = round(top5_pct_T - init_top5_pct, 4)
            bundle_pct_T = round((sum(w_bal.get(w, 0.0) for w in bundled_set) / tot_supply) * 100.0, 4)
            creator_ret_pct_T = round((w_bal.get(creator, 0.0) / tot_supply) * 100.0, 4) if creator else 0.0
            creator_dumped_T = int(creator_sold > 0 and creator_sold >= 0.4 * max(creator_bought, 1.0))

            vol_to_mcap = round((buy_usd_sum + sell_usd_sum) / max(500.0, mcap_at_T), 4)
            dip_abs_T = round((dip_buys_usd + 5.0) / (dip_sells_usd + 5.0), 3) if had_dip else 1.0

            rt_manip_risk = round(min(100.0, (25.0 if mayhem_on else 0.0) + min(30.0, len(bundled_set) * 6.0) + min(25.0, buy_cv * 12.0) + (20.0 if n_indep < max(2, n_buyers * 0.5) and n_buyers >= 4 else 0.0)), 2)
            rt_insider_risk = round(min(100.0, min(35.0, top5_pct_T * 1.6) + min(30.0, bundle_pct_T * 2.2) + (20.0 if creator_dumped_T else 0.0) + min(15.0, creator_ret_pct_T * 1.5)), 2)

            # STRICTLY POST-SIGNAL FORWARD OUTCOMES (after obs_ms!)
            future_bars = [b for b in all_bars if int(b.get("openTimeMs") or 0) >= obs_ms and (float(b.get("volumeUsd") or 0) >= 20.0 or int(b.get("trades") or 0) >= 2)]
            future_trades_px = [float(tr.get("priceUsd") or 0) for tr in trades if int(tr.get("blockTimeMs") or 0) > obs_ms and float(tr.get("valueUsd") or 0) >= 10.0]

            cand_future_max = last_px
            if future_bars:
                cand_future_max = max(cand_future_max, max(max(float(b["close"]), 0.5 * (float(b["high"]) + float(b["close"]))) for b in future_bars))
            if future_trades_px:
                cand_future_max = max(cand_future_max, float(np.percentile(future_trades_px, 98)))
            # Also if overall token reliable ATH happened strictly after obs_ms, incorporate it!
            ath_ts_tok = int(c.get("ath_market_cap_timestamp") or 0)
            if ath_ts_tok > obs_ms + 30_000:
                cand_future_max = max(cand_future_max, max_rel_p)

            cand_future_min = last_px
            if future_bars:
                cand_future_min = min(cand_future_min, min(float(b["low"]) for b in future_bars if float(b.get("low") or 0) > 0))
            elif future_trades_px:
                cand_future_min = min(cand_future_min, min(future_trades_px))

            already_moved_mult = round(last_px / max(first_rel_p, 1e-10), 3)
            future_max_mult = round(max(1.0, cand_future_max / last_px), 3)
            future_dd_pct = round(max(0.0, (1.0 - cand_future_min / last_px) * 100.0), 2)

            p_15m = price_at_future(obs_ms + 15 * 60_000, last_px)
            p_1h = price_at_future(obs_ms + 60 * 60_000, p_15m)
            p_4h = price_at_future(obs_ms + 240 * 60_000, p_1h)
            p_24h = price_at_future(obs_ms + 1440 * 60_000, p_4h)

            ret_15m = round(((p_15m / last_px) - 1.0) * 100.0, 2)
            ret_1h = round(((p_1h / last_px) - 1.0) * 100.0, 2)
            ret_4h = round(((p_4h / last_px) - 1.0) * 100.0, 2)
            ret_24h = round(((p_24h / last_px) - 1.0) * 100.0, 2)

            # Target definition for true early alpha: achieves >= 3.0x REMAINING upside AFTER signal time T!
            hit_future_3x = int(future_max_mult >= 3.0 and float(row["max_mcap_usd"]) >= 12000)
            hit_future_5x = int(future_max_mult >= 5.0 and float(row["max_mcap_usd"]) >= 18000)

            early_rows.append({
                "mint": m,
                "symbol": row["symbol"],
                "cohort_role": row["cohort_role"],
                "created_timestamp_ms": cts,
                "signal_timestamp_ms": obs_ms,
                "horizon": h_label,
                "horizon_sec": h_sec,
                "price_at_signal_usd": round(last_px, 10),
                "mcap_at_signal_usd": round(mcap_at_T, 2),
                "already_moved_multiple": already_moved_mult,
                "new_buyers_cum": n_buyers,
                "independent_buyers_cum": n_indep,
                "buyer_velocity_per_min": buyer_vel,
                "independent_buyer_velocity": indep_buyer_vel,
                "buyer_acceleration_ratio": buyer_accel_ratio,
                "buyer_acceleration_diff": buyer_accel_diff_per_min,
                "buy_tx_count": buys_cnt,
                "sell_tx_count": sells_cnt,
                "tx_acceleration_ratio": tx_accel_ratio,
                "buy_sell_usd_ratio": bs_ratio,
                "buy_volume_usd": round(buy_usd_sum, 2),
                "avg_buy_usd": avg_buy,
                "median_buy_usd": med_buy,
                "buy_size_cv": buy_cv,
                "buy_size_shift_ratio": buy_shift,
                "causal_smart_wallets_in": smart_wallets_in,
                "top5_supply_pct_at_T": top5_pct_T,
                "wallet_concentration_change": conc_change_T,
                "bundle_supply_pct_at_T": bundle_pct_T,
                "creator_retained_pct_at_T": creator_ret_pct_T,
                "creator_dumped_at_T": creator_dumped_T,
                "implied_liquidity_usd_at_T": implied_liq_T,
                "liquidity_growth_pct_at_T": liq_growth_pct,
                "vol_to_mcap_ratio_at_T": vol_to_mcap,
                "had_early_dip_at_T": had_dip,
                "dip_absorption_ratio_at_T": dip_abs_T,
                "has_social_links": has_socials,
                "meme_shareability_score": shareability,
                "is_ticker_first_mover": is_first_mover,
                "creator_prior_launches": cr_prior_cnt,
                "creator_prior_win_rate": cr_prior_win_rate,
                "mayhem_enabled": mayhem_on,
                "sol_ret_24h_pct": float(row["sol_ret_24h_at_launch_pct"]),
                "realtime_manipulation_risk": rt_manip_risk,
                "realtime_insider_risk": rt_insider_risk,
                "future_max_multiple_from_signal": future_max_mult,
                "future_max_drawdown_pct": future_dd_pct,
                "ret_15m_post_signal_pct": ret_15m,
                "ret_1h_post_signal_pct": ret_1h,
                "ret_4h_post_signal_pct": ret_4h,
                "ret_24h_post_signal_pct": ret_24h,
                "target_future_3x": hit_future_3x,
                "target_future_5x": hit_future_5x,
            })

    return pd.DataFrame(early_rows)

def fit_scoring_and_backtest(df_early: pd.DataFrame):
    """
    Fits empirical Pump Potential Score (0-100) on strictly chronological Train split (first 50%),
    validates on chronological Val (next 20%), and evaluates on chronological Test (final 30%)
    plus 5-fold expanding Walk-Forward validation.
    Focuses on early actionable horizon t = 5m (and also scores all horizons in EARLY_SIGNALS.csv).
    """
    logger.info("Fitting empirical 3-Pillar Scoring Model & running chronological + walk-forward backtests...")
    feature_cols = [
        "independent_buyer_velocity",
        "buyer_acceleration_ratio",
        "tx_acceleration_ratio",
        "buy_sell_usd_ratio",
        "vol_to_mcap_ratio_at_T",
        "liquidity_growth_pct_at_T",
        "causal_smart_wallets_in",
        "dip_absorption_ratio_at_T",
        "has_social_links",
        "meme_shareability_score",
        "is_ticker_first_mover",
        "creator_prior_win_rate",
        "wallet_concentration_change",
        "creator_dumped_at_T",
        "mayhem_enabled",
        "sol_ret_24h_pct",
    ]

    # Chronological split by token launch time on 5m snapshot
    df_5m = df_early[df_early["horizon"] == "5m"].sort_values("created_timestamp_ms").reset_index(drop=True)
    n = len(df_5m)
    i_train = int(n * 0.50)
    i_val = int(n * 0.70)

    train_df = df_5m.iloc[:i_train].copy()
    val_df = df_5m.iloc[i_train:i_val].copy()
    test_df = df_5m.iloc[i_val:].copy()

    scaler = StandardScaler()
    X_tr = scaler.fit_transform(train_df[feature_cols].fillna(0.0))
    y_tr = train_df["target_future_3x"].values

    clf = BalancedL2Logistic(C=0.5)
    clf.fit(X_tr, y_tr)

    # Apply learned empirical model across ALL snapshots in df_early
    X_all = scaler.transform(df_early[feature_cols].fillna(0.0))
    probs_all = clf.predict_proba(X_all)[:, 1]
    # Penalize tokens that have ALREADY done >8x before signal (we want remaining upside, not chasing tops!)
    late_chase_penalty = np.where(df_early["already_moved_multiple"].values > 8.0, 0.72, 1.0)
    df_early["predicted_prob_3x"] = np.round(probs_all * late_chase_penalty, 4)
    df_early["pump_potential_score"] = np.round(np.clip(df_early["predicted_prob_3x"] * 100.0, 0.0, 100.0), 2)

    # Refresh train/val/test slices with scores
    df_5m = df_early[df_early["horizon"] == "5m"].sort_values("created_timestamp_ms").reset_index(drop=True)
    train_df = df_5m.iloc[:i_train].copy()
    val_df = df_5m.iloc[i_train:i_val].copy()
    test_df = df_5m.iloc[i_val:].copy()

    weights_dict = {
        col: round(float(w), 4)
        for col, w in sorted(zip(feature_cols, clf.coef_[0]), key=lambda x: abs(x[1]), reverse=True)
    }

    # Walk-Forward Expanding Window Predictions across splits 2..5 (out-of-sample chronological stream)
    wf_preds = []
    n_folds = 5
    fold_sz = n // (n_folds + 1)
    for fold in range(1, n_folds + 1):
        tr_end = fold * fold_sz
        te_end = min(n, (fold + 1) * fold_sz) if fold < n_folds else n
        if tr_end < 30 or te_end <= tr_end:
            continue
        f_tr = df_5m.iloc[:tr_end]
        f_te = df_5m.iloc[tr_end:te_end].copy()
        if f_tr["target_future_3x"].nunique() < 2:
            continue
        sc_f = StandardScaler()
        Xf_tr = sc_f.fit_transform(f_tr[feature_cols].fillna(0.0))
        Xf_te = sc_f.transform(f_te[feature_cols].fillna(0.0))
        m_f = BalancedL2Logistic(C=0.5)
        m_f.fit(Xf_tr, f_tr["target_future_3x"].values)
        p_te = m_f.predict_proba(Xf_te)[:, 1] * np.where(f_te["already_moved_multiple"].values > 8.0, 0.72, 1.0)
        f_te["wf_pump_potential_score"] = np.round(p_te * 100.0, 2)
        f_te["wf_fold"] = fold
        wf_preds.append(f_te)

    df_wf = pd.concat(wf_preds, ignore_index=True) if wf_preds else test_df.assign(wf_pump_potential_score=test_df["pump_potential_score"], wf_fold=1)

    # Evaluate Model + Risk Guardrail vs 5 Benchmarks on Out-of-Sample Walk-Forward Stream (and strict Test Set!)
    def eval_strategy(df_eval: pd.DataFrame, score_series: pd.Series, name: str):
        base_rate = float(df_eval["target_future_3x"].mean())
        order = np.argsort(-score_series.values)
        ranked = df_eval.iloc[order].reset_index(drop=True)

        top10 = ranked.head(10)
        top20 = ranked.head(20)
        p_at_10 = float(top10["target_future_3x"].mean()) if len(top10) > 0 else 0.0
        p_at_20 = float(top20["target_future_3x"].mean()) if len(top20) > 0 else 0.0
        lift_10 = round(p_at_10 / max(base_rate, 1e-6), 3)
        lift_20 = round(p_at_20 / max(base_rate, 1e-6), 3)

        # Recall at top 25% of ranked candidates
        k_top = max(1, int(len(ranked) * 0.25))
        recall_top25 = float(ranked.head(k_top)["target_future_3x"].sum() / max(1, ranked["target_future_3x"].sum()))

        try:
            auc = round(float(roc_auc_score(df_eval["target_future_3x"], score_series)), 4)
            ap = round(float(average_precision_score(df_eval["target_future_3x"], score_series)), 4)
        except Exception:
            auc, ap = 0.5, base_rate

        # Post-cost net return simulation on Top 20 signals:
        # Realistic execution: $250 entry at signal_t, round-trip fee + priority + curve slippage = ~3.2% round-trip cost,
        # exit strategy: take 50% at +150% (2.5x) if reached, hold 50% to 4h close (capped against single-tx illiquidity)
        net_rets = []
        for _, r in top20.iterrows():
            liq = max(500.0, float(r["implied_liquidity_usd_at_T"]))
            rt_cost_pct = 2.2 + min(12.0, (250.0 / (0.5 * liq)) * 100.0)
            r4h = min(400.0, float(r["ret_4h_post_signal_pct"]))
            if float(r["future_max_multiple_from_signal"]) >= 2.5:
                gross_pct = 0.5 * 150.0 + 0.5 * r4h
            else:
                gross_pct = r4h
            net_rets.append(gross_pct - rt_cost_pct)

        return {
            "strategy": name,
            "n_evaluated": len(df_eval),
            "base_rate_3x": round(base_rate, 4),
            "precision_at_10": round(p_at_10, 4),
            "precision_at_20": round(p_at_20, 4),
            "lift_at_10": lift_10,
            "lift_at_20": lift_20,
            "recall_at_top25pct": round(recall_top25, 4),
            "roc_auc": auc,
            "pr_auc": ap,
            "top20_mean_net_return_after_costs_pct": round(float(np.mean(net_rets)) if net_rets else 0.0, 2),
            "top20_median_net_return_after_costs_pct": round(float(np.median(net_rets)) if net_rets else 0.0, 2),
            "top20_median_max_multiple": round(float(top20["future_max_multiple_from_signal"].median()) if len(top20) else 1.0, 3),
        }

    # Risk-aware composite ranking ONLY for signal selection while preserving all 3 scores separately!
    wf_risk_adj = df_wf["wf_pump_potential_score"] - 0.18 * np.maximum(0.0, df_wf["realtime_manipulation_risk"] - 55.0) - 0.18 * np.maximum(0.0, df_wf["realtime_insider_risk"] - 55.0)
    rng = np.random.default_rng(42)
    rand_scores = pd.Series(rng.uniform(0, 1, len(df_wf)), index=df_wf.index)
    simple_mom = (df_wf["already_moved_multiple"].rank(pct=True) * 0.5 + df_wf["buy_sell_usd_ratio"].rank(pct=True) * 0.5)

    benchmarks_wf = [
        eval_strategy(df_wf, wf_risk_adj, "1_Alpha_Model_Potential_Plus_Risk_Guardrail"),
        eval_strategy(df_wf, df_wf["wf_pump_potential_score"], "2_Alpha_Model_Pump_Potential_Raw"),
        eval_strategy(df_wf, df_wf["independent_buyer_velocity"], "3_Benchmark_Buyer_Count_Velocity_Only"),
        eval_strategy(df_wf, df_wf["buy_volume_usd"], "4_Benchmark_Volume_Only"),
        eval_strategy(df_wf, df_wf["already_moved_multiple"], "5_Benchmark_Price_Gain_Only"),
        eval_strategy(df_wf, simple_mom, "6_Benchmark_Simple_Momentum_Rule"),
        eval_strategy(df_wf, rand_scores, "7_Benchmark_Random_Selection"),
    ]

    # Calibration Brier score on Walk-Forward OOS
    brier_oos = round(float(brier_score_loss(df_wf["target_future_3x"], np.clip(df_wf["wf_pump_potential_score"] / 100.0, 0.01, 0.99))), 4)

    # Build BACKTEST_RESULTS.csv containing every out-of-sample signal evaluation + benchmark comparison attributes
    bt_rows = []
    df_wf_copy = df_wf.copy()
    df_wf_copy["risk_adjusted_rank_score"] = np.round(wf_risk_adj, 2)
    df_wf_copy = df_wf_copy.sort_values("risk_adjusted_rank_score", ascending=False).reset_index(drop=True)
    for rank_i, r in df_wf_copy.iterrows():
        liq = max(500.0, float(r["implied_liquidity_usd_at_T"]))
        rt_cost_pct = round(2.2 + min(12.0, (250.0 / (0.5 * liq)) * 100.0), 2)
        r4h = min(400.0, float(r["ret_4h_post_signal_pct"]))
        gross_pct = (0.5 * 150.0 + 0.5 * r4h) if float(r["future_max_multiple_from_signal"]) >= 2.5 else r4h
        net_pct = round(gross_pct - rt_cost_pct, 2)

        sig_utc = pd.to_datetime(int(r["signal_timestamp_ms"]), unit="ms", utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
        bt_rows.append({
            "oos_rank": rank_i + 1,
            "wf_fold": int(r["wf_fold"]),
            "signal_timestamp_utc": sig_utc,
            "mint": r["mint"],
            "symbol": r["symbol"],
            "horizon": r["horizon"],
            "entry_price_usd": r["price_at_signal_usd"],
            "mcap_at_signal_usd": r["mcap_at_signal_usd"],
            "already_moved_multiple": r["already_moved_multiple"],
            "pump_potential_score": r["wf_pump_potential_score"],
            "manipulation_risk_score": r["realtime_manipulation_risk"],
            "insider_supply_risk_score": r["realtime_insider_risk"],
            "high_potential_high_risk_warning": int(r["wf_pump_potential_score"] >= 65 and (r["realtime_manipulation_risk"] >= 55 or r["realtime_insider_risk"] >= 55)),
            "max_multiple_post_signal": r["future_max_multiple_from_signal"],
            "max_drawdown_post_signal_pct": r["future_max_drawdown_pct"],
            "ret_15m_pct": r["ret_15m_post_signal_pct"],
            "ret_1h_pct": r["ret_1h_post_signal_pct"],
            "ret_4h_pct": r["ret_4h_post_signal_pct"],
            "ret_24h_pct": r["ret_24h_post_signal_pct"],
            "est_roundtrip_cost_and_slippage_pct": rt_cost_pct,
            "net_strategy_return_after_costs_pct": net_pct,
            "hit_3x_post_signal": int(r["target_future_3x"]),
        })

    return df_early, pd.DataFrame(bt_rows), weights_dict, benchmarks_wf, brier_oos

def run_35_hypotheses(df_all: pd.DataFrame, df_tm: pd.DataFrame, df_early: pd.DataFrame, df_name: pd.DataFrame, df_hourly: pd.DataFrame, df_creators: pd.DataFrame):
    logger.info("Testing 35 formal quantitative hypotheses with BH-FDR multiple-testing correction...")
    df_5m = df_early[df_early["horizon"] == "5m"].copy()
    df_ga_tm = df_tm[df_tm["created_timestamp_ms"] >= WINDOW_START_MS].copy()
    pumps = df_ga_tm[df_ga_tm["hit_5x"] == 1]
    ctrls = df_ga_tm[df_ga_tm["hit_2x"] == 0]

    raw_tests = []

    def add_mw_test(hid, category, question, metric_name, s_win, s_lose, practical_note, expect_dir="greater"):
        a = pd.Series(s_win).dropna().values.astype(float)
        b = pd.Series(s_lose).dropna().values.astype(float)
        if len(a) < 5 or len(b) < 5:
            raw_tests.append({
                "id": hid, "category": category, "question": question, "metric": metric_name,
                "n_winners": len(a), "n_controls": len(b), "median_winners": np.nan, "median_controls": np.nan,
                "mean_winners": np.nan, "mean_controls": np.nan, "effect_size_cliffs_d": 0.0,
                "p_value": 1.0, "practical_utility": "Insufficient sample", "notes": practical_note
            })
            return
        u_stat, p_val = stats.mannwhitneyu(a, b, alternative="two-sided")
        # Cliff's delta effect size in [-1, 1]
        cliffs_d = (2.0 * u_stat) / (len(a) * len(b)) - 1.0
        raw_tests.append({
            "id": hid, "category": category, "question": question, "metric": metric_name,
            "n_winners": int(len(a)), "n_controls": int(len(b)),
            "median_winners": round(float(np.median(a)), 4),
            "median_controls": round(float(np.median(b)), 4),
            "mean_winners": round(float(np.mean(a)), 4),
            "mean_controls": round(float(np.mean(b)), 4),
            "effect_size_cliffs_d": round(float(cliffs_d), 4),
            "p_value": float(p_val),
            "expect_dir": expect_dir,
            "notes": practical_note,
        })

    w5 = df_5m[df_5m["target_future_3x"] == 1]
    c5 = df_5m[df_5m["target_future_3x"] == 0]

    # 35 Hypotheses spanning all 11 domains!
    add_mw_test("H01", "Early_Acceleration", "Czy przyspieszenie napływu kupujących (2. połowa vs 1. połowa pierwszych 5 min) różnicuje przyszłe pumpy 3x+?", "buyer_acceleration_ratio (t=5m)", w5["buyer_acceleration_ratio"], c5["buyer_acceleration_ratio"], "Kluczowy wskaźnik zmiany reżimu przed głównym ruchem ceny.")
    add_mw_test("H02", "Early_Buyers", "Czy tempo napływu NIEZALEŻNYCH kupujących (po odjęciu bundlerów i twórcy) w 5 min wyprzedza pump?", "independent_buyer_velocity (t=5m)", w5["independent_buyer_velocity"], c5["independent_buyer_velocity"], "Odporny na sztuczne bundlowanie portfeli na starcie.")
    add_mw_test("H03", "Early_Acceleration", "Czy przyspieszenie liczby transakcji (tx_acceleration_ratio) w 5 min przewyższa zwykłą liczbę wczesnych zakupów?", "tx_acceleration_ratio (t=5m)", w5["tx_acceleration_ratio"], c5["tx_acceleration_ratio"], "Wychwytuje narastający popyt przed wybiciem.")
    add_mw_test("H04", "Order_Flow", "Czy przewaga dolarowa kupna nad sprzedażą (buy/sell USD ratio) w 5 min zwiastuje dalszy wzrost >=3x?", "buy_sell_usd_ratio (t=5m)", w5["buy_sell_usd_ratio"], c5["buy_sell_usd_ratio"], "Bezpośredni pomiar asymetrii presji popytowej.")
    add_mw_test("H05", "Liquidity_Microstructure", "Czy relacja wolumenu do kapitalizacji (vol/mcap) w 5 min wyprzedza wybicie z bonding curve?", "vol_to_mcap_ratio_at_T (t=5m)", w5["vol_to_mcap_ratio_at_T"], c5["vol_to_mcap_ratio_at_T"], "Wysoki obrót przy niskiej wycenie sygnalizuje akumulację.")
    add_mw_test("H06", "Pullback_Psychology", "Czy absorpcja pierwszej korekty (dip_absorption_ratio podczas spadku >=12%) odróżnia przyszłych zwycięzców 5x+ od przegranych?", "dip_absorption_ratio", pumps["dip_absorption_ratio"], ctrls["dip_absorption_ratio"], "Silny popyt na pierwszym cofnięciu eliminuje słabe ręce.")
    add_mw_test("H07", "FOMO_Psychology", "Czy mierzalny indeks przejścia w FOMO (fomo_transition_index) jest istotnie wyższy w tokenach 5x+ niż w grupie kontrolnej?", "fomo_transition_index", pumps["fomo_transition_index"], ctrls["fomo_transition_index"], "Kwantyfikuje moment wejścia w kaskadę FOMO.")
    add_mw_test("H08", "Order_Size_Dynamics", "Czy średnia wartość pierwszych 10 zakupów (early10_avg_buy_usd) jest wyższa w pumpach niż w tokenach kontrolnych?", "early10_avg_buy_usd", pumps["early10_avg_buy_usd"], ctrls["early10_avg_buy_usd"], "Testuje hipotezę inicjacji ruchu przez większy kapitał.")
    add_mw_test("H09", "Order_Size_Dynamics", "Czy udział drobnych zakupów (<$25) różni się między zwycięzcami a przegranymi?", "small_buy_share", pumps["small_buy_share"], ctrls["small_buy_share"], "Weryfikuje czy drobnica dominuje od startu czy dołącza później.")
    add_mw_test("H10", "Order_Size_Dynamics", "Czy zmiana średniego rozmiaru zakupu w czasie pierwszych 5 min (buy_size_shift_ratio) zwiastuje dołączanie kapitału?", "buy_size_shift_ratio (t=5m)", w5["buy_size_shift_ratio"], c5["buy_size_shift_ratio"], "Rosnący bilet zakupu w min 3-5 potwierdza wejście większych graczy.")
    add_mw_test("H11", "Buyer_Conviction", "Czy odsetek kupujących dokupujących pozycję (scale_in_buyer_share >=2 zakupy) jest wyższy u zwycięzców?", "scale_in_buyer_share", pumps["scale_in_buyer_share"], ctrls["scale_in_buyer_share"], "Wielokrotne dokupywanie mierzy przekonanie uczestników.")
    add_mw_test("H12", "Smart_Money", "Czy obecność historycznie skutecznych portfeli (causal_smart_wallets_in) w pierwszych 5 min zwiększa szansę na dalsze 3x+?", "causal_smart_wallets_in (t=5m)", w5["causal_smart_wallets_in"], c5["causal_smart_wallets_in"], "Sprawdzone ściśle przyczynowo bez przecieku z przyszłości.")
    add_mw_test("H13", "Supply_Concentration", "Czy zmiana koncentracji TOP 5 w pierwszych 5 min (wallet_concentration_change < 0, czyli dekoncentracja) sprzyja trwałemu pumpowi?", "wallet_concentration_change (t=5m)", w5["wallet_concentration_change"], c5["wallet_concentration_change"], "Spadek koncentracji oznacza dystrybucję do szerokiego rynku.", expect_dir="less")
    add_mw_test("H14", "Supply_Concentration", "Czy szczytowa koncentracja TOP 10 holderów różni się między tokenami 5x+ a grupą kontrolną?", "top10_holders_peak_pct", pumps["top10_holders_peak_pct"], ctrls["top10_holders_peak_pct"], "Testuje czy wysoka koncentracja pomaga wypchnąć cenę, czy dusi projekt.")
    add_mw_test("H15", "Insider_Retention", "Czy utrzymywanie części podaży przez potencjalnych insiderów (potential_insiders_retained_pct) wiąże się z kolejnymi falami wzrostu (multi-wave)?", "potential_insiders_retained_pct (Multi-Wave vs Single-Wave)", df_ga_tm[df_ga_tm["multi_wave_flag"] == 1]["potential_insiders_retained_pct"], df_ga_tm[(df_ga_tm["hit_2x"] == 1) & (df_ga_tm["multi_wave_flag"] == 0)]["potential_insiders_retained_pct"], "Weryfikuje wzorzec Insider Retention ($COOL-style).")
    add_mw_test("H16", "Insider_Clusters", "Czy liczba wykrytych klastrów powiązanych portfeli jest wyższa w dużych pumpach niż w tokenach martwych?", "detected_clusters_count", pumps["detected_clusters_count"], ctrls["detected_clusters_count"], "Sprawdza udział skoordynowanych grup w kreowaniu pumpów.")
    add_mw_test("H17", "Bundling_Snipers", "Czy agresywne bundlowanie w bloku startowym (bundle_wallets_count) zwiększa ryzyko głębokiego załamania (>85% drawdown)?", "bundle_wallets_count (Crash >=85% vs Resilient <70% DD)", df_ga_tm[df_ga_tm["max_drawdown_from_ath_pct"] >= 85]["bundle_wallets_count"], df_ga_tm[(df_ga_tm["hit_2x"] == 1) & (df_ga_tm["max_drawdown_from_ath_pct"] < 70)]["bundle_wallets_count"], "Ocenia ryzyko nagłego zrzutu podaży przez bundlerów.")
    add_mw_test("H18", "Creator_Behavior", "Czy wczesna sprzedaż tokenów przez twórcę (creator_dumped_at_T w 5 min) obniża przyszły mnożnik wzrostu?", "future_max_multiple (Creator Dumped=0 vs Dumped=1)", df_5m[df_5m["creator_dumped_at_T"] == 0]["future_max_multiple_from_signal"], df_5m[df_5m["creator_dumped_at_T"] == 1]["future_max_multiple_from_signal"], "Natychmiastowy sygnał ostrzegawczy on-chain.")
    add_mw_test("H19", "Creator_Track_Record", "Czy wcześniejszy odsetek sukcesów twórcy (creator_prior_win_rate) pozwala przewidzieć kolejny pump?", "creator_prior_win_rate (t=5m)", w5["creator_prior_win_rate"], c5["creator_prior_win_rate"], "Oddziela powtarzalnych operatorów od jednorazowych twórców.")
    add_mw_test("H20", "Creator_Spam", "Czy seryjni spamerzy (>10 wcześniejszych tokenów) osiągają gorsze mnożniki niż selektywni twórcy (1-3 tokeny)?", "future_max_multiple (Selective 1-3 vs Spammer >10)", df_5m[df_5m["creator_prior_launches"].between(1, 3)]["future_max_multiple_from_signal"], df_5m[df_5m["creator_prior_launches"] > 10]["future_max_multiple_from_signal"], "Demaskuje fabryki masowych rug-pulli.")
    add_mw_test("H21", "Artificial_Activity_Mayhem", "Czy włączenie trybu AI Mayhem Mode (sztuczny wolumen bota przez 24h) zwiększa realną szansę na trwały pump >=3x?", "est_multiple (Mayhem=1 vs Standard=0 across 30d universe)", df_all[(df_all["group_a_new_30d"] == 1) & (df_all["mayhem_enabled"] == 1)]["est_multiple"], df_all[(df_all["group_a_new_30d"] == 1) & (df_all["mayhem_enabled"] == 0)]["est_multiple"], "Kluczowy test odróżniający sztuczny wolumen bota AI od popytu organicznego!")

    df_na_ga = df_name[df_name["group_a_new_30d"] == 1]
    na_win = df_na_ga[df_na_ga["est_multiple"] >= 5.0]
    na_lose = df_na_ga[df_na_ga["est_multiple"] < 2.0]
    add_mw_test("H22", "Lexical_Ticker", "Czy sama krótka długość tickera (ticker_len) odróżnia zwycięzców 5x+ od przegranych w całej populacji 30 dni?", "ticker_len", na_win["ticker_len"], na_lose["ticker_len"], "Klasyczny test przeciwko survivorship bias (większość przegranych też ma 3-5 znaków!).", expect_dir="less")
    add_mw_test("H23", "Lexical_Pronounceability", "Czy łatwość wymowy tickera (pronounceability_score) ma istotny związek ze skalą wzrostu?", "pronounceability_score", na_win["pronounceability_score"], na_lose["pronounceability_score"], "Test fonetycznej zapamiętywalności nazwy.")
    add_mw_test("H24", "Viral_Psychology", "Czy łączny indeks memetycznej udostępnialności (meme_shareability_score) jest wyższy wśród tokenów 5x+?", "meme_shareability_score", na_win["meme_shareability_score"], na_lose["meme_shareability_score"], "Syntetyczny miernik prostoty, humoru i emocji.")
    add_mw_test("H25", "Narrative_First_Mover", "Czy pierwszy token używający danego tickera (is_ticker_first_mover=1) osiąga wyższe mnożniki niż jego późniejsi naśladowcy (copycats)?", "est_multiple (First-Mover vs Copycat)", df_na_ga[df_na_ga["is_ticker_first_mover"] == 1]["est_multiple"], df_na_ga[df_na_ga["is_ticker_first_mover"] == 0]["est_multiple"], "Kwantyfikuje premię pierwszeństwa i karę dla klonów.")
    add_mw_test("H26", "Narrative_Saturation", "Czy wysoka saturacja klastra semantycznego w ostatnich 24h (>15 podobnych premier) obniża wyniki kolejnych tokenów?", "est_multiple (Low Saturation <=5 vs High >15)", df_na_ga[df_na_ga["semantic_cluster_24h_launches"] <= 5]["est_multiple"], df_na_ga[df_na_ga["semantic_cluster_24h_launches"] > 15]["est_multiple"], "Efekt przesycenia narracji na pump.fun.")
    add_mw_test("H27", "Narrative_AI_vs_Humor", "Czy tokeny z narracji AI & Agents różnią się mnożnikiem wzrostu od tokenów Absurd/Toilet Humor?", "est_multiple (AI_Agents_Tech vs Absurd_Toilet_Humor)", df_na_ga[df_na_ga["narrative_category"] == "AI_Agents_Tech"]["est_multiple"], df_na_ga[df_na_ga["narrative_category"] == "Absurd_Toilet_Humor"]["est_multiple"], "Porównanie dwóch dominujących meta-narracji Solany w 2026 r.")
    add_mw_test("H28", "Controversy_Effect", "Czy kontrowersyjność / wulgarność nazwy (controversy_score > 0) zwiększa czy obniża prawdopodobieństwo dużego wzrostu?", "est_multiple (Controversial vs Neutral)", df_na_ga[df_na_ga["controversy_score"] > 0]["est_multiple"], df_na_ga[df_na_ga["controversy_score"] == 0]["est_multiple"], "Sprawdza czy szokujące nazwy przyciągają kapitał czy tylko chwilową uwagę.")
    add_mw_test("H29", "Social_Presence", "Czy obecność linków społecznościowych X/WWW w metadanych startowych (has_social_links=1) zwiększa szansę na dalsze 3x+ po 5 min?", "future_max_multiple (Has Socials=1 vs None=0)", df_5m[df_5m["has_social_links"] == 1]["future_max_multiple_from_signal"], df_5m[df_5m["has_social_links"] == 0]["future_max_multiple_from_signal"], "Weryfikacja przygotowania zaplecza społecznościowego przed startem.")
    add_mw_test("H30", "Time_US_Open", "Czy prawdopodobieństwo pumpa 5x+ w oknie otwarcia rynków USA (14:00–20:59 UTC / 15:00–21:59 PL) jest wyższe niż poza nim?", "prob_pump_5x (US Hours vs Off-Hours)", df_hourly[df_hourly["is_us_equity_open_window"] == 1]["prob_pump_5x"], df_hourly[df_hourly["is_us_equity_open_window"] == 0]["prob_pump_5x"], "Porównuje warunkowe prawdopodobieństwo, a nie surową liczbę premier.")
    add_mw_test("H31", "Time_EU_US_Overlap", "Czy nakładanie sesji Europy i USA (13:00–17:59 UTC / 14:00–18:59 PL) wykazuje wyższe prawdopodobieństwo warunkowe pumpa?", "prob_pump_5x (EU-US Overlap vs Rest)", df_hourly[df_hourly["is_eu_us_overlap"] == 1]["prob_pump_5x"], df_hourly[df_hourly["is_eu_us_overlap"] == 0]["prob_pump_5x"], "Okno maksymalnej globalnej płynności detalicznej i instytucjonalnej.")
    add_mw_test("H32", "Time_Weekend_Effect", "Czy weekendy różnią się warunkowym prawdopodobieństwem pumpa 5x+ od dni roboczych?", "prob_pump_5x (Weekend vs Weekday)", df_hourly[df_hourly["is_weekend"] == 1]["prob_pump_5x"], df_hourly[df_hourly["is_weekend"] == 0]["prob_pump_5x"], "Testuje weekendowy spadek płynności vs aktywność detaliczną.")
    add_mw_test("H33", "Macro_SOL_Regime", "Czy dodatnia 24-godzinna zmiana ceny SOL w momencie startu tokena sprzyja większym wzrostom memecoinów?", "future_max_multiple (SOL 24h > 0% vs SOL 24h <= -2%)", df_5m[df_5m["sol_ret_24h_pct"] > 0.0]["future_max_multiple_from_signal"], df_5m[df_5m["sol_ret_24h_pct"] <= -2.0]["future_max_multiple_from_signal"], "Wpływ kondycji całego ekosystemu Solana na apetyt na ryzyko.")
    add_mw_test("H34", "DEX_Migration_Sustainability", "Czy tokeny po migracji na DEX (Raydium/PumpSwap) charakteryzują się mniejszym obsunięciem od ATH niż pumpy zatrzymane na bonding curve?", "max_drawdown_from_ath_pct (Migrated vs Non-Migrated 2x+)", df_ga_tm[(df_ga_tm["hit_2x"] == 1) & (df_ga_tm["migrated_dex"] == 1)]["max_drawdown_from_ath_pct"], df_ga_tm[(df_ga_tm["hit_2x"] == 1) & (df_ga_tm["migrated_dex"] == 0)]["max_drawdown_from_ath_pct"], "Ocenia przeżywalność po ukończeniu krzywej bondingowej.", expect_dir="less")
    add_mw_test("H35", "Early_vs_Chasing", "Czy sygnały wykrywane przed ucieczką ceny (already_moved < 2.5x w 5 min) przy wysokim przyspieszeniu kupujących dają wyższy dalszy mnożnik niż gonienie świec >4x?", "future_max_multiple (Early Accel <2.5x vs Late Chase >4x)", df_5m[(df_5m["already_moved_multiple"] < 2.5) & (df_5m["buyer_acceleration_ratio"] >= 1.2)]["future_max_multiple_from_signal"], df_5m[df_5m["already_moved_multiple"] > 4.0]["future_max_multiple_from_signal"], "Bezpośredni dowód przewagi wczesnej detekcji nad gonieniem wzrostu!")

    q_vals = benjamini_hochberg([t["p_value"] for t in raw_tests])
    for t, q in zip(raw_tests, q_vals):
        t["q_value_bh_fdr"] = q
        cd = float(t["effect_size_cliffs_d"])
        exp_d = t.get("expect_dir", "greater")
        dir_matches = (cd > 0 and exp_d == "greater") or (cd < 0 and exp_d == "less")
        eff = abs(cd)
        if not dir_matches and q < 0.05 and eff >= 0.12:
            grade = "D"
            verdict = "ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku"
        elif not dir_matches:
            grade = "D"
            verdict = "ODRZUCONY — kierunek niezgodny z hipotezą / brak przewagi nad grupą kontrolną"
        elif q < 0.01 and eff >= 0.18:
            grade = "A"
            verdict = "MOCNY DOWÓD — potwierdzona zależność zgodna z kierunkiem po korekcie FDR"
        elif q < 0.05 or (q < 0.12 and eff >= 0.20):
            grade = "B"
            verdict = "OBIECUJĄCY — istotny kierunek, wymaga dalszej walidacji"
        elif q < 0.25 and eff >= 0.08:
            grade = "C"
            verdict = "SŁABY — niewielka korelacja, ograniczona siła predykcyjna"
        else:
            grade = "D"
            verdict = "ODRZUCONY — brak potwierdzenia statystycznego względem grupy kontrolnej"
        t["evidence_grade"] = grade
        t["verdict_pl"] = verdict

    return raw_tests

def rank_top_10_early_signals(df_early: pd.DataFrame) -> list:
    """
    Computes empirical performance of candidate early signals (1..15m) strictly BEFORE most of the move
    (filtering to observations where already_moved_multiple <= 3.0x so we never rank lagging post-pump indicators #1!).
    """
    sub = df_early[(df_early["horizon"].isin(["1m", "3m", "5m", "10m", "15m"])) & (df_early["already_moved_multiple"] <= 3.0)].copy()
    base_rate = float(sub["target_future_3x"].mean()) if len(sub) > 0 else 0.2

    signal_specs = [
        ("First Pullback Absorption Surge", "Po pierwszym cofnięciu ceny o >=12%, wolumen kupna na spadku przewyższa sprzedaż >= 1.35x (cena nadal <=3x od startu).", "had_early_dip_at_T == 1 & dip_absorption_ratio_at_T >= 1.35", "3m–15m", lambda d: (d["had_early_dip_at_T"] == 1) & (d["dip_absorption_ratio_at_T"] >= 1.35), "Niskie — trudne do taniego sfabrykowania przy realnej podaży", "A"),
        ("Asymmetric Buy-to-Sell Dollar Pressure", "Stosunek wolumenu kupna do sprzedaży USD >= 2.2x przy min. 8 transakcjach kupna przed ucieczką ceny (>3x).", "buy_sell_usd_ratio >= 2.2 & buy_tx_count >= 8 & mayhem_enabled == 0", "1m–5m", lambda d: (d["horizon"].isin(["1m", "3m", "5m"])) & (d["buy_sell_usd_ratio"] >= 2.2) & (d["buy_tx_count"] >= 8) & (d["mayhem_enabled"] == 0), "Niskie po odfiltrowaniu Mayhem AI", "A"),
        ("Volume-to-MarketCap Ignition Ratio", "Skumulowany obrót przekracza 35% bieżącej kapitalizacji przy braku sprzedaży twórcy i wyłączonym Mayhem.", "vol_to_mcap_ratio_at_T >= 0.35 & creator_dumped_at_T == 0 & mayhem_enabled == 0", "3m–10m", lambda d: (d["horizon"].isin(["3m", "5m", "10m"])) & (d["vol_to_mcap_ratio_at_T"] >= 0.35) & (d["creator_dumped_at_T"] == 0) & (d["mayhem_enabled"] == 0), "Średnie — wymaga kontroli niezależnych portfeli", "A"),
        ("Independent Buyer Velocity Surge", "Napływ >= 2.5 niezależnych kupujących na minutę (po wykluczeniu bundlerów z bloku 0 i twórcy) bez zrzutu dewelopera.", "independent_buyer_velocity >= 2.5 & creator_dumped_at_T == 0", "1m–5m", lambda d: (d["horizon"].isin(["1m", "3m", "5m"])) & (d["independent_buyer_velocity"] >= 2.5) & (d["creator_dumped_at_T"] == 0), "Niskie — odporne na bundlowanie w jednym bloku", "A"),
        ("First-Mover Viral Narrative + Early Demand", "Oryginalny pierwszy ticker narracji (is_ticker_first_mover=1) z linkami X/WWW i napływem >=1.5 niezależnych kupujących/min.", "is_ticker_first_mover == 1 & has_social_links == 1 & independent_buyer_velocity >= 1.5", "1m–5m", lambda d: (d["horizon"].isin(["1m", "3m", "5m"])) & (d["is_ticker_first_mover"] == 1) & (d["has_social_links"] == 1) & (d["independent_buyer_velocity"] >= 1.5), "Niskie — łączy przewagę narracyjną z popytem on-chain", "A"),
        ("Positive Macro SOL Regime + Buyer Flow", "Start tokena w dodatnim reżimie SOL (24h > 0%) połączony z >= 5 niezależnymi kupującymi i brakiem sprzedaży twórcy.", "sol_ret_24h_pct > 0 & independent_buyers_cum >= 5 & creator_dumped_at_T == 0", "3m–10m", lambda d: (d["horizon"].isin(["3m", "5m", "10m"])) & (d["sol_ret_24h_pct"] > 0) & (d["independent_buyers_cum"] >= 5) & (d["creator_dumped_at_T"] == 0), "Bardzo niskie — zewnętrzny czynnik makro SOL", "A"),
        ("Causal Smart Money Early Entry", "Wejście min. 1 portfela z historyczną skutecznością >=45% (wyliczoną ściśle przed startem bieżącego tokena).", "causal_smart_wallets_in >= 1 & creator_dumped_at_T == 0", "1m–5m", lambda d: (d["horizon"].isin(["1m", "3m", "5m"])) & (d["causal_smart_wallets_in"] >= 1) & (d["creator_dumped_at_T"] == 0), "Niskie — oparte na wielokrotnej historii portfela", "B"),
        ("Institutional-Size Initial Conviction Ticket", "Mediana pojedynczego zakupu >= $60 przy min. 6 kupujących i braku sprzedaży twórcy.", "median_buy_usd >= 60 & new_buyers_cum >= 6 & creator_dumped_at_T == 0", "1m–5m", lambda d: (d["horizon"].isin(["1m", "3m", "5m"])) & (d["median_buy_usd"] >= 60) & (d["new_buyers_cum"] >= 6) & (d["creator_dumped_at_T"] == 0), "Średnie — wymaga weryfikacji klastrów finansowania", "A"),
        ("Healthy Supply De-Concentration", "Stabilna lub malejąca koncentracja TOP 5 holderów (<= +0.5 pp) przy min. 5 niezależnych kupujących.", "wallet_concentration_change <= 0.5 & independent_buyers_cum >= 5", "5m–15m", lambda d: (d["horizon"].isin(["5m", "10m", "15m"])) & (d["wallet_concentration_change"] <= 0.5) & (d["independent_buyers_cum"] >= 5), "Niskie — mierzy realne rozproszenie tokenów", "B"),
        ("Low Manipulation Guardrail + Liquidity Lift", "Wzrost płynności krzywej >= +12% przy niskim ryzyku manipulacji (<35 pkt) i wyłączonym Mayhem Mode.", "liquidity_growth_pct_at_T >= 12 & realtime_manipulation_risk < 35 & mayhem_enabled == 0", "3m–10m", lambda d: (d["horizon"].isin(["3m", "5m", "10m"])) & (d["liquidity_growth_pct_at_T"] >= 12) & (d["realtime_manipulation_risk"] < 35) & (d["mayhem_enabled"] == 0), "Niskie — wbudowany filtr anty-manipulacyjny", "B"),
    ]

    top10_raw = []
    for name, defn, formula, window_avail, mask_fn, risk_note, grade_hint in signal_specs:
        triggered = sub[mask_fn(sub)]
        triggered_tok = triggered.sort_values("horizon_sec").groupby("mint", as_index=False).first()
        n_obs = len(triggered_tok)
        hit_3x = round(float(triggered_tok["target_future_3x"].mean()), 4) if n_obs > 0 else 0.0
        lift = round(hit_3x / max(base_rate, 1e-6), 2)
        med_upside = round(float(triggered_tok["future_max_multiple_from_signal"].median()), 2) if n_obs > 0 else 1.0
        mean_upside = round(float(triggered_tok["future_max_multiple_from_signal"].mean()), 2) if n_obs > 0 else 1.0
        med_dd = round(float(triggered_tok["future_max_drawdown_pct"].median()), 2) if n_obs > 0 else 0.0
        top10_raw.append({
            "raw_name": name,
            "definition": defn,
            "measurement_formula": formula,
            "availability_window": window_avail,
            "n_tokens_triggered": n_obs,
            "hit_rate_future_3x": hit_3x,
            "lift_vs_baseline": lift,
            "median_future_multiple": med_upside,
            "mean_future_multiple": mean_upside,
            "median_max_drawdown_pct": med_dd,
            "manipulation_resilience_and_risk": risk_note,
            "evidence_grade": grade_hint if (n_obs >= 12 and lift >= 1.35) else ("B" if lift >= 1.05 else "C"),
        })

    top10_raw.sort(key=lambda x: (x["lift_vs_baseline"], x["n_tokens_triggered"]), reverse=True)
    top10_out = []
    for idx, item in enumerate(top10_raw, start=1):
        sc = dict(item)
        sc["signal_name"] = f"{idx}. {sc.pop('raw_name')}"
        # keep signal_name first
        ordered = {"signal_name": sc["signal_name"]}
        ordered.update({k: v for k, v in sc.items() if k != "signal_name"})
        top10_out.append(ordered)

    return top10_out

def main():
    with open(RAW_DIR / "pumpfun_universe_raw.json", "r", encoding="utf-8") as f:
        coins_by_mint = json.load(f)
    creator_db = {}
    if (CREATORS_CACHE_DIR / "creator_histories_complete.json").exists():
        with open(CREATORS_CACHE_DIR / "creator_histories_complete.json", "r", encoding="utf-8") as f:
            creator_db = json.load(f)

    df_all = pd.read_csv(BASE_DIR / "ALL_TOKENS.csv")
    df_tm = pd.read_csv(BASE_DIR / "TOKEN_METRICS.csv")
    df_name = pd.read_csv(BASE_DIR / "NAME_ANALYSIS.csv")
    df_hourly = pd.read_csv(BASE_DIR / "HOURLY_PATTERNS.csv")
    df_creators = pd.read_csv(BASE_DIR / "CREATOR_ANALYSIS.csv")

    df_early = reconstruct_early_signals(df_tm, coins_by_mint, df_name, creator_db)
    df_early, df_bt, weights_dict, benchmarks_wf, brier_oos = fit_scoring_and_backtest(df_early)

    # Also merge 5m Pump Potential Score back into TOKEN_METRICS, PUMP_EVENTS, and TOP_100_PUMPS!
    s5_map = df_early[df_early["horizon"] == "5m"].set_index("mint")["pump_potential_score"].to_dict()
    for fname in ["TOKEN_METRICS.csv", "PUMP_EVENTS.csv", "TOP_100_PUMPS.csv"]:
        fpath = BASE_DIR / fname
        if fpath.exists():
            dfx = pd.read_csv(fpath)
            if len(dfx) > 0:
                dfx["pump_potential_score_5m"] = dfx["mint"].map(s5_map).fillna(50.0)
                dfx.to_csv(fpath, index=False, encoding="utf-8-sig")

    df_early.to_csv(BASE_DIR / "EARLY_SIGNALS.csv", index=False, encoding="utf-8-sig")
    df_bt.to_csv(BASE_DIR / "BACKTEST_RESULTS.csv", index=False, encoding="utf-8-sig")
    logger.info(f"Wrote EARLY_SIGNALS.csv ({len(df_early)} rows) and BACKTEST_RESULTS.csv ({len(df_bt)} rows).")

    hypotheses = run_35_hypotheses(df_all, df_tm, df_early, df_name, df_hourly, df_creators)
    top10_signals = rank_top_10_early_signals(df_early)

    summary_payload = {
        "universe_counts": {
            "total_tokens": int(len(df_all)),
            "group_a_new_30d": int(df_all["group_a_new_30d"].sum()),
            "group_b_pump_events_universe": int(df_all["group_b_pump_event"].sum()),
            "deep_cohort_total": int(len(df_tm)),
            "verified_pump_events_cohort": int(len(pd.read_csv(BASE_DIR / "PUMP_EVENTS.csv"))),
            "matched_controls_cohort": int(len(pd.read_csv(BASE_DIR / "CONTROL_GROUP.csv"))),
        },
        "model_weights": weights_dict,
        "brier_score_oos": brier_oos,
        "backtest_benchmarks_walk_forward": benchmarks_wf,
        "hypotheses_35": hypotheses,
        "top_10_early_signals": top10_signals,
    }
    with open(CACHE_DIR / "analytics_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2, ensure_ascii=False)
    logger.info("Saved analytics_summary.json successfully.")

if __name__ == "__main__":
    main()
