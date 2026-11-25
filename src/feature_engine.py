"""
UNIFIED FEATURE ENGINE (`src/feature_engine.py` — V2.1 P0):
THE SINGLE SHARED MODULE FOR:
  1. Training
  2. Validation
  3. Out-of-time (OOT) testing
  4. Paper trading
  5. Live inference

Enforces:
- Per-feature provenance (`value`, `source`, `acquired_at_ms`, `event_timestamp_ms`,
  `max_data_timestamp_ms`, `feature_available_at_ms`).
- Hard blocking condition: `feature_available_at_ms <= signal_timestamp_ms` and
  `max_data_timestamp_ms <= signal_timestamp_ms` on EVERY feature!
- No artificial substitution for unknown history (`"unknown"` / `"insufficient_history"` preserved in snapshot,
  never forcing `is_ticker_first_mover = 1`!).
- Strict supply validation: deduplicates trades, excludes all LP/pool/curve/burn/technical addresses,
  and marks `INVALID_SUPPLY_RECONSTRUCTION` if holder sum > 100% of effective supply, blocking invalid
  supply from model input!
"""
import json
import math
import re
from pathlib import Path
from collections import defaultdict, Counter
from typing import Optional

from config_v2_1 import (
    CONFIRMED_TECHNICAL_ADDRESSES,
    INTERVAL_MS,
    PUMPFUN_INIT_VIRTUAL_SOL,
    PUMPFUN_INIT_VIRTUAL_TOKENS,
    PUMPFUN_INIT_K,
)
from state_trackers_v2_1 import UnifiedStateBundle

class FeatureLeakageError(RuntimeError):
    """Raised immediately if any feature violates `feature_available_at_ms <= signal_timestamp_ms`."""
    pass

NARRATIVE_PATTERNS = [
    ("AI_Agents_Tech", r"\b(ai|agent|gpt|claude|llm|bot|neural|sentient|autonom|solana\.ai|mcp|truth|terminal|cyber|quantum|code|dev|algo|deepseek|openai|grok)\b"),
    ("Absurd_Toilet_Humor", r"\b(fart|poop|pee|shit|butt|ass|dick|balls|toilet|piss|burp|goon|brainrot|skibidi|autism|schizo)\b"),
    ("Animals_Pets", r"\b(dog|cat|pepe|frog|shib|inu|goat|pnut|squirrel|bear|bull|ape|monkey|pengu|bird|duck|fish|shark|whale|hamster|moo|hippo|capy|seal|otter|panda|wolf|fox|kitty|pup)\b"),
    ("Politics_Macro", r"\b(trump|biden|elon|musk|maga|doge|gov|president|senate|vote|america|usa|china|russia|war|tariff|fed|powell|tax|sec)\b"),
    ("Platform_Meta_Pump", r"\b(mayhem|polymarket|pump|pumpswap|boost|privy|sui|raydium|bonding|koth|trench|trenches|runner|cabal|bundle)\b"),
    ("Internet_Memes_Culture", r"\b(chad|wojak|pepe|kek|giga|sigma|chill|guy|doge|troll|npc|based|cope|wagmi|hodl|fomo|meme|viral|bro|aura|rizz)\b"),
    ("Finance_Trading_Wealth", r"\b(quant|alpha|rich|million|billion|money|cash|gold|dollar|usd|bank|yield|hedge|fund|stock|short|long|bullish|candle|moon)\b"),
]

def classify_token_narrative(name: str, symbol: str, desc: str) -> str:
    txt = f"{name or ''} {symbol or ''} {desc or ''}".lower()
    for cat, pat in NARRATIVE_PATTERNS:
        if re.search(pat, txt):
            return cat
    return "General_Novelty_Other"

def compute_lexical_strength(name: str, symbol: str) -> float:
    n_c = (name or "").strip()
    s_c = re.sub(r"[^a-zA-Z]", "", (symbol or "").lower())
    vow = sum(1 for c in s_c if c in "aeiouy") / max(1, len(s_c))
    pron = max(0.0, 1.0 - abs(vow - 0.42) * 1.8)
    words = [w for w in re.split(r"\s+", n_c) if w]
    return round(min(1.0, max(0.05, 0.5 * pron + 0.5 * (1.0 if 1 <= len(words) <= 3 else 0.4))), 4)

# Canonical ordered list of numeric model inputs (grouped cleanly for 8-component Ablation Study in Section 8!)
MODEL_FEATURE_GROUPS_V2_1 = {
    "buyer_velocity": ["independent_buyer_velocity", "unique_buyers_cum", "scale_in_buyers_ratio"],
    "buyer_acceleration": ["buyer_acceleration_ratio", "tx_acceleration_ratio"],
    "order_absorption": ["buy_sell_log_ratio", "dip_absorption_ratio", "vol_to_mcap_ratio"],
    "wallet_intelligence": ["smart_wallets_count_num", "wallet_history_known_flag"],
    "creator_history": ["creator_win_rate_num", "creator_history_known_flag", "creator_prior_launches_log", "creator_dumped_flag"],
    "insider_risk": ["same_slot_bundle_wallets_at_T", "mayhem_enabled"],
    "supply_concentration": ["top5_human_supply_pct_num", "concentration_change_pct_num", "supply_valid_flag"],
    "social_momentum": ["has_launch_social_links", "twitter_is_direct_post_or_handle"],
    "narrative_strength": ["narrative_lexical_score", "ticker_first_mover_num", "ticker_history_known_flag"],
    "market_context": ["sol_ret_1h_pct_num", "sol_ret_24h_pct_num"],
}
ALL_MODEL_FEATURES_V2_1 = [col for grp in MODEL_FEATURE_GROUPS_V2_1.values() for col in grp]

def make_feature_record(
    value,
    model_num: float,
    source: str,
    acquired_at_ms: int,
    event_ts_ms: int,
    max_data_ts_ms: int,
    available_at_ms: int,
    status: str = "ok"
) -> dict:
    return {
        "value": value,
        "model_num": round(float(model_num), 6),
        "source": source,
        "acquired_at_ms": int(acquired_at_ms),
        "event_timestamp_ms": int(event_ts_ms),
        "max_data_timestamp_ms": int(max_data_ts_ms),
        "feature_available_at_ms": int(available_at_ms),
        "status": status,
    }

def validate_snapshot_no_leakage(snapshot: dict) -> None:
    sig_ts = int(snapshot["signal_timestamp_ms"])
    for fname, frec in snapshot["features"].items():
        if int(frec["feature_available_at_ms"]) > sig_ts:
            raise FeatureLeakageError(
                f"BLOCKED SIGNAL: Feature '{fname}' has feature_available_at_ms={frec['feature_available_at_ms']} > signal_ts={sig_ts}"
            )
        if int(frec["max_data_timestamp_ms"]) > sig_ts:
            raise FeatureLeakageError(
                f"BLOCKED SIGNAL: Feature '{fname}' has max_data_timestamp_ms={frec['max_data_timestamp_ms']} > signal_ts={sig_ts}"
            )
        if int(frec["event_timestamp_ms"]) > sig_ts:
            raise FeatureLeakageError(
                f"BLOCKED SIGNAL: Feature '{fname}' has event_timestamp_ms={frec['event_timestamp_ms']} > signal_ts={sig_ts}"
            )

def deduplicate_and_filter_trades_before(trades: list, cutoff_ms: int) -> list:
    """
    Deduplicates trades strictly by `(txId, legIndex, eventIndex)` so no swap is ever counted twice,
    and rejects any trade with `blockTimeMs > cutoff_ms`!
    """
    seen_keys = set()
    vis = []
    for tr in trades:
        tms = int(tr.get("blockTimeMs") or 0)
        if tms <= 0 or tms > cutoff_ms:
            continue
        dedup_k = (tr.get("txId") or tr.get("ordinalKey") or "", int(tr.get("legIndex") or 0), int(tr.get("eventIndex") or 0))
        if dedup_k in seen_keys:
            continue
        seen_keys.add(dedup_k)
        vis.append(tr)
    vis.sort(key=lambda x: (int(x.get("blockTimeMs") or 0), int(x.get("blockId") or 0), int(x.get("txIndex") or 0), int(x.get("eventIndex") or 0)))
    return vis

def build_token_technical_set(coin: dict, trades: list) -> set:
    """Collects all confirmed technical, program, burn, curve, and AMM pool addresses for a token."""
    tech = set(CONFIRMED_TECHNICAL_ADDRESSES.keys())
    for fld in ["bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address", "market_id"]:
        if coin.get(fld):
            tech.add(str(coin[fld]))
    for tr in trades:
        pool_addr = (tr.get("pool") or {}).get("address")
        if pool_addr:
            tech.add(str(pool_addr))
    return tech

def get_token_supply_at_birth(coin: dict) -> float:
    dec = int(coin.get("base_decimals") or 6)
    raw_sup = coin.get("total_supply")
    mayhem_on = coin.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(coin.get("mayhem"), dict) and bool(coin["mayhem"].get("state")))
    if raw_sup is not None and float(raw_sup) > 0:
        sup = float(raw_sup) / (10 ** dec)
        if sup >= 1e6:
            return sup
    return 2_000_000_000.0 if mayhem_on else 1_000_000_000.0


class UnifiedFeatureEngine:
    """
    Single unified feature engine shared identically by Training, Validation, OOT, Paper Trading, and Live.
    """
    def __init__(self, save_snapshots_dir: Optional[Path] = None):
        self.save_snapshots_dir = save_snapshots_dir

    def compute_snapshot(
        self,
        coin: dict,
        trades: list,
        candles_1m: list,
        signal_ts_ms: int,
        state: UnifiedStateBundle,
        mode: str = "training",
        acquired_at_ms: Optional[int] = None,
        persist_json: bool = False,
    ) -> dict:
        mint = coin["mint"]
        cts = int(coin.get("created_timestamp") or 0)
        if cts <= 0 or cts > signal_ts_ms:
            raise FeatureLeakageError(f"Invalid created_timestamp {cts} vs signal_ts {signal_ts_ms} for {mint}")

        acq_ms = int(acquired_at_ms) if acquired_at_ms is not None else int(signal_ts_ms)
        acq_ms = min(acq_ms, int(signal_ts_ms))

        vis_trades = deduplicate_and_filter_trades_before(trades, signal_ts_ms)
        # Filter 1m candles strictly closed at or before signal_ts_ms (`openTimeMs + 60_000 <= signal_ts_ms`)
        closed_1m = [
            b for b in candles_1m
            if int(b.get("openTimeMs") or 0) > 0 and (int(b["openTimeMs"]) + INTERVAL_MS["1m"]) <= signal_ts_ms
        ]
        closed_1m.sort(key=lambda b: int(b["openTimeMs"]))

        # Extract latest on-chain SOL spot quote tick <= signal_ts_ms if present
        spot_tick = None
        for tr in reversed(vis_trades):
            qp = float(tr.get("quotePriceUsd") or 0.0)
            if qp > 5.0:
                spot_tick = (int(tr["blockTimeMs"]), qp)
                break

        # 1. Market Context (SOL) — strictly closed hourly bars + causal spot tick!
        sol_ctx = state.market.query_sol_at(signal_ts_ms, onchain_spot_tick=spot_tick)
        sol_px_num = float(sol_ctx["sol_price_usd"]) if isinstance(sol_ctx["sol_price_usd"], (int, float)) else 70.0

        # 2. Causal Entry Price & Historical Bonding-Curve Reserve State at `signal_ts_ms`
        init_curve_px_usd = (PUMPFUN_INIT_VIRTUAL_SOL * sol_px_num) / PUMPFUN_INIT_VIRTUAL_TOKENS
        entry_px_usd = init_curve_px_usd
        entry_px_quote_sol = PUMPFUN_INIT_VIRTUAL_SOL / PUMPFUN_INIT_VIRTUAL_TOKENS
        px_ts = cts
        px_src = "genesis_bonding_curve_reserve"
        last_venue = "pump"

        rel_trades = [
            tr for tr in vis_trades
            if (float(tr.get("valueUsd") or 0) >= 5.0 or float(tr.get("valueNative") or 0) >= 0.05)
            and (float(tr.get("priceUsd") or 0) > 0 or float(tr.get("priceQuote") or 0) > 0)
        ]
        if rel_trades:
            lt = rel_trades[-1]
            pq = float(lt.get("priceQuote") or 0.0)
            pu = float(lt.get("priceUsd") or 0.0)
            entry_px_usd = pu if pu > 0 else (pq * sol_px_num)
            entry_px_quote_sol = pq if pq > 0 else (entry_px_usd / max(sol_px_num, 1.0))
            px_ts = int(lt["blockTimeMs"])
            px_src = "last_reliable_swap_pre_signal"
            last_venue = lt.get("venue") or "pump"
        elif vis_trades:
            lt = vis_trades[-1]
            pq = float(lt.get("priceQuote") or 0.0)
            pu = float(lt.get("priceUsd") or 0.0)
            if pu > 0 or pq > 0:
                entry_px_usd = pu if pu > 0 else (pq * sol_px_num)
                entry_px_quote_sol = pq if pq > 0 else (entry_px_usd / max(sol_px_num, 1.0))
                px_ts = int(lt["blockTimeMs"])
                px_src = "last_swap_pre_signal"
                last_venue = lt.get("venue") or "pump"

        if closed_1m:
            lb = closed_1m[-1]
            b_ct = int(lb["openTimeMs"]) + INTERVAL_MS["1m"]
            if b_ct > px_ts and float(lb.get("close") or 0) > 0:
                entry_px_usd = float(lb["close"])
                entry_px_quote_sol = entry_px_usd / max(sol_px_num, 1.0)
                px_ts = b_ct
                px_src = "last_closed_1m_candle_pre_signal"

        # Recover exact bonding-curve virtual reserves at signal_ts_ms if still on `pump` bonding curve!
        if last_venue == "pump" and entry_px_quote_sol > 0:
            v_sol_reserve = math.sqrt(PUMPFUN_INIT_K * entry_px_quote_sol)
            v_tok_reserve = math.sqrt(PUMPFUN_INIT_K / entry_px_quote_sol)
            reserve_source = "EXACT_BONDING_CURVE_RESERVES"
            liq_usd = round(2.0 * v_sol_reserve * sol_px_num, 2)
        else:
            # Post-migration AMM pool where historical LP add/remove reserves are not in swap tape
            v_sol_reserve = max(85.0, PUMPFUN_INIT_VIRTUAL_SOL * math.sqrt(max(1.0, entry_px_usd / max(init_curve_px_usd, 1e-11))))
            v_tok_reserve = v_sol_reserve / max(entry_px_quote_sol, 1e-12)
            reserve_source = "ESTIMATED_AMM_RESERVES"
            liq_usd = round(2.0 * v_sol_reserve * sol_px_num, 2)

        # 3. Order Flow, Buyer Velocity, Acceleration & Supply Ledger up to `signal_ts_ms`
        tok_tech = build_token_technical_set(coin, vis_trades)
        creator = coin.get("creator") or ""
        mayhem_on = int(coin.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(coin.get("mayhem"), dict) and bool(coin["mayhem"].get("state"))))
        eff_supply = get_token_supply_at_birth(coin)

        h_sec = max(1.0, (signal_ts_ms - cts) / 1000.0)
        h_min = h_sec / 60.0
        max_tr_ts = max([int(tr["blockTimeMs"]) for tr in vis_trades], default=cts)

        # Same-slot bundle check in first 4s
        slot_buyers = defaultdict(list)
        for tr in vis_trades:
            if tr.get("side") == "buy" and int(tr["blockTimeMs"]) <= cts + 4000:
                w = (tr.get("trader") or {}).get("address") or ""
                if w and w not in tok_tech:
                    slot_buyers[int(tr.get("blockId") or 0)].append((int(tr.get("txIndex") or 0), w))
        bundle_set = set()
        for blk, lst in slot_buyers.items():
            lst.sort()
            uw = list(dict.fromkeys([w for _, w in lst]))
            if len(uw) >= 2:
                gaps = [lst[k+1][0] - lst[k][0] for k in range(len(lst)-1)]
                if gaps and max(gaps) <= 3:
                    bundle_set.update(uw)

        buyers_first_s = {}
        indep_buyers = set()
        buy_cnt_w = Counter()
        w_bal = defaultdict(float)
        w_bal_15s = defaultdict(float)
        buy_usd = 0.0
        sell_usd = 0.0
        fh_buyers = 0
        sh_buyers = 0
        fh_tx = 0
        sh_tx = 0
        cr_bought = 0.0
        cr_sold = 0.0

        peak_px = init_curve_px_usd
        in_dip = False
        dip_b_usd = 0.0
        dip_s_usd = 0.0

        for tr in vis_trades:
            tms = int(tr["blockTimeMs"])
            rel_s = max(0.0, (tms - cts) / 1000.0)
            w = (tr.get("trader") or {}).get("address") or ""
            side = tr.get("side")
            vu = float(tr.get("valueUsd") or 0.0)
            px = float(tr.get("priceUsd") or 0.0)

            if px > peak_px:
                peak_px = px
            elif peak_px >= init_curve_px_usd * 1.15 and 0 < px <= peak_px * 0.88:
                in_dip = True

            if rel_s <= h_sec * 0.5:
                fh_tx += 1
            else:
                sh_tx += 1

            if w and w not in tok_tech:
                dec = int((tr.get("baseAmount") or {}).get("decimals") or 6)
                qty = float((tr.get("baseAmount") or {}).get("raw") or 0.0) / (10 ** dec)
                if side == "buy":
                    buy_usd += vu
                    buy_cnt_w[w] += 1
                    w_bal[w] += qty
                    if rel_s <= 15.0:
                        w_bal_15s[w] += qty
                    if w == creator:
                        cr_bought += qty
                    if in_dip:
                        dip_b_usd += vu
                    if w not in buyers_first_s:
                        buyers_first_s[w] = rel_s
                        if rel_s <= h_sec * 0.5:
                            fh_buyers += 1
                        else:
                            sh_buyers += 1
                        if w not in bundle_set and w != creator:
                            indep_buyers.add(w)
                elif side == "sell":
                    sell_usd += vu
                    w_bal[w] = max(0.0, w_bal[w] - qty)
                    if rel_s <= 15.0:
                        w_bal_15s[w] = max(0.0, w_bal_15s[w] - qty)
                    if w == creator:
                        cr_sold += qty
                    if in_dip:
                        dip_s_usd += vu

        # STRICT SUPPLY INVARIANT CHECK (Section 6: Fix >100% holder sum bug!)
        pos_bals = sorted([v for k, v in w_bal.items() if k not in tok_tech and v > 0], reverse=True)
        pos_bals_15s = sorted([v for k, v in w_bal_15s.items() if k not in tok_tech and v > 0], reverse=True)
        sum_human_bals = sum(pos_bals)

        if sum_human_bals > eff_supply * 1.0001 or eff_supply <= 0:
            supply_status = "INVALID_SUPPLY_RECONSTRUCTION"
            supply_valid_flag = 0.0
            top5_val = "INVALID_SUPPLY_RECONSTRUCTION"
            top5_num = 0.0
            conc_chg_val = "INVALID_SUPPLY_RECONSTRUCTION"
            conc_chg_num = 0.0
        else:
            supply_status = "ok"
            supply_valid_flag = 1.0
            top5_pct = round((sum(pos_bals[:5]) / eff_supply) * 100.0, 4)
            top5_15s_pct = round((sum(pos_bals_15s[:5]) / eff_supply) * 100.0, 4)
            top5_val = top5_pct
            top5_num = top5_pct
            conc_chg_val = round(top5_pct - top5_15s_pct, 4)
            conc_chg_num = conc_chg_val

        # 4. Query Unified State Trackers (Creator, Wallet, Ticker/Narrative)
        narr_cat = classify_token_narrative(coin.get("name"), coin.get("symbol"), coin.get("description"))
        lex_score = compute_lexical_strength(coin.get("name"), coin.get("symbol"))

        cr_q = state.creators.query_at(creator, mint, signal_ts_ms)
        wal_q = state.wallets.query_wallets_at(list(buyers_first_s.keys()), mint, signal_ts_ms)
        tkr_q = state.tickers.query_at(cts, mint, coin.get("symbol") or "", narr_cat, signal_ts_ms)

        n_u = len(buyers_first_s)
        n_ind = len(indep_buyers)
        ind_vel = round(n_ind / h_min, 4)
        scale_in = round(sum(1 for w, c in buy_cnt_w.items() if c >= 2) / max(1, n_u), 4)
        b_accel = round((sh_buyers + 1.0) / (fh_buyers + 1.0), 4)
        tx_accel = round((sh_tx + 1.5) / (fh_tx + 1.5), 4)
        bs_log = round(math.log1p(buy_usd + 5.0) - math.log1p(sell_usd + 5.0), 4)
        dip_abs = round(min(10.0, (dip_b_usd + 5.0) / (dip_s_usd + 5.0)), 4) if in_dip else 1.0
        mcap_T = entry_px_usd * eff_supply
        vol_mcap = round(min(5.0, (buy_usd + sell_usd) / max(500.0, mcap_T)), 4)
        cr_dumped = int(cr_sold > 0 and cr_sold >= 0.40 * max(cr_bought, 1.0))

        tw = str(coin.get("twitter") or "").strip()
        has_soc = int(bool(tw) or bool(coin.get("website")))
        tw_direct = int(bool(tw) and "/i/communities/" not in tw)

        # Build Per-Feature Provenance Dictionary (every single feature carries its own timestamps & status!)
        f_map = {
            "independent_buyer_velocity": make_feature_record(ind_vel, ind_vel, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "unique_buyers_cum": make_feature_record(n_u, float(n_u), "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "scale_in_buyers_ratio": make_feature_record(scale_in, scale_in, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "buyer_acceleration_ratio": make_feature_record(b_accel, b_accel, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "tx_acceleration_ratio": make_feature_record(tx_accel, tx_accel, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "buy_sell_log_ratio": make_feature_record(bs_log, bs_log, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "dip_absorption_ratio": make_feature_record(dip_abs, dip_abs, "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "vol_to_mcap_ratio": make_feature_record(vol_mcap, vol_mcap, "pumpfun_swap_tape", acq_ms, max_tr_ts, max(max_tr_ts, px_ts), max(max_tr_ts, px_ts)),

            # Wallet Intelligence (never fakes unknown history!)
            "smart_wallets_count_num": make_feature_record(
                wal_q["smart_wallets_count"],
                float(wal_q["smart_wallets_count"]) if isinstance(wal_q["smart_wallets_count"], int) else 0.0,
                "wallet_history_tracker", acq_ms, wal_q["event_ts_ms"], max(max_tr_ts, wal_q["available_at_ms"]), max(max_tr_ts, wal_q["available_at_ms"]),
                status=wal_q["status"]
            ),
            "wallet_history_known_flag": make_feature_record(
                1 if wal_q["status"] == "ok" else 0,
                1.0 if wal_q["status"] == "ok" else 0.0,
                "wallet_history_tracker", acq_ms, wal_q["event_ts_ms"], wal_q["available_at_ms"], wal_q["available_at_ms"],
                status=wal_q["status"]
            ),

            # Creator History (strictly `label_available_at <= signal_ts_ms`; `"unknown"` if not evaluated!)
            "creator_win_rate_num": make_feature_record(
                cr_q["win_rate"],
                float(cr_q["win_rate"]) if isinstance(cr_q["win_rate"], (int, float)) else 0.0,
                "creator_history_tracker", acq_ms, cr_q["event_ts_ms"], cr_q["available_at_ms"], cr_q["available_at_ms"],
                status=cr_q["status"]
            ),
            "creator_history_known_flag": make_feature_record(
                1 if cr_q["status"] == "ok" else 0,
                1.0 if cr_q["status"] == "ok" else 0.0,
                "creator_history_tracker", acq_ms, cr_q["event_ts_ms"], cr_q["available_at_ms"], cr_q["available_at_ms"],
                status=cr_q["status"]
            ),
            "creator_prior_launches_log": make_feature_record(
                cr_q["prior_launches_count"],
                round(math.log1p(cr_q["prior_launches_count"]), 4),
                "creator_history_tracker", acq_ms, cr_q["event_ts_ms"], cr_q["available_at_ms"], cr_q["available_at_ms"],
                status="ok" if cr_q["prior_launches_count"] > 0 else "unknown"
            ),
            "creator_dumped_flag": make_feature_record(cr_dumped, float(cr_dumped), "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),

            # Insider / Manipulation Microstructure
            "same_slot_bundle_wallets_at_T": make_feature_record(len(bundle_set), float(len(bundle_set)), "pumpfun_swap_tape", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts),
            "mayhem_enabled": make_feature_record(mayhem_on, float(mayhem_on), "token_init_metadata", acq_ms, cts, cts, cts),

            # Supply Concentration (blocks >100% INVALID_SUPPLY_RECONSTRUCTION!)
            "top5_human_supply_pct_num": make_feature_record(top5_val, top5_num, "ledger_supply_reconstructor", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts, status=supply_status),
            "concentration_change_pct_num": make_feature_record(conc_chg_val, conc_chg_num, "ledger_supply_reconstructor", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts, status=supply_status),
            "supply_valid_flag": make_feature_record(int(supply_valid_flag), supply_valid_flag, "ledger_supply_reconstructor", acq_ms, max_tr_ts, max_tr_ts, max_tr_ts, status=supply_status),

            # Launch Social Metadata (immutable from token init at `cts`)
            "has_launch_social_links": make_feature_record(has_soc, float(has_soc), "token_init_metadata", acq_ms, cts, cts, cts),
            "twitter_is_direct_post_or_handle": make_feature_record(tw_direct, float(tw_direct), "token_init_metadata", acq_ms, cts, cts, cts),

            # Narrative & Ticker History (NEVER forces `is_ticker_first_mover = 1`!)
            "narrative_lexical_score": make_feature_record(lex_score, lex_score, "token_init_metadata", acq_ms, cts, cts, cts),
            "ticker_first_mover_num": make_feature_record(
                tkr_q["is_ticker_first_mover"],
                float(tkr_q["is_ticker_first_mover"]) if isinstance(tkr_q["is_ticker_first_mover"], int) else 0.0,
                "ticker_narrative_tracker", acq_ms, max(cts, tkr_q["event_ts_ms"]), max(cts, tkr_q["available_at_ms"]), max(cts, tkr_q["available_at_ms"]),
                status=tkr_q["status"]
            ),
            "ticker_history_known_flag": make_feature_record(
                1 if tkr_q["status"] == "ok" else 0,
                1.0 if tkr_q["status"] == "ok" else 0.0,
                "ticker_narrative_tracker", acq_ms, max(cts, tkr_q["event_ts_ms"]), max(cts, tkr_q["available_at_ms"]), max(cts, tkr_q["available_at_ms"]),
                status=tkr_q["status"]
            ),

            # SOL Market Context (strictly closed bars!)
            "sol_ret_1h_pct_num": make_feature_record(
                sol_ctx["sol_ret_1h_pct"],
                float(sol_ctx["sol_ret_1h_pct"]) if isinstance(sol_ctx["sol_ret_1h_pct"], (int, float)) else 0.0,
                sol_ctx["sol_price_source"], acq_ms, sol_ctx["sol_price_event_ts_ms"], sol_ctx["sol_ret_available_at_ms"], sol_ctx["sol_ret_available_at_ms"],
                status=sol_ctx["status"]
            ),
            "sol_ret_24h_pct_num": make_feature_record(
                sol_ctx["sol_ret_24h_pct"],
                float(sol_ctx["sol_ret_24h_pct"]) if isinstance(sol_ctx["sol_ret_24h_pct"], (int, float)) else 0.0,
                sol_ctx["sol_price_source"], acq_ms, sol_ctx["sol_price_event_ts_ms"], sol_ctx["sol_ret_available_at_ms"], sol_ctx["sol_ret_available_at_ms"],
                status=sol_ctx["status"]
            ),
        }

        manip_risk = round(min(100.0, (
            (25.0 if mayhem_on else 0.0)
            + min(30.0, len(bundle_set) * 6.0)
            + (20.0 if n_u >= 4 and n_ind < n_u * 0.5 else 0.0)
            + (15.0 if liq_usd < 3500 else 0.0)
        )), 2)

        insider_risk = round(min(100.0, (
            (min(35.0, top5_num * 1.5) if supply_valid_flag > 0 else 25.0)
            + (25.0 if cr_dumped else 0.0)
            + min(25.0, len(bundle_set) * 5.0)
            + (15.0 if cr_q["prior_launches_count"] > 8 and cr_q["win_rate"] == 0 else 0.0)
        )), 2)

        snapshot = {
            "mint": mint,
            "symbol": (coin.get("symbol") or "").strip(),
            "name": (coin.get("name") or "").strip(),
            "mode": mode,
            "created_timestamp_ms": cts,
            "signal_timestamp_ms": int(signal_ts_ms),
            "price_timestamp_ms": int(px_ts),
            "price_source": px_src,
            "entry_price_usd": round(entry_px_usd, 10),
            "entry_price_quote_sol": round(entry_px_quote_sol, 12),
            "sol_price_usd_at_signal": round(sol_px_num, 4),
            "venue_at_signal": last_venue,
            "reserve_source_at_signal": reserve_source,
            "virtual_sol_reserve_at_signal": round(v_sol_reserve, 4),
            "virtual_token_reserve_at_signal": round(v_tok_reserve, 2),
            "implied_liquidity_usd": liq_usd,
            "mcap_at_signal_usd": round(mcap_T, 2),
            "already_moved_mult": round(entry_px_usd / max(init_curve_px_usd, 1e-12), 4),
            "buy_volume_usd": round(buy_usd, 2),
            "narrative_category": narr_cat,
            "supply_status": supply_status,
            "manipulation_risk_score": manip_risk,
            "insider_supply_risk_score": insider_risk,
            "features": f_map,
            "model_vector": {col: f_map[col]["model_num"] for col in ALL_MODEL_FEATURES_V2_1},
        }

        # HARD PER-FEATURE LEAKAGE GATE!
        validate_snapshot_no_leakage(snapshot)
        snapshot["data_max_timestamp_ms"] = max(int(f["max_data_timestamp_ms"]) for f in f_map.values())

        if persist_json and self.save_snapshots_dir is not None:
            out_f = self.save_snapshots_dir / f"{mint}_{signal_ts_ms}_feature_snapshot.json"
            out_f.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        return snapshot
