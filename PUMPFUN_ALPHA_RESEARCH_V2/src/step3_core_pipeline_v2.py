"""
STEP 3 (V2 — MASTER P0/P1/P2 ANALYTICAL, ANTI-LEAKAGE, FIFO, WALK-FORWARD, ABLATION & MODEL-FREEZE PIPELINE):

Generates:
- EARLY_SIGNALS_V2.csv (with strict `data_max_timestamp_ms <= signal_timestamp_ms` assertion, 9 fixed-horizon labels, censoring, and event-driven backtest fills)
- TOKEN_METRICS_V2.csv
- CONTROL_GROUP_V2.csv (propensity/covariate-matched Mayhem vs Standard & chronological control comparisons)
- WALLET_CLUSTERS_V2.csv (8-category relationship & confidence classification)
- INSIDER_ANALYSIS_V2.csv (separated verified on-chain insiders vs heuristic bundles + $COOL mint verification audit)
- SUPPLY_CONCENTRATION_V2.csv (ledger-reconstructed supply separating LP/curve/burn/technical from human holders)
- REALIZED_PNL_V2.csv (explicit FIFO lot accounting separating realized PnL, unrealized MTM, internal transfers, and unmatched inventory)
- WALK_FORWARD_RESULTS.csv (per-fold chronological walk-forward metrics with strict token disjointness & embargo)
- MODEL_COMPARISON.csv (V2 vs Frozen V1 vs 5 simple benchmarks + 7-component ablation study on identical timestamps & rules)
- cache/models/v2_frozen_model.json (frozen V2 model parameters locked BEFORE out-of-time new data test!)
"""
import hashlib
import json
import math
import re
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from scipy import stats

from config_v2 import (
    V1_DIR, V2_DIR, CACHE_DIR, RAW_V2_DIR, CANDLES_V2_DIR, TRADES_V2_DIR,
    WALLETS_V2_DIR, CREATORS_V2_DIR, MODELS_V2_DIR, LOGS_DIR,
    CONFIRMED_TECHNICAL_ADDRESSES
)
from temporal_integrity_v2 import (
    candle_close_time_ms,
    filter_closed_candles_before,
    get_causal_entry_price,
    compute_fixed_horizon_labels,
    CausalHistoryTracker,
)
from wallet_insider_fifo_v2 import (
    compute_fifo_pnl_for_token,
    classify_token_wallet_relationships_v2,
)
from event_backtest_and_walkforward_v2 import (
    RobustStandardScaler,
    RegularizedLogisticV2,
    compute_ranking_metrics,
    simulate_event_driven_position,
    build_embargoed_walkforward_splits,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step3_core_pipeline_v2.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("v2_step3")

NARRATIVE_RULES = [
    ("AI_Agents_Tech", r"\b(ai|agent|gpt|claude|llm|bot|neural|sentient|autonom|solana\.ai|mcp|truth|terminal|cyber|quantum|code|dev|algo|deepseek|openai|grok)\b"),
    ("Absurd_Toilet_Humor", r"\b(fart|poop|pee|shit|butt|ass|dick|balls|toilet|piss|burp|goon|brainrot|skibidi|autism|schizo)\b"),
    ("Animals_Pets", r"\b(dog|cat|pepe|frog|shib|inu|goat|pnut|squirrel|bear|bull|ape|monkey|pengu|bird|duck|fish|shark|whale|hamster|moo|hippo|capy|seal|otter|panda|wolf|fox|kitty|pup)\b"),
    ("Politics_Macro", r"\b(trump|biden|elon|musk|maga|doge|gov|president|senate|vote|america|usa|china|russia|war|tariff|fed|powell|tax|sec)\b"),
    ("Platform_Meta_Pump", r"\b(mayhem|polymarket|pump|pumpswap|boost|privy|sui|raydium|bonding|koth|trench|trenches|runner|cabal|bundle)\b"),
    ("Internet_Memes_Culture", r"\b(chad|wojak|pepe|kek|giga|sigma|chill|guy|doge|troll|npc|based|cope|wagmi|hodl|fomo|meme|viral|bro|aura|rizz)\b"),
    ("Finance_Trading_Wealth", r"\b(quant|alpha|rich|million|billion|money|cash|gold|dollar|usd|bank|yield|hedge|fund|stock|short|long|bullish|candle|moon)\b"),
]

def classify_narrative(name: str, symbol: str, desc: str) -> str:
    txt = f"{name or ''} {symbol or ''} {desc or ''}".lower()
    for cat, pat in NARRATIVE_RULES:
        if re.search(pat, txt):
            return cat
    return "General_Novelty_Other"

def narrative_lexical_score(name: str, symbol: str, desc: str) -> float:
    n_c = (name or "").strip()
    s_c = re.sub(r"[^a-zA-Z]", "", (symbol or "").lower())
    vow = sum(1 for c in s_c if c in "aeiouy") / max(1, len(s_c))
    pron = max(0.0, 1.0 - abs(vow - 0.42) * 1.8)
    words = [w for w in re.split(r"\s+", n_c) if w]
    mem = 0.5 * pron + 0.5 * (1.0 if 1 <= len(words) <= 3 else 0.4)
    return round(min(1.0, max(0.05, mem)), 4)

def load_sol_lookup(raw_dir):
    p = raw_dir / "sol_1h_v2.json"
    sol_map = {}
    if p.exists():
        kl = json.loads(p.read_text(encoding="utf-8"))
        closes = []
        for idx, k in enumerate(kl):
            hr = int(k[0]) // 3_600_000
            cp = float(k[4])
            closes.append(cp)
            r24 = ((cp / closes[idx - 24]) - 1.0) * 100.0 if idx >= 24 else 0.0
            sol_map[hr] = (cp, round(r24, 3))
    return sol_map

def get_sol_ctx(sol_map: dict, ts_ms: int):
    hr = int(ts_ms) // 3_600_000
    if hr in sol_map:
        return sol_map[hr]
    if not sol_map:
        return (70.0, 0.0)
    k = min(sol_map.keys(), key=lambda x: abs(x - hr))
    return sol_map[k]

# Feature columns for V2 Pump Potential Model (grouped cleanly for 7-component Ablation Study!)
V2_FEATURE_GROUPS = {
    "buyer_flow": ["independent_buyer_velocity", "unique_buyers_cum", "scale_in_buyers_ratio"],
    "buyer_acceleration": ["buyer_acceleration_ratio", "tx_acceleration_ratio"],
    "order_absorption": ["buy_sell_usd_ratio", "dip_absorption_ratio", "vol_to_mcap_ratio"],
    "wallet_intelligence": ["causal_smart_wallets_in"],
    "creator_history": ["creator_prior_win_rate", "creator_prior_launches_log", "creator_dumped_flag"],
    "insider_risk": ["same_slot_bundle_wallets_at_T", "mayhem_enabled"],
    "supply_concentration": ["top5_human_supply_pct_at_T", "concentration_change_pct"],
    "social_momentum": ["has_social_links", "twitter_is_post_or_handle"],
    "narrative_strength": ["narrative_lexical_score", "is_ticker_first_mover", "sol_ret_24h_pct"],
}
V2_ALL_FEATURES = [f for grp in V2_FEATURE_GROUPS.values() for f in grp]

def extract_causal_features_at_horizon(
    coin: dict,
    trades: list,
    candles_1m: list,
    created_ts_ms: int,
    signal_ts_ms: int,
    sol_px: float,
    sol_r24: float,
    history_tracker: CausalHistoryTracker,
    is_first_mover: int,
    tok_tech_addrs: set,
) -> dict:
    """
    Computes strictly causal features using ONLY events with timestamp <= signal_ts_ms.
    Verifies `data_max_timestamp_ms <= signal_ts_ms`!
    """
    entry_info = get_causal_entry_price(trades, candles_1m, created_ts_ms, signal_ts_ms, sol_px)
    entry_px = entry_info["entry_price_usd"]
    init_px = entry_info["init_curve_price_usd"]

    vis_trades = [tr for tr in trades if int(tr.get("blockTimeMs") or 0) <= signal_ts_ms]
    closed_1m = filter_closed_candles_before(candles_1m, "1m", signal_ts_ms)

    max_trade_ts = max([int(tr["blockTimeMs"]) for tr in vis_trades], default=created_ts_ms)
    max_candle_ts = max([candle_close_time_ms(b, "1m") for b in closed_1m], default=created_ts_ms)

    creator = coin.get("creator") or ""
    mayhem_on = int(coin.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(coin.get("mayhem"), dict) and bool(coin["mayhem"].get("state"))))
    tot_supply = 2_000_000_000.0 if mayhem_on else 1_000_000_000.0
    h_sec = max(1.0, (signal_ts_ms - created_ts_ms) / 1000.0)
    h_min = h_sec / 60.0

    # Detect same-slot launch bundle wallets strictly within [created_ts_ms, min(signal_ts_ms, created_ts_ms + 4000)]
    slot_map = defaultdict(list)
    for tr in vis_trades:
        if tr.get("side") == "buy" and int(tr.get("blockTimeMs") or 0) <= created_ts_ms + 4000:
            w = (tr.get("trader") or {}).get("address") or ""
            if w and w not in tok_tech_addrs:
                slot_map[int(tr.get("blockId") or 0)].append((int(tr.get("txIndex") or 0), w))
    bundle_set = set()
    for blk, lst in slot_map.items():
        lst.sort()
        uw = list(dict.fromkeys([w for _, w in lst]))
        if len(uw) >= 2:
            gaps = [lst[k+1][0] - lst[k][0] for k in range(len(lst)-1)]
            if gaps and max(gaps) <= 3:
                bundle_set.update(uw)

    buyers_first_s = {}
    indep_buyers = set()
    buy_cnt_by_w = Counter()
    buy_usd = 0.0
    sell_usd = 0.0
    first_half_b = 0
    sec_half_b = 0
    first_half_tx = 0
    sec_half_tx = 0
    w_bal = defaultdict(float)
    init_15s_bal = defaultdict(float)
    cr_bought = 0.0
    cr_sold = 0.0

    peak_px = init_px
    in_dip = False
    dip_b_usd = 0.0
    dip_s_usd = 0.0

    for tr in vis_trades:
        tms = int(tr.get("blockTimeMs") or created_ts_ms)
        rel_s = max(0.0, (tms - created_ts_ms) / 1000.0)
        w = (tr.get("trader") or {}).get("address") or ""
        side = tr.get("side")
        vu = float(tr.get("valueUsd") or 0.0)
        px = float(tr.get("priceUsd") or 0.0)
        if px > peak_px:
            peak_px = px
        elif peak_px >= init_px * 1.15 and 0 < px <= peak_px * 0.88:
            in_dip = True

        if rel_s <= h_sec * 0.5:
            first_half_tx += 1
        else:
            sec_half_tx += 1

        if w and w not in tok_tech_addrs:
            qty = float((tr.get("baseAmount") or {}).get("raw") or 0.0) / (10 ** int((tr.get("baseAmount") or {}).get("decimals") or 6))
            if side == "buy":
                buy_usd += vu
                buy_cnt_by_w[w] += 1
                w_bal[w] += qty
                if rel_s <= 15.0:
                    init_15s_bal[w] += qty
                if w == creator:
                    cr_bought += qty
                if in_dip:
                    dip_b_usd += vu
                if w not in buyers_first_s:
                    buyers_first_s[w] = rel_s
                    if rel_s <= h_sec * 0.5:
                        first_half_b += 1
                    else:
                        sec_half_b += 1
                    if w not in bundle_set and w != creator:
                        indep_buyers.add(w)
            elif side == "sell":
                sell_usd += vu
                w_bal[w] = max(0.0, w_bal[w] - qty)
                if rel_s <= 15.0:
                    init_15s_bal[w] = max(0.0, init_15s_bal[w] - qty)
                if w == creator:
                    cr_sold += qty
                if in_dip:
                    dip_s_usd += vu

    # Causal history lookups strictly gated by `label_available_at_ms < signal_ts_ms`!
    cr_stats = history_tracker.get_creator_stats_at(creator, signal_ts_ms)
    sm_stats = history_tracker.get_smart_wallets_count_at(list(buyers_first_s.keys()), signal_ts_ms, min_eval_entries=2, min_hit_rate=0.35)

    data_max_ts = max(
        entry_info["price_timestamp_ms"],
        max_trade_ts,
        max_candle_ts,
        cr_stats["max_history_ts_used"],
        sm_stats["max_wallet_history_ts_used"],
    )
    assert data_max_ts <= signal_ts_ms, f"Temporal violation: data_max_ts={data_max_ts} > signal_ts={signal_ts_ms}"

    mcap_T = entry_px * 1_000_000_000.0
    liq_T = round(60.0 * sol_px * math.sqrt(max(0.25, entry_px / max(init_px, 1e-11))), 2)

    n_u = len(buyers_first_s)
    n_ind = len(indep_buyers)
    scale_in_ratio = round(sum(1 for w, c in buy_cnt_by_w.items() if c >= 2) / max(1, n_u), 4)
    b_accel = round((sec_half_b + 1.0) / (first_half_b + 1.0), 4)
    tx_accel = round((sec_half_tx + 1.5) / (first_half_tx + 1.5), 4)
    bs_ratio = round(math.log1p(buy_usd + 5.0) - math.log1p(sell_usd + 5.0), 4)
    dip_abs = round((dip_b_usd + 5.0) / (dip_s_usd + 5.0), 4) if in_dip else 1.0
    vol_mcap = round((buy_usd + sell_usd) / max(500.0, mcap_T), 4)

    top5_now = round((sum(sorted(w_bal.values(), reverse=True)[:5]) / tot_supply) * 100.0, 4)
    top5_15s = round((sum(sorted(init_15s_bal.values(), reverse=True)[:5]) / tot_supply) * 100.0, 4)
    conc_chg = round(top5_now - top5_15s, 4)
    cr_dumped = int(cr_sold > 0 and cr_sold >= 0.40 * max(cr_bought, 1.0))

    tw = str(coin.get("twitter") or "").strip()
    has_soc = int(bool(tw) or bool(coin.get("website")))
    tw_good = int(bool(tw) and "/i/communities/" not in tw)
    lex_s = narrative_lexical_score(coin.get("name"), coin.get("symbol"), coin.get("description"))

    # Real-time Manipulation Risk V2 & Insider/Supply Risk V2 (0-100, separate from Pump Potential!)
    manip_risk_v2 = round(min(100.0, (
        (25.0 if mayhem_on else 0.0)
        + min(30.0, len(bundle_set) * 6.0)
        + (20.0 if n_u >= 4 and n_ind < n_u * 0.5 else 0.0)
        + (15.0 if liq_T < 3500 else 0.0)
        + (10.0 if vol_mcap > 1.5 and n_ind <= 2 else 0.0)
    )), 2)

    insider_risk_v2 = round(min(100.0, (
        min(35.0, top5_now * 1.5)
        + (25.0 if cr_dumped else 0.0)
        + min(25.0, len(bundle_set) * 5.0)
        + (15.0 if cr_stats["creator_prior_launches_count"] > 8 and cr_stats["creator_prior_win_rate"] == 0 else 0.0)
    )), 2)

    feat_dict = {
        "independent_buyer_velocity": round(n_ind / h_min, 4),
        "unique_buyers_cum": float(n_u),
        "scale_in_buyers_ratio": scale_in_ratio,
        "buyer_acceleration_ratio": b_accel,
        "tx_acceleration_ratio": tx_accel,
        "buy_sell_usd_ratio": bs_ratio,
        "dip_absorption_ratio": min(10.0, dip_abs),
        "vol_to_mcap_ratio": min(5.0, vol_mcap),
        "causal_smart_wallets_in": float(sm_stats["causal_smart_wallets_in"]),
        "creator_prior_win_rate": cr_stats["creator_prior_win_rate"],
        "creator_prior_launches_log": round(math.log1p(cr_stats["creator_prior_launches_count"]), 4),
        "creator_dumped_flag": float(cr_dumped),
        "same_slot_bundle_wallets_at_T": float(len(bundle_set)),
        "mayhem_enabled": float(mayhem_on),
        "top5_human_supply_pct_at_T": top5_now,
        "concentration_change_pct": conc_chg,
        "has_social_links": float(has_soc),
        "twitter_is_post_or_handle": float(tw_good),
        "narrative_lexical_score": lex_s,
        "is_ticker_first_mover": float(is_first_mover),
        "sol_ret_24h_pct": sol_r24,
    }

    return {
        "entry_price_usd": entry_px,
        "price_timestamp_ms": entry_info["price_timestamp_ms"],
        "price_source": entry_info["price_source"],
        "data_max_timestamp_ms": data_max_ts,
        "leakage_check_passed": int(data_max_ts <= signal_ts_ms),
        "implied_liquidity_usd": liq_T,
        "mcap_at_signal_usd": round(mcap_T, 2),
        "already_moved_mult": round(entry_px / max(init_px, 1e-11), 4),
        "buy_volume_usd": round(buy_usd, 2),
        "independent_buyers_count": n_ind,
        "manipulation_risk_v2": manip_risk_v2,
        "insider_supply_risk_v2": insider_risk_v2,
        "features": feat_dict,
    }

def explain_v2_score(feat: dict, pot_score: float, manip_risk: float, ins_risk: float) -> str:
    reasons = []
    if feat["independent_buyer_velocity"] >= 1.5:
        reasons.append(f"+High indep. buyer flow ({feat['independent_buyer_velocity']:.1f}/m)")
    elif feat["unique_buyers_cum"] <= 1:
        reasons.append("-Low/zero early buyers")
    if feat["buy_sell_usd_ratio"] >= 0.6:
        reasons.append("+Net buy USD dominance")
    elif feat["buy_sell_usd_ratio"] < -0.2:
        reasons.append("-Net sell pressure")
    if feat["dip_absorption_ratio"] >= 1.3:
        reasons.append("+Strong dip absorption")
    if feat["causal_smart_wallets_in"] >= 1:
        reasons.append(f"+Smart wallet entry ({int(feat['causal_smart_wallets_in'])})")
    if feat["creator_dumped_flag"] >= 1:
        reasons.append("-Creator sold early")
    if feat["mayhem_enabled"] >= 1:
        reasons.append("!Mayhem AI bot mode")
    if manip_risk >= 55 or ins_risk >= 55:
        reasons.append("!Elevated bundle/supply risk")
    return "; ".join(reasons[:4]) if reasons else "Baseline arrival profile"

def compute_frozen_v1_score_proxy(row: pd.Series, v1_weights: dict) -> float:
    """Evaluates frozen V1 feature weight vector on the exact same V2 standardized test observation."""
    mapping = {
        "independent_buyer_velocity": row.get("independent_buyer_velocity", 0.0),
        "creator_dumped_at_T": row.get("creator_dumped_flag", 0.0),
        "dip_absorption_ratio_at_T": row.get("dip_absorption_ratio", 1.0),
        "causal_smart_wallets_in": row.get("causal_smart_wallets_in", 0.0),
        "meme_shareability_score": row.get("narrative_lexical_score", 0.5),
        "vol_to_mcap_ratio_at_T": row.get("vol_to_mcap_ratio", 0.0),
        "is_ticker_first_mover": row.get("is_ticker_first_mover", 1.0),
        "buy_sell_usd_ratio": math.exp(row.get("buy_sell_usd_ratio", 0.0)),
        "mayhem_enabled": row.get("mayhem_enabled", 0.0),
        "wallet_concentration_change": row.get("concentration_change_pct", 0.0),
        "creator_prior_win_rate": row.get("creator_prior_win_rate", 0.0),
        "buyer_acceleration_ratio": row.get("buyer_acceleration_ratio", 1.0),
        "tx_acceleration_ratio": row.get("tx_acceleration_ratio", 1.0),
        "sol_ret_24h_pct": row.get("sol_ret_24h_pct", 0.0),
        "has_social_links": row.get("has_social_links", 0.0),
    }
    z = 0.0
    for k, w in v1_weights.items():
        if k in mapping:
            z += float(w) * float(mapping[k])
    return float(100.0 / (1.0 + math.exp(-max(-15.0, min(15.0, z * 0.25)))))

def main():
    logger.info("Loading V2 chronological dataset, RPC paginated profiles, creator histories, and frozen V1...")
    ds = json.loads((RAW_V2_DIR / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    tokens = sorted(ds["tokens"], key=lambda x: (int(x["created_timestamp"]), x["mint"]))
    collection_ms = int(ds["collection_timestamp_ms"])

    sol_map = load_sol_lookup(RAW_V2_DIR)
    ds_enr = json.loads((RAW_V2_DIR / "dexscreener_v2.json").read_text(encoding="utf-8")) if (RAW_V2_DIR / "dexscreener_v2.json").exists() else {}
    rpc_payload = json.loads((WALLETS_V2_DIR / "paginated_wallet_rpc_v2.json").read_text(encoding="utf-8")) if (WALLETS_V2_DIR / "paginated_wallet_rpc_v2.json").exists() else {"wallets": {}, "funder_types": {}}
    rpc_wallets = rpc_payload.get("wallets", {})
    funder_types = rpc_payload.get("funder_types", {})
    cr_histories = json.loads((CREATORS_V2_DIR / "outcome_blind_creator_histories.json").read_text(encoding="utf-8")) if (CREATORS_V2_DIR / "outcome_blind_creator_histories.json").exists() else {}
    v1_frozen = json.loads((CACHE_DIR / "v1_frozen_model.json").read_text(encoding="utf-8"))
    v1_weights = v1_frozen.get("v1_weights", {})

    # Pre-index SPL transfers by mint from paginated RPC
    spl_by_mint = defaultdict(list)
    for w_info in rpc_wallets.values():
        for tf in w_info.get("spl_transfers", []):
            spl_by_mint[tf["mint"]].append(tf)

    # Seed CausalHistoryTracker with pre-cohort creator history (each historical coin's 24h evaluation completes at created_ts + 24h!)
    tracker = CausalHistoryTracker()
    cohort_mint_set = {t["mint"] for t in tokens}
    for cr, cinfo in cr_histories.items():
        items = cinfo.get("coins_full") or cinfo.get("coins_brief") or []
        for it in items:
            m_id = it.get("mint")
            if m_id in cohort_mint_set:
                continue  # Cohort tokens will be registered dynamically from their actual V2 4h labels!
            bts = int(it.get("created_timestamp") or 0)
            if bts > 0:
                # Conservative 24h evaluation completion timestamp (`label_available_at_ms = bts + 24h`)!
                lbl_avail = bts + 86_400_000
                is_win = int(bool(it.get("complete")))
                tracker.register_creator_token(cr, bts, lbl_avail, is_win)

    # First pass for co-sniper counts (strictly descriptive for P1 Category 5) & ticker first-mover tracking
    co_sniper_counts = Counter()
    ticker_seen = Counter()
    is_first_mover_map = {}
    trades_by_mint = {}
    candles_by_mint = {}

    for tok in tokens:
        m = tok["mint"]
        sym_norm = re.sub(r"[^a-z0-9]", "", (tok.get("symbol") or "").lower())
        is_first_mover_map[m] = int(ticker_seen[sym_norm] == 0) if sym_norm else 1
        if sym_norm:
            ticker_seen[sym_norm] += 1

        tp = TRADES_V2_DIR / f"{m}.json"
        cp = CANDLES_V2_DIR / f"{m}.json"
        td = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {"trades": [], "early_30m_pagination_truncated": 0}
        cd = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {"candles_1m": [], "candles_15m": [], "candles_4h": [], "api_ok": 0}
        trades_by_mint[m] = td
        candles_by_mint[m] = cd

        e15 = []
        for tr in td.get("trades", []):
            w = (tr.get("trader") or {}).get("address") or ""
            if tr.get("side") == "buy" and w and w not in CONFIRMED_TECHNICAL_ADDRESSES and w not in e15:
                e15.append(w)
                if len(e15) >= 15:
                    break
        for i in range(len(e15)):
            for j in range(i + 1, len(e15)):
                co_sniper_counts[tuple(sorted((e15[i], e15[j])))] += 1

    # Second pass (strictly chronological!): extract multi-horizon signals, fixed-horizon labels, event-driven fills,
    # FIFO PnL, Supply Concentration, and register causal 4h outcomes into `tracker` ONLY with `label_available_at = sig_5m + 4h`!
    obs_horizons = [("1m", 60_000), ("3m", 180_000), ("5m", 300_000), ("10m", 600_000), ("15m", 900_000)]

    early_rows = []
    token_metrics_rows = []
    clusters_rows = []
    insider_rows = []
    supply_rows = []
    fifo_pnl_rows = []

    for tok in tokens:
        m = tok["mint"]
        cts = int(tok["created_timestamp"])
        creator = tok.get("creator") or ""
        sol_px, sol_r24 = get_sol_ctx(sol_map, cts)
        td = trades_by_mint[m]
        cd = candles_by_mint[m]
        trades = td.get("trades", [])
        c_1m = cd.get("candles_1m", [])
        c_15m = cd.get("candles_15m", [])
        c_4h = cd.get("candles_4h", [])
        tp_exists = (TRADES_V2_DIR / f"{m}.json").exists()
        # If candles succeeded OR trades endpoint verified 0 swaps ever occurred, history is known; if trades > 0 but candles missing, mark api_ok=0 -> status='unknown'!
        api_ok = int(int(cd.get("api_ok", 0)) == 1 or (tp_exists and len(trades) == 0))
        col_ms = int(cd.get("collection_timestamp_ms") or collection_ms)

        tok_tech = dict(CONFIRMED_TECHNICAL_ADDRESSES)
        for fld, desc_t in [("bonding_curve", "Token_Bonding_Curve"), ("associated_bonding_curve", "Token_Assoc_Bonding_Curve"), ("raydium_pool", "Raydium_LP_Pool"), ("pool_address", "Canonical_Pool")]:
            if tok.get(fld):
                tok_tech[tok[fld]] = desc_t

        mayhem_on = int(tok.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(tok.get("mayhem"), dict) and bool(tok["mayhem"].get("state"))))
        tot_sup = 2_000_000_000.0 if mayhem_on else 1_000_000_000.0
        narr_cat = classify_narrative(tok.get("name"), tok.get("symbol"), tok.get("description"))

        tok_5m_summary = None

        for h_lbl, h_ms in obs_horizons:
            sig_ms = cts + h_ms
            if sig_ms > col_ms:
                continue

            causal_pack = extract_causal_features_at_horizon(
                tok, trades, c_1m, cts, sig_ms, sol_px, sol_r24,
                tracker, is_first_mover_map[m], set(tok_tech.keys())
            )
            labels = compute_fixed_horizon_labels(
                sig_ms, causal_pack["entry_price_usd"], causal_pack["implied_liquidity_usd"],
                sol_px, col_ms, api_ok, trades, c_1m, c_15m, c_4h
            )
            # Event-driven 4h execution simulation (only meaningful if 4h is complete, else mark MTM/censored)
            if labels["status_4h"] == "complete":
                sim_4h = simulate_event_driven_position(
                    sig_ms, causal_pack["entry_price_usd"], causal_pack["implied_liquidity_usd"],
                    sol_px, trades, c_1m, c_15m, horizon_ms=14_400_000, position_usd=200.0
                )
            else:
                sim_4h = {
                    "execution_status": f"CENSORED_OR_{labels['status_4h'].upper()}",
                    "entry_ts_ms": None, "exit_ts_ms": None, "position_usd": 0.0,
                    "entry_exec_price_usd": np.nan, "avg_exit_exec_price_usd": np.nan,
                    "total_fees_usd": np.nan, "total_slippage_impact_pct": np.nan,
                    "gross_return_pct": np.nan, "net_return_pct": np.nan,
                    "exit_reason": f"HORIZON_4H_{labels['status_4h'].upper()}",
                }

            data_comp = "COMPLETE" if (api_ok and not td.get("early_30m_pagination_truncated")) else ("TRUNCATED_HIGH_ACTIVITY_TAPE" if api_ok else "API_INCOMPLETE")

            row_e = {
                "mint": m,
                "symbol": (tok.get("symbol") or "").strip(),
                "name": (tok.get("name") or "").strip(),
                "stratum": tok.get("_v2_stratum", ""),
                "narrative_category": narr_cat,
                "created_timestamp_ms": cts,
                "obs_horizon": h_lbl,
                "signal_timestamp_ms": sig_ms,
                "data_max_timestamp_ms": causal_pack["data_max_timestamp_ms"],
                "price_timestamp_ms": causal_pack["price_timestamp_ms"],
                "leakage_check_passed": causal_pack["leakage_check_passed"],
                "price_source": causal_pack["price_source"],
                "entry_price_usd": causal_pack["entry_price_usd"],
                "mcap_at_signal_usd": causal_pack["mcap_at_signal_usd"],
                "implied_liquidity_usd": causal_pack["implied_liquidity_usd"],
                "already_moved_mult": causal_pack["already_moved_mult"],
                "buy_volume_usd": causal_pack["buy_volume_usd"],
                "data_completeness": data_comp,
                "manipulation_risk_v2": causal_pack["manipulation_risk_v2"],
                "insider_supply_risk_v2": causal_pack["insider_supply_risk_v2"],
                **causal_pack["features"],
                **labels,
                "sim_4h_execution_status": sim_4h["execution_status"],
                "sim_4h_entry_exec_px": sim_4h["entry_exec_price_usd"],
                "sim_4h_exit_exec_px": sim_4h["avg_exit_exec_price_usd"],
                "sim_4h_fees_usd": sim_4h["total_fees_usd"],
                "sim_4h_slippage_pct": sim_4h["total_slippage_impact_pct"],
                "sim_4h_gross_ret_pct": sim_4h["gross_return_pct"],
                "sim_4h_net_ret_pct": sim_4h["net_return_pct"],
                "sim_4h_exit_reason": sim_4h["exit_reason"],
                "feature_snapshot_json": json.dumps(causal_pack["features"], separators=(",", ":")),
            }
            early_rows.append(row_e)
            if h_lbl == "5m":
                tok_5m_summary = row_e

        # Register 4h outcome into `tracker` with strict `label_available_at_ms = cts + 5m + 4h`!
        if tok_5m_summary and tok_5m_summary["status_4h"] == "complete":
            win_4h = int(tok_5m_summary["hit_2x_4h"] == 1)
            lbl_avail_4h = cts + 300_000 + 14_400_000
            tracker.register_creator_token(creator, cts, lbl_avail_4h, win_4h)
            seen_b = set()
            for tr in trades:
                if int(tr.get("blockTimeMs") or 0) <= cts + 300_000 and tr.get("side") == "buy":
                    w = (tr.get("trader") or {}).get("address") or ""
                    if w and w not in tok_tech and w not in seen_b:
                        seen_b.add(w)
                        tracker.register_wallet_entry(w, int(tr["blockTimeMs"]), lbl_avail_4h, win_4h)
                        if len(seen_b) >= 20:
                            break

        # P1: Token-level FIFO PnL, Supply Concentration & 8-Category Wallet Relationships
        last_mark_px = float(c_15m[-1]["close"]) if c_15m else (float(trades[-1]["priceUsd"]) if trades and float(trades[-1].get("priceUsd") or 0) > 0 else (27.96 * sol_px / 1e9))
        is_complete_tape = (td.get("genesis_trades_count", 0) < 300) and api_ok == 1
        fifo_res = compute_fifo_pnl_for_token(
            trades, spl_by_mint.get(m, []), tot_sup, last_mark_px, sol_px, set(tok_tech.keys()), is_complete_tape
        )
        rel_rows, ins_sum = classify_token_wallet_relationships_v2(
            m, creator, trades, tok_tech, rpc_wallets, funder_types, co_sniper_counts,
            fifo_res["wallets"], fifo_res["supply"]["effective_supply"]
        )
        clusters_rows.extend(rel_rows)

        sup_row = {
            "mint": m,
            "symbol": (tok.get("symbol") or "").strip(),
            "stratum": tok.get("_v2_stratum", ""),
            **fifo_res["supply"],
            "verified_onchain_insider_supply_pct": ins_sum["verified_onchain_insider_supply_pct"],
            "heuristic_bundle_sniper_supply_pct": ins_sum["heuristic_bundle_sniper_supply_pct"],
        }
        supply_rows.append(sup_row)

        ins_row = {
            "mint": m,
            "symbol": (tok.get("symbol") or "").strip(),
            "creator": creator,
            **ins_sum,
            "top10_human_holders_pct": fifo_res["supply"]["top10_human_holders_pct"],
            "supply_reconstruction_quality": fifo_res["supply"]["reconstruction_quality"],
            "cool_case_verification_status": "UNVERIFIED_TICKER_COLLISION_NOT_CONFIRMED" if str(tok.get("symbol") or "").upper().replace("$", "") == "COOL" else "N/A",
        }
        insider_rows.append(ins_row)

        # Save top active wallets per token into REALIZED_PNL_V2.csv (with RPC history metadata if traced!)
        top_w_fifo = sorted(fifo_res["wallets"].items(), key=lambda kv: kv[1]["sol_spent_gross"] + kv[1]["sol_received_gross"], reverse=True)[:8]
        for w_addr, wf in top_w_fifo:
            if wf["sol_spent_gross"] + wf["sol_received_gross"] < 0.05:
                continue
            r_meta = rpc_wallets.get(w_addr, {})
            fifo_pnl_rows.append({
                "mint": m,
                "symbol": (tok.get("symbol") or "").strip(),
                "wallet": w_addr,
                "is_creator": int(w_addr == creator),
                "tokens_bought": round(wf["tokens_bought"], 2),
                "tokens_sold": round(wf["tokens_sold"], 2),
                "fifo_matched_sold_tokens": round(wf["fifo_matched_sold_tokens"], 2),
                "unmatched_sold_tokens": round(wf["unmatched_sold_tokens"], 2),
                "sol_spent_gross": round(wf["sol_spent_gross"], 5),
                "sol_received_gross": round(wf["sol_received_gross"], 5),
                "est_fees_sol": round(wf["est_fees_sol"], 5),
                "fifo_realized_pnl_sol": wf["fifo_realized_pnl_sol"],
                "fifo_realized_pnl_usd": wf["fifo_realized_pnl_usd"],
                "remaining_fifo_tokens": wf["remaining_fifo_tokens"],
                "remaining_cost_basis_sol": wf["remaining_cost_basis_sol"],
                "fifo_unrealized_pnl_sol": wf["fifo_unrealized_pnl_sol"],
                "internal_transfer_in_tokens": round(wf["internal_transfer_in_tokens"], 2),
                "internal_transfer_out_tokens": round(wf["internal_transfer_out_tokens"], 2),
                "unattributed_sell_proceeds_sol": wf["unattributed_sell_proceeds_sol"],
                "pnl_completeness": wf["pnl_completeness"],
                "rpc_signatures_analyzed": r_meta.get("signatures_analyzed", 0),
                "rpc_history_completeness": r_meta.get("history_completeness", "NOT_QUERIED_IN_RPC_SUBSET"),
                "rpc_first_tx_utc": r_meta.get("first_tx_utc", ""),
                "rpc_last_tx_utc": r_meta.get("last_tx_utc", ""),
            })

        if tok_5m_summary:
            ds_liq = float(((ds_enr.get(m) or {}).get("liquidity") or {}).get("usd") or 0.0)
            token_metrics_rows.append({
                "mint": m,
                "symbol": (tok.get("symbol") or "").strip(),
                "name": (tok.get("name") or "").strip(),
                "creator": creator,
                "stratum": tok.get("_v2_stratum", ""),
                "created_timestamp_ms": cts,
                "created_utc": datetime.fromtimestamp(cts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "narrative_category": narr_cat,
                "mayhem_enabled": mayhem_on,
                "migrated_dex_current_metadata": int(bool(tok.get("complete"))),
                "initial_mcap_usd": round((27.96 * sol_px), 2),
                "mcap_at_5m_usd": tok_5m_summary["mcap_at_signal_usd"],
                "implied_liquidity_5m_usd": tok_5m_summary["implied_liquidity_usd"],
                "dexscreener_current_liquidity_usd": round(ds_liq, 2),
                "unique_buyers_5m": int(tok_5m_summary["unique_buyers_cum"]),
                "independent_buyer_velocity_5m": tok_5m_summary["independent_buyer_velocity"],
                "buy_volume_5m_usd": tok_5m_summary["buy_volume_usd"],
                "status_1h": tok_5m_summary["status_1h"],
                "status_4h": tok_5m_summary["status_4h"],
                "status_24h": tok_5m_summary["status_24h"],
                "hit_2x_1h": tok_5m_summary["hit_2x_1h"],
                "hit_3x_1h": tok_5m_summary["hit_3x_1h"],
                "hit_2x_4h": tok_5m_summary["hit_2x_4h"],
                "hit_3x_4h": tok_5m_summary["hit_3x_4h"],
                "hit_5x_4h": tok_5m_summary["hit_5x_4h"],
                "hit_2x_24h": tok_5m_summary["hit_2x_24h"],
                "hit_3x_24h": tok_5m_summary["hit_3x_24h"],
                "reliable_market_mult_4h": tok_5m_summary["reliable_market_mult_4h"],
                "realizable_mult_4h_pos250": tok_5m_summary["realizable_mult_4h_pos250"],
                "sim_4h_net_ret_pct": tok_5m_summary["sim_4h_net_ret_pct"],
                "verified_onchain_insider_supply_pct": ins_sum["verified_onchain_insider_supply_pct"],
                "heuristic_bundle_sniper_supply_pct": ins_sum["heuristic_bundle_sniper_supply_pct"],
                "manipulation_risk_v2_5m": tok_5m_summary["manipulation_risk_v2"],
                "insider_supply_risk_v2_5m": tok_5m_summary["insider_supply_risk_v2"],
                "data_completeness": tok_5m_summary["data_completeness"],
            })

    df_early = pd.DataFrame(early_rows)
    df_tm = pd.DataFrame(token_metrics_rows)

    # Hard global anti-leakage assertion across all generated signal rows!
    violations = int((df_early["data_max_timestamp_ms"] > df_early["signal_timestamp_ms"]).sum())
    assert violations == 0, f"CRITICAL: {violations} rows violated data_max_timestamp <= signal_timestamp!"
    logger.info(f"Verified 0 leakage violations across {len(df_early)} point-in-time signal snapshots!")

    # ==========================================================================
    # P0/P2: WALK-FORWARD VALIDATION WITH EMBARGO, BENCHMARKS & 7 ABLATION TESTS
    # ==========================================================================
    # Primary evaluation horizon: `t = 5m` signals predicting uncensored `hit_2x_4h` (and also report `hit_3x_4h` & `hit_2x_1h`)!
    df_5m_unc = df_early[(df_early["obs_horizon"] == "5m") & (df_early["status_4h"] == "complete")].sort_values("created_timestamp_ms").reset_index(drop=True)
    target_col = "hit_2x_4h" if df_5m_unc["hit_2x_4h"].sum() >= 15 else "hit_2x_1h"
    logger.info(
        f"Uncensored 5m->4h dataset: N={len(df_5m_unc)} | "
        f"hit_2x_1h={int(df_5m_unc['hit_2x_1h'].sum())} ({df_5m_unc['hit_2x_1h'].mean()*100:.2f}%) | "
        f"hit_2x_4h={int(df_5m_unc['hit_2x_4h'].sum())} ({df_5m_unc['hit_2x_4h'].mean()*100:.2f}%) | "
        f"hit_3x_4h={int(df_5m_unc['hit_3x_4h'].sum())} ({df_5m_unc['hit_3x_4h'].mean()*100:.2f}%)"
    )

    splits = build_embargoed_walkforward_splits(df_5m_unc, embargo_ms=14_400_000, n_test_folds=4)
    wf_rows = []
    oos_chunks = []

    for sp in splits:
        f_num = sp["fold"]
        tr_df = df_5m_unc[df_5m_unc["mint"].isin(sp["train_mints"] | sp["val_mints"])].copy()
        te_df = df_5m_unc[df_5m_unc["mint"].isin(sp["test_mints"])].copy()
        if tr_df[target_col].nunique() < 2 or len(te_df) < 10:
            continue

        sc = RobustStandardScaler()
        X_tr = sc.fit_transform(tr_df[V2_ALL_FEATURES])
        X_te = sc.transform(te_df[V2_ALL_FEATURES])
        clf = RegularizedLogisticV2(C=0.35).fit(X_tr, tr_df[target_col].values)

        te_df["pump_potential_v2"] = np.round(clf.predict_proba(X_te) * 100.0, 2)
        te_df["pump_potential_v1_frozen"] = [round(compute_frozen_v1_score_proxy(r, v1_weights), 2) for _, r in te_df.iterrows()]
        te_df["wf_fold"] = f_num
        te_df["embargo_status"] = sp["embargo_status"]
        te_df["embargo_minutes"] = sp["actual_embargo_minutes"]

        # Ablation predictions on the exact same fold!
        for ab_name, drop_cols in V2_FEATURE_GROUPS.items():
            if ab_name in ("buyer_flow", "order_absorption"):
                continue
            keep_cols = [c for c in V2_ALL_FEATURES if c not in drop_cols]
            sc_a = RobustStandardScaler()
            Xa_tr = sc_a.fit_transform(tr_df[keep_cols])
            Xa_te = sc_a.transform(te_df[keep_cols])
            ca = RegularizedLogisticV2(C=0.35).fit(Xa_tr, tr_df[target_col].values)
            te_df[f"ablation_no_{ab_name}"] = np.round(ca.predict_proba(Xa_te) * 100.0, 2)

        oos_chunks.append(te_df)

        # Record per-fold metrics for V2, V1 Frozen, Buyer Velocity, Volume, Price Gain
        for strat_name, score_col in [
            ("Pump_Potential_V2", "pump_potential_v2"),
            ("Pump_Potential_V1_Frozen", "pump_potential_v1_frozen"),
            ("Buyer_Count_Velocity_Only", "independent_buyer_velocity"),
            ("Volume_Only", "buy_volume_usd"),
            ("Price_Gain_Only", "already_moved_mult"),
        ]:
            m_fold = compute_ranking_metrics(te_df[target_col].values, te_df[score_col].values, te_df["sim_4h_net_ret_pct"].values)
            wf_rows.append({
                "fold": f_num,
                "test_period_start_utc": datetime.fromtimestamp(sp["test_start_ms"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "test_period_end_utc": datetime.fromtimestamp(sp["test_end_ms"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "embargo_status": sp["embargo_status"],
                "embargo_minutes": sp["actual_embargo_minutes"],
                "target": target_col,
                "strategy": strat_name,
                **m_fold,
            })

    df_oos = pd.concat(oos_chunks, ignore_index=True)

    # Pooled head-to-head comparison on identical OOS timestamps, dataset, and rules (`MODEL_COMPARISON.csv`)
    rng = np.random.default_rng(42)
    df_oos["random_score"] = rng.uniform(0.0, 100.0, len(df_oos))
    df_oos["simple_momentum"] = 0.5 * df_oos["already_moved_mult"].rank(pct=True) + 0.5 * df_oos["buy_sell_usd_ratio"].rank(pct=True)

    comparison_specs = [
        ("Pump_Potential_V2", "pump_potential_v2", "Full_Model_V2"),
        ("Pump_Potential_V1_Frozen", "pump_potential_v1_frozen", "Legacy_Model_V1"),
        ("Buyer_Count_Velocity_Only", "independent_buyer_velocity", "Simple_Benchmark"),
        ("Volume_Only", "buy_volume_usd", "Simple_Benchmark"),
        ("Price_Gain_Only", "already_moved_mult", "Simple_Benchmark"),
        ("Simple_Momentum", "simple_momentum", "Simple_Benchmark"),
        ("Random_Selection", "random_score", "Baseline"),
        ("Ablation_No_Wallet_Intelligence", "ablation_no_wallet_intelligence", "Ablation_V2"),
        ("Ablation_No_Buyer_Acceleration", "ablation_no_buyer_acceleration", "Ablation_V2"),
        ("Ablation_No_Creator_History", "ablation_no_creator_history", "Ablation_V2"),
        ("Ablation_No_Insider_Risk", "ablation_no_insider_risk", "Ablation_V2"),
        ("Ablation_No_Supply_Concentration", "ablation_no_supply_concentration", "Ablation_V2"),
        ("Ablation_No_Social_Momentum", "ablation_no_social_momentum", "Ablation_V2"),
        ("Ablation_No_Narrative_Strength", "ablation_no_narrative_strength", "Ablation_V2"),
    ]

    model_comp_rows = []
    for s_name, s_col, s_group in comparison_specs:
        if s_col not in df_oos.columns:
            continue
        for eval_target in ["hit_2x_1h", "hit_2x_4h", "hit_3x_4h"]:
            valid_sub = df_oos[df_oos[eval_target].notna()]
            if len(valid_sub) == 0:
                continue
            met = compute_ranking_metrics(valid_sub[eval_target].values, valid_sub[s_col].values, valid_sub["sim_4h_net_ret_pct"].values)
            model_comp_rows.append({
                "strategy": s_name,
                "group": s_group,
                "horizon_target": eval_target,
                **met,
            })

    # Fit FINAL FROZEN V2 MODEL on all uncensored historical 5m observations (prior to unseen Nov 25 test!)
    final_scaler = RobustStandardScaler()
    X_full = final_scaler.fit_transform(df_5m_unc[V2_ALL_FEATURES])
    final_clf = RegularizedLogisticV2(C=0.35).fit(X_full, df_5m_unc[target_col].values)

    # Apply V2 scores + confidence + explainability across all rows of EARLY_SIGNALS_V2 and TOKEN_METRICS_V2
    X_all_early = final_scaler.transform(df_early[V2_ALL_FEATURES])
    df_early["pump_potential_v2_score"] = np.round(final_clf.predict_proba(X_all_early) * 100.0, 2)
    df_early["score_confidence_level"] = np.where(
        (df_early["data_completeness"] == "COMPLETE") & (df_early["unique_buyers_cum"] >= 3), "HIGH",
        np.where(df_early["data_completeness"] == "COMPLETE", "MEDIUM", "LOW")
    )
    df_early["score_reasons"] = [
        explain_v2_score(json.loads(r["feature_snapshot_json"]), r["pump_potential_v2_score"], r["manipulation_risk_v2"], r["insider_supply_risk_v2"])
        for _, r in df_early.iterrows()
    ]

    s5_pot = df_early[df_early["obs_horizon"] == "5m"].set_index("mint")["pump_potential_v2_score"].to_dict()
    s5_conf = df_early[df_early["obs_horizon"] == "5m"].set_index("mint")["score_confidence_level"].to_dict()
    s5_rsn = df_early[df_early["obs_horizon"] == "5m"].set_index("mint")["score_reasons"].to_dict()
    df_tm["pump_potential_v2_5m"] = df_tm["mint"].map(s5_pot)
    df_tm["score_confidence_level"] = df_tm["mint"].map(s5_conf)
    df_tm["score_reasons"] = df_tm["mint"].map(s5_rsn)

    # Freeze V2 Model Artifact BEFORE unseen Nov 25 data is ever fetched!
    frozen_v2_obj = {
        "model_id": "Pump_Potential_V2_Frozen",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "trained_on_n_uncensored_tokens": int(len(df_5m_unc)),
        "target_trained": target_col,
        "feature_names": V2_ALL_FEATURES,
        "scaler_mean": [round(float(x), 6) for x in final_scaler.mean_],
        "scaler_scale": [round(float(x), 6) for x in final_scaler.scale_],
        "coef": [round(float(x), 6) for x in final_clf.coef_],
        "intercept": round(float(final_clf.intercept_), 6),
        "weights_by_feature": {f: round(float(w), 4) for f, w in sorted(zip(V2_ALL_FEATURES, final_clf.coef_), key=lambda kv: abs(kv[1]), reverse=True)},
    }
    frozen_json_bytes = json.dumps(frozen_v2_obj, indent=2).encode("utf-8")
    frozen_v2_obj["frozen_sha256"] = hashlib.sha256(frozen_json_bytes).hexdigest()
    (MODELS_V2_DIR / "v2_frozen_model.json").write_text(json.dumps(frozen_v2_obj, indent=2), encoding="utf-8")
    logger.info(f"FROZEN V2 MODEL LOCKED: sha256={frozen_v2_obj['frozen_sha256']}")

    # ==========================================================================
    # SECTION 11: COVARIATE-MATCHED MAYHEM MODE STUDY (`CONTROL_GROUP_V2.csv`)
    # ==========================================================================
    df_1m_all = df_early[df_early["obs_horizon"] == "1m"].set_index("mint")
    mayhem_df = df_tm[df_tm["mayhem_enabled"] == 1].copy()
    std_df = df_tm[df_tm["mayhem_enabled"] == 0].copy()

    used_std = set()
    matched_pairs = []
    for _, m_row in mayhem_df.iterrows():
        m_mint = m_row["mint"]
        m_1m_buyers = float(df_1m_all.loc[m_mint, "unique_buyers_cum"]) if m_mint in df_1m_all.index else 0.0
        best_s = None
        best_dist = 1e18
        for _, s_row in std_df.iterrows():
            s_mint = s_row["mint"]
            if s_mint in used_std:
                continue
            s_1m_buyers = float(df_1m_all.loc[s_mint, "unique_buyers_cum"]) if s_mint in df_1m_all.index else 0.0
            # Standardized multi-covariate distance: launch time, initial mcap, 1m activity, narrative, SOL regime
            dt_hrs = abs(float(m_row["created_timestamp_ms"]) - float(s_row["created_timestamp_ms"])) / 3_600_000.0
            dmcap = abs(float(m_row["initial_mcap_usd"]) - float(s_row["initial_mcap_usd"])) / 200.0
            dact = abs(m_1m_buyers - s_1m_buyers) * 1.5
            dnarr = 0.0 if m_row["narrative_category"] == s_row["narrative_category"] else 4.0
            dist = dt_hrs * 0.25 + dmcap + dact + dnarr
            if dist < best_dist:
                best_dist = dist
                best_s = s_row
        if best_s is not None:
            used_std.add(best_s["mint"])
            matched_pairs.append({
                "pair_type": "MAYHEM_VS_COVARIATE_MATCHED_STANDARD",
                "focal_mint": m_mint,
                "focal_symbol": m_row["symbol"],
                "control_mint": best_s["mint"],
                "control_symbol": best_s["symbol"],
                "focal_narrative": m_row["narrative_category"],
                "control_narrative": best_s["narrative_category"],
                "launch_gap_hours": round(abs(float(m_row["created_timestamp_ms"]) - float(best_s["created_timestamp_ms"])) / 3_600_000.0, 2),
                "focal_init_mcap_usd": m_row["initial_mcap_usd"],
                "control_init_mcap_usd": best_s["initial_mcap_usd"],
                "focal_buyers_5m": m_row["unique_buyers_5m"],
                "control_buyers_5m": best_s["unique_buyers_5m"],
                "focal_mult_4h": m_row["reliable_market_mult_4h"],
                "control_mult_4h": best_s["reliable_market_mult_4h"],
                "focal_hit_2x_4h": m_row["hit_2x_4h"],
                "control_hit_2x_4h": best_s["hit_2x_4h"],
                "focal_sim_net_ret_4h_pct": m_row["sim_4h_net_ret_pct"],
                "control_sim_net_ret_4h_pct": best_s["sim_4h_net_ret_pct"],
            })

    df_ctrl_v2 = pd.DataFrame(matched_pairs)

    # Save all core V2 CSV deliverables!
    outputs = {
        "EARLY_SIGNALS_V2.csv": df_early,
        "TOKEN_METRICS_V2.csv": df_tm,
        "CONTROL_GROUP_V2.csv": df_ctrl_v2,
        "WALLET_CLUSTERS_V2.csv": pd.DataFrame(clusters_rows),
        "INSIDER_ANALYSIS_V2.csv": pd.DataFrame(insider_rows),
        "SUPPLY_CONCENTRATION_V2.csv": pd.DataFrame(supply_rows),
        "REALIZED_PNL_V2.csv": pd.DataFrame(fifo_pnl_rows),
        "WALK_FORWARD_RESULTS.csv": pd.DataFrame(wf_rows),
        "MODEL_COMPARISON.csv": pd.DataFrame(model_comp_rows),
    }
    for fname, dfo in outputs.items():
        dfo.to_csv(V2_DIR / fname, index=False, encoding="utf-8-sig")
        logger.info(f"Wrote {fname}: {len(dfo)} rows × {len(dfo.columns)} cols")

    # Save structured summary for reports
    mayhem_stat = {}
    if len(df_ctrl_v2) >= 5:
        valid_m = df_ctrl_v2.dropna(subset=["focal_mult_4h", "control_mult_4h"])
        if len(valid_m) >= 5:
            u_st, p_v = stats.mannwhitneyu(valid_m["focal_mult_4h"], valid_m["control_mult_4h"], alternative="two-sided")
            mayhem_stat = {
                "n_matched_pairs": int(len(valid_m)),
                "mayhem_median_4h_mult": round(float(valid_m["focal_mult_4h"].median()), 4),
                "standard_median_4h_mult": round(float(valid_m["control_mult_4h"].median()), 4),
                "mayhem_2x_4h_rate": round(float(valid_m["focal_hit_2x_4h"].mean()), 4),
                "standard_2x_4h_rate": round(float(valid_m["control_hit_2x_4h"].mean()), 4),
                "mannwhitney_p_value": round(float(p_v), 6),
            }

    v2_summary = {
        "chronological_dataset_total": int(len(df_tm)),
        "early_signals_total_rows": int(len(df_early)),
        "leakage_violations": violations,
        "uncensored_4h_count": int(len(df_5m_unc)),
        "censored_24h_count": int((df_tm["status_24h"] == "censored").sum()),
        "base_rates_5m": {
            "hit_2x_1h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_2x_1h"].dropna().mean()), 4),
            "hit_3x_1h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_3x_1h"].dropna().mean()), 4),
            "hit_2x_4h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_2x_4h"].dropna().mean()), 4),
            "hit_3x_4h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_3x_4h"].dropna().mean()), 4),
            "hit_5x_4h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_5x_4h"].dropna().mean()), 4),
            "hit_2x_24h": round(float(df_early[df_early["obs_horizon"] == "5m"]["hit_2x_24h"].dropna().mean()), 4),
        },
        "mayhem_matched_study": mayhem_stat,
        "frozen_model": frozen_v2_obj,
    }
    (CACHE_DIR / "v2_core_summary.json").write_text(json.dumps(v2_summary, indent=2), encoding="utf-8")
    logger.info("Saved cache/v2_core_summary.json.")

if __name__ == "__main__":
    main()
