"""
CORE TEMPORAL INTEGRITY, PRICE EXTRACTION, FIXED-HORIZON LABELING, AND CAUSAL HISTORY ENGINE (V2 — P0).

Enforces:
1. Strict candle boundary semantics: `closeTimeMs = openTimeMs + interval_ms`.
   A candle is NEVER visible to features or entry pricing unless `closeTimeMs <= signal_timestamp_ms`.
2. Interval separation: 1m, 15m, and 4h candles are NEVER merged without explicit closeTimeMs validation.
3. Hard leakage invariant: `data_max_timestamp_ms <= signal_timestamp_ms` for every generated signal.
4. Fixed-horizon labels (`1h`, `4h`, `24h`) with explicit right-censoring (`censored` / `unknown` -> NaN, never 0)
   and strict separation of:
   - Category 1: Theoretical max single-tick potential (`max_potential_mult`),
   - Category 2: Reliable market price change (`reliable_market_mult` & terminal `ret_pct`),
   - Category 3: Position-size realizable growth (`realizable_mult_pos250`) accounting for AMM/curve depth & fees.
5. Causal historical creator & wallet scoring gated strictly by `label_available_at_ms < signal_timestamp_ms`.
"""
import math
import json
from dataclasses import dataclass
from typing import Optional
import numpy as np

from config_v2 import INTERVAL_DURATION_MS, CONFIRMED_TECHNICAL_ADDRESSES

def candle_close_time_ms(bar: dict, res: str) -> int:
    return int(bar["openTimeMs"]) + INTERVAL_DURATION_MS[res]

def filter_closed_candles_before(candles: list, res: str, cutoff_ms: int) -> list:
    """Returns ONLY candles whose entire interval has closed at or before cutoff_ms."""
    dur = INTERVAL_DURATION_MS[res]
    out = []
    for b in candles:
        ot = int(b.get("openTimeMs") or 0)
        if ot > 0 and (ot + dur) <= cutoff_ms:
            out.append(b)
    return out

def filter_candles_strictly_inside_horizon(candles: list, res: str, start_ms: int, end_ms: int) -> list:
    """
    Returns ONLY candles that opened at/after start_ms AND closed at/before end_ms.
    Prevents a 4h candle opened at 12:05 (closing at 16:05) from leaking 16:05 prices into a 1h horizon ending at 13:05!
    """
    dur = INTERVAL_DURATION_MS[res]
    out = []
    for b in candles:
        ot = int(b.get("openTimeMs") or 0)
        ct = ot + dur
        if ot >= start_ms and ct <= end_ms:
            out.append(b)
    return out

def get_causal_entry_price(
    trades: list,
    candles_1m: list,
    created_ts_ms: int,
    signal_ts_ms: int,
    sol_price_usd: float
) -> dict:
    """
    Determines entry price at `signal_ts_ms` strictly from data at or before `signal_ts_ms`.
    Never uses any trade or candle closing after `signal_ts_ms`.
    """
    init_curve_px = (27.96 * max(sol_price_usd, 10.0)) / 1_000_000_000.0
    vis_trades = [
        tr for tr in trades
        if int(tr.get("blockTimeMs") or 0) <= signal_ts_ms and float(tr.get("priceUsd") or 0) > 0
    ]
    reliable_vis = [
        tr for tr in vis_trades
        if float(tr.get("valueUsd") or 0) >= 5.0 or float(tr.get("valueNative") or 0) >= 0.05
    ]
    closed_1m = filter_closed_candles_before(candles_1m, "1m", signal_ts_ms)

    # Compare timestamp of latest reliable trade vs latest closed 1m bar (both <= signal_ts_ms!)
    best_px = init_curve_px
    px_ts = created_ts_ms
    px_source = "initial_bonding_curve_reserve"

    if reliable_vis:
        last_tr = reliable_vis[-1]
        best_px = float(last_tr["priceUsd"])
        px_ts = int(last_tr["blockTimeMs"])
        px_source = "last_reliable_trade_pre_signal"
    elif vis_trades:
        last_tr = vis_trades[-1]
        best_px = float(last_tr["priceUsd"])
        px_ts = int(last_tr["blockTimeMs"])
        px_source = "last_small_trade_pre_signal"

    if closed_1m:
        last_b = closed_1m[-1]
        b_close_ts = candle_close_time_ms(last_b, "1m")
        if b_close_ts > px_ts and float(last_b.get("close") or 0) > 0:
            best_px = float(last_b["close"])
            px_ts = b_close_ts
            px_source = "last_closed_1m_candle_pre_signal"

    assert px_ts <= signal_ts_ms, f"LEAKAGE DETECTED: price_timestamp {px_ts} > signal_timestamp {signal_ts_ms}"
    return {
        "entry_price_usd": max(best_px, 1e-11),
        "price_timestamp_ms": px_ts,
        "price_source": px_source,
        "init_curve_price_usd": init_curve_px,
        "has_pre_signal_trade": int(len(vis_trades) > 0),
    }

def compute_realizable_roundtrip_multiple(
    entry_market_px: float,
    exit_market_px: float,
    entry_liq_usd: float,
    exit_liq_usd: float,
    position_usd: float = 250.0,
    fee_rate_one_way: float = 0.010,
    priority_fee_usd_one_way: float = 0.35
) -> float:
    """
    Computes position-size-adjusted realizable multiple (Category 3) for a `position_usd` order
    on a constant-product curve/pool, accounting for:
    - Entry fee + priority fee + entry price impact against one-side pool depth (0.5 * entry_liq_usd)
    - Exit price impact against one-side pool depth at exit (0.5 * exit_liq_usd) + exit fee + priority fee.
    """
    if position_usd <= 0 or entry_market_px <= 0:
        return 0.0
    net_in = max(0.0, position_usd * (1.0 - fee_rate_one_way) - priority_fee_usd_one_way)
    depth_in = max(150.0, 0.5 * entry_liq_usd)
    # Effective entry execution price rises by (1 + net_in / depth_in)
    eff_entry_px = entry_market_px * (1.0 + net_in / depth_in)
    tokens_acquired = net_in / eff_entry_px

    gross_mark_exit_usd = tokens_acquired * max(0.0, exit_market_px)
    depth_out = max(100.0, 0.5 * exit_liq_usd)
    # Selling into AMM pool receives gross_mark_exit_usd / (1 + gross_mark_exit_usd / depth_out)
    realized_before_fee = gross_mark_exit_usd / (1.0 + gross_mark_exit_usd / depth_out)
    net_out_usd = max(0.0, realized_before_fee * (1.0 - fee_rate_one_way) - priority_fee_usd_one_way)
    return round(net_out_usd / position_usd, 4)

def compute_fixed_horizon_labels(
    signal_ts_ms: int,
    entry_price_usd: float,
    entry_liq_usd: float,
    sol_price_usd: float,
    collection_ts_ms: int,
    api_ok: int,
    trades: list,
    candles_1m: list,
    candles_15m: list,
    candles_4h: list,
) -> dict:
    """
    Computes independent fixed-horizon labels for 1h, 4h, and 24h:
    - Marks `status_{h} = "censored"` (all labels NaN) if `collection_ts_ms < signal_ts_ms + horizon_ms`.
    - Marks `status_{h} = "unknown"` (all labels NaN) if `api_ok == 0`.
    - Separates:
      1) `max_potential_mult_{h}` (raw tick/wick high),
      2) `reliable_market_mult_{h}` & `terminal_ret_{h}_pct` (volume-verified market price),
      3) `realizable_mult_{h}_pos250` (net realizable multiple for $250 position after slippage & fees).
    """
    horizons_spec = [
        ("1h", 3_600_000, [2, 3]),
        ("4h", 14_400_000, [2, 3, 5]),
        ("24h", 86_400_000, [2, 3, 5, 10]),
    ]
    init_curve_px = (27.96 * max(sol_price_usd, 10.0)) / 1_000_000_000.0
    out = {}

    for h_name, h_ms, mult_thresholds in horizons_spec:
        end_ms = signal_ts_ms + h_ms
        if not api_ok:
            out[f"status_{h_name}"] = "unknown"
            is_valid = False
        elif collection_ts_ms < end_ms:
            out[f"status_{h_name}"] = "censored"
            is_valid = False
        else:
            out[f"status_{h_name}"] = "complete"
            is_valid = True

        if not is_valid:
            out[f"max_potential_mult_{h_name}"] = np.nan
            out[f"reliable_market_mult_{h_name}"] = np.nan
            out[f"realizable_mult_{h_name}_pos250"] = np.nan
            out[f"max_drawdown_{h_name}_pct"] = np.nan
            out[f"terminal_ret_{h_name}_pct"] = np.nan
            for k in mult_thresholds:
                out[f"hit_{k}x_{h_name}"] = np.nan
                out[f"time_to_{k}x_{h_name}_sec"] = np.nan
            continue

        # Strictly in-window trades: signal_ts_ms < blockTimeMs <= end_ms
        h_trades = [
            tr for tr in trades
            if signal_ts_ms < int(tr.get("blockTimeMs") or 0) <= end_ms and float(tr.get("priceUsd") or 0) > 0
        ]
        # Strictly in-window closed candles (each resolution checked via its own exact closeTimeMs!)
        b_1m = filter_candles_strictly_inside_horizon(candles_1m, "1m", signal_ts_ms, end_ms)
        b_15m = filter_candles_strictly_inside_horizon(candles_15m, "15m", signal_ts_ms, end_ms)
        b_4h = filter_candles_strictly_inside_horizon(candles_4h, "4h", signal_ts_ms, end_ms) if h_ms >= 14_400_000 else []

        # Chronological sequence of verified market price observations `(timestamp_ms, reliable_px, raw_high_px, raw_low_px)`
        events = []
        for tr in h_trades:
            tms = int(tr["blockTimeMs"])
            px = float(tr["priceUsd"])
            val_u = float(tr.get("valueUsd") or 0.0)
            is_rel = val_u >= 15.0
            events.append((tms, px if is_rel else None, px, px))

        # Use finest available candle stream, extending later coverage via 15m / 4h bars whose close exceeds finer coverage
        fine_bars = [(b, "1m") for b in b_1m]
        last_1m_close = candle_close_time_ms(b_1m[-1], "1m") if b_1m else signal_ts_ms
        for b in b_15m:
            if candle_close_time_ms(b, "15m") > last_1m_close:
                fine_bars.append((b, "15m"))
        last_15m_close = max([last_1m_close] + [candle_close_time_ms(b, "15m") for b in b_15m])
        for b in b_4h:
            if candle_close_time_ms(b, "4h") > last_15m_close:
                fine_bars.append((b, "4h"))

        for b, res_lbl in fine_bars:
            ct = candle_close_time_ms(b, res_lbl)
            hi = float(b.get("high") or 0.0)
            lo = float(b.get("low") or 0.0)
            cl = float(b.get("close") or 0.0)
            vol = float(b.get("volumeUsd") or 0.0)
            nt = int(b.get("trades") or 0)
            rel_px = max(cl, 0.5 * (hi + cl)) if (vol >= 25.0 or nt >= 2) and cl > 0 else (cl if cl > 0 and vol >= 10.0 else None)
            events.append((ct, rel_px, hi if hi > 0 else cl, lo if lo > 0 else cl))

        events.sort(key=lambda x: x[0])

        max_raw_px = entry_price_usd
        max_rel_px = entry_price_usd
        min_low_px = entry_price_usd
        terminal_px = entry_price_usd
        time_to_k = {k: np.nan for k in mult_thresholds}

        for ev_ts, rel_p, hi_p, lo_p in events:
            if hi_p and hi_p > max_raw_px:
                max_raw_px = hi_p
            if lo_p and 0 < lo_p < min_low_px:
                min_low_px = lo_p
            if rel_p is not None and rel_p > 0:
                terminal_px = rel_p
                if rel_p > max_rel_px:
                    max_rel_px = rel_p
                cur_mult = rel_p / entry_price_usd
                for k in mult_thresholds:
                    if cur_mult >= float(k) and np.isnan(time_to_k[k]):
                        time_to_k[k] = round((ev_ts - signal_ts_ms) / 1000.0, 1)
            elif hi_p and hi_p > 0:
                # Even if low-volume sell tick dropped price, update terminal mark if lower
                if hi_p < terminal_px:
                    terminal_px = hi_p

        pot_mult = round(max(1.0, max_raw_px / entry_price_usd), 4)
        rel_mult = round(max(1.0, max_rel_px / entry_price_usd), 4)
        peak_liq_est = max(200.0, 60.0 * sol_price_usd * math.sqrt(max(0.2, max_rel_px / max(init_curve_px, 1e-11))))
        realizable_mult = compute_realizable_roundtrip_multiple(
            entry_price_usd, max_rel_px, entry_liq_usd, peak_liq_est, position_usd=250.0
        )
        dd_pct = round(max(0.0, (1.0 - (min_low_px / entry_price_usd)) * 100.0), 2)
        term_ret_pct = round(((terminal_px / entry_price_usd) - 1.0) * 100.0, 2)

        out[f"max_potential_mult_{h_name}"] = pot_mult
        out[f"reliable_market_mult_{h_name}"] = rel_mult
        out[f"realizable_mult_{h_name}_pos250"] = realizable_mult
        out[f"max_drawdown_{h_name}_pct"] = dd_pct
        out[f"terminal_ret_{h_name}_pct"] = term_ret_pct
        for k in mult_thresholds:
            # Binary target strictly uses RELIABLE MARKET MULTIPLE within the fixed horizon!
            out[f"hit_{k}x_{h_name}"] = int(rel_mult >= float(k))
            out[f"time_to_{k}x_{h_name}_sec"] = time_to_k[k]

    return out

class CausalHistoryTracker:
    """
    Tracks historical creator and wallet performance WITHOUT look-ahead leakage.
    Every historical observation carries `label_available_at_ms`.
    A record is ONLY eligible to inform a signal at `signal_ts_ms` if:
        record.label_available_at_ms < signal_ts_ms
    """
    def __init__(self):
        # creator -> list of (created_ts_ms, label_available_at_ms, is_winner_int)
        self.creator_records = {}
        # wallet -> list of (entry_ts_ms, label_available_at_ms, is_winner_int)
        self.wallet_records = {}

    def register_creator_token(self, creator: str, created_ts_ms: int, label_available_at_ms: int, is_winner: int):
        if not creator:
            return
        assert label_available_at_ms > created_ts_ms, "label_available_at_ms must be strictly after created_ts_ms"
        self.creator_records.setdefault(creator, []).append((int(created_ts_ms), int(label_available_at_ms), int(is_winner)))

    def register_wallet_entry(self, wallet: str, entry_ts_ms: int, label_available_at_ms: int, is_winner: int):
        if not wallet or wallet in CONFIRMED_TECHNICAL_ADDRESSES:
            return
        assert label_available_at_ms > entry_ts_ms, "label_available_at_ms must be strictly after entry_ts_ms"
        self.wallet_records.setdefault(wallet, []).append((int(entry_ts_ms), int(label_available_at_ms), int(is_winner)))

    def get_creator_stats_at(self, creator: str, signal_ts_ms: int) -> dict:
        recs = self.creator_records.get(creator, [])
        # Prior launches known to exist before signal_ts_ms
        prior_launched = [r for r in recs if r[0] < signal_ts_ms - 1000]
        # Prior launches whose outcome evaluation window has COMPLETELY FINISHED before signal_ts_ms!
        evaluated = [r for r in recs if r[1] < signal_ts_ms]
        max_used_ts = max([r[1] for r in evaluated] + [r[0] for r in prior_launched] + [0])
        wins = sum(r[2] for r in evaluated)
        n_eval = len(evaluated)
        win_rate = round(wins / n_eval, 4) if n_eval > 0 else 0.0
        return {
            "creator_prior_launches_count": len(prior_launched),
            "creator_evaluated_prior_count": n_eval,
            "creator_prior_wins": wins,
            "creator_prior_win_rate": win_rate,
            "max_history_ts_used": max_used_ts,
        }

    def get_smart_wallets_count_at(self, buyer_wallets: list, signal_ts_ms: int, min_eval_entries: int = 2, min_hit_rate: float = 0.35) -> dict:
        smart_cnt = 0
        max_used_ts = 0
        for w in set(buyer_wallets):
            recs = self.wallet_records.get(w, [])
            evaluated = [r for r in recs if r[1] < signal_ts_ms]
            if evaluated:
                max_used_ts = max(max_used_ts, max(r[1] for r in evaluated))
            if len(evaluated) >= min_eval_entries:
                hr = sum(r[2] for r in evaluated) / len(evaluated)
                if hr >= min_hit_rate:
                    smart_cnt += 1
        return {
            "causal_smart_wallets_in": smart_cnt,
            "max_wallet_history_ts_used": max_used_ts,
        }
