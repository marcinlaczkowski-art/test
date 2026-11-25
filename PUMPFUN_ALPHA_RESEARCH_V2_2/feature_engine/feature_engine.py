"""
SHARED FEATURE ENGINE V2.2 (`feature_engine/feature_engine.py` — Sections 3, 11, 12):
- Single shared implementation across `training`, `validation`, `oot`, `paper_trading`, and `live`.
- Zero `min(acquired_at_ms, signal_ts_ms)` time clamping! Integrates directly with `TemporalIntegrityLedger`.
- Formal `FEATURE_DEFINITIONS_V2_2` registry documenting every feature's name, definition, source,
  required inputs, lookback, cutoff rule, and missing-data policy.
- Covers all 5 Hypotheses (H1–H5), Narrative vs Social Separation (`UNKNOWN` historical X/Telegram),
  and SOL + Pump.fun Ecosystem Market Regime (`BULL` / `BEAR` / `SIDEWAYS`, `HIGH_VOL` / `LOW_VOL`).
"""
import bisect
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import INTERVAL_MS, PUMPFUN_INIT_VIRTUAL_SOL, PUMPFUN_INIT_VIRTUAL_TOKENS
from data_integrity.temporal_ledger import TemporalIntegrityLedger
from amm_reconstruction.amm_reconstructor import deduplicate_and_order_swaps, reconstruct_reserve_state_at
from wallet_intelligence.wallet_intel_v2_2 import (
    WalletIntelligenceEngineV22,
    compute_chronological_fifo_for_token,
    build_token_excluded_addresses,
)

# Formal Feature Registry (Section 12 requirement: every feature has explicit metadata)
FEATURE_DEFINITIONS_V2_2 = {
    "new_buyers_15s": {
        "definition": "Count of first-time human buyers in [cutoff - 15s, cutoff]",
        "source": "pumpfun_v3_trades", "required_inputs": ["trades"], "lookback": "15s",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms", "missing_handling": "UNKNOWN_IF_NO_TAPE",
    },
    "new_buyers_30s": {
        "definition": "Count of first-time human buyers in [cutoff - 30s, cutoff]",
        "source": "pumpfun_v3_trades", "required_inputs": ["trades"], "lookback": "30s",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms", "missing_handling": "UNKNOWN_IF_NO_TAPE",
    },
    "new_buyers_60s": {
        "definition": "Count of first-time human buyers in [cutoff - 60s, cutoff]",
        "source": "pumpfun_v3_trades", "required_inputs": ["trades"], "lookback": "60s",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms", "missing_handling": "UNKNOWN_IF_NO_TAPE",
    },
    "buyer_acceleration_ratio": {
        "definition": "Ratio of recent 30s buyer arrival rate to prior [30s..90s] arrival rate",
        "source": "pumpfun_v3_trades", "required_inputs": ["trades"], "lookback": "90s",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms", "missing_handling": "UNKNOWN_IF_NO_TAPE",
    },
    "independent_buyers_estimate": {
        "definition": "Unique buyers minus creator, creator-linked, and multi-wallet cluster/slot duplicates",
        "source": "wallet_intel_v2_2", "required_inputs": ["trades", "wallet_graph"], "lookback": "from_birth",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms & edge.first_seen <= cutoff_ts_ms", "missing_handling": "0_OR_UNKNOWN",
    },
    "cluster_profitable_accum_sol": {
        "definition": "SOL bought by CONFIRMED/PROBABLE clusters with positive prior pre-pump track record",
        "source": "wallet_intel_v2_2", "required_inputs": ["trades", "cluster_track_record"], "lookback": "prior_tokens",
        "cutoff_rule": "outcome_known_at_ms <= cutoff_ts_ms", "missing_handling": "INSUFFICIENT_HISTORY",
    },
    "smart_money_buy_sol": {
        "definition": "SOL bought by wallets with >=3 prior evaluated tokens, >=40% win rate, and >0 FIFO SOL",
        "source": "wallet_intel_v2_2", "required_inputs": ["trades", "wallet_fifo_history"], "lookback": "prior_tokens",
        "cutoff_rule": "outcome_known_at_ms <= cutoff_ts_ms", "missing_handling": "INSUFFICIENT_HISTORY",
    },
    "top5_holder_pct": {
        "definition": "Share of effective supply held by top 5 non-system/non-pool wallets",
        "source": "fifo_supply_ledger", "required_inputs": ["trades", "spl_transfers"], "lookback": "from_birth",
        "cutoff_rule": "event_ts <= cutoff_ts_ms", "missing_handling": "INVALID_SUPPLY_RECONSTRUCTION",
    },
    "absorption_score_raw": {
        "definition": "Independent buyer + buy/sell inflow strength normalized by controlled price advance without linked dump",
        "source": "amm_and_swap_tape", "required_inputs": ["trades", "amm_reserves"], "lookback": "from_birth",
        "cutoff_rule": "blockTimeMs <= cutoff_ts_ms", "missing_handling": "UNKNOWN_IF_INCOMPLETE",
    },
    "narrative_potential_score": {
        "definition": "Lexical + recognizable meme/current-event motif clarity without assuming virality",
        "source": "token_genesis_metadata", "required_inputs": ["name", "symbol", "description"], "lookback": "at_birth",
        "cutoff_rule": "created_timestamp <= cutoff_ts_ms", "missing_handling": "NEUTRAL_UNKNOWN",
    },
    "sol_market_regime": {
        "definition": "Causal SOL trend (BULL/BEAR/SIDEWAYS) and volatility (HIGH_VOL/LOW_VOL) from closed 1h klines",
        "source": "binance_spot_closed_1h", "required_inputs": ["sol_klines_1h"], "lookback": "24h",
        "cutoff_rule": "open_time_ms + 3_600_000 <= cutoff_ts_ms", "missing_handling": "UNKNOWN",
    },
}

NARRATIVE_MOTIFS = [
    ("AI_Agent_Tech", r"\b(ai|agent|gpt|claude|llm|mcp|bot|neural|deepseek|grok|openai|quant|algo)\b"),
    ("Viral_Animal_Meme", r"\b(dog|cat|pepe|frog|pnut|goat|pengu|monkey|ape|shib|capy|otter|shark|moo)\b"),
    ("Current_Event_Macro", r"\b(trump|elon|musk|doge|tariff|fed|sec|vote|president|mars| Polymarket)\b"),
    ("Internet_Culture_Absurd", r"\b(chad|giga|wojak|chill|sigma|aura|rizz|fart|brainrot|npc|meme|trench)\b"),
]


class CausalMarketRegimeTracker:
    """
    Section 11.2 Market Regime & Pump.fun Ecosystem Context Tracker.
    Uses ONLY strictly closed SOL 1h bars (`close_time_ms = open_time_ms + 3_600_000 <= cutoff_ts_ms`)
    and strictly prior ecosystem launches & buy volume (`<= cutoff_ts_ms`).
    """
    def __init__(self):
        self.closed_sol_1h: list[tuple[int, int, float, float, float, float, float]] = []
        self._close_ts: list[int] = []
        self.ecosystem_launches: list[tuple[int, str, str]] = []  # (created_ts_ms, mint, motif)
        self._launch_ts: list[int] = []
        self.ecosystem_swaps_1h: list[tuple[int, float]] = []     # (swap_ts_ms, buy_sol)
        self._swap_ts: list[int] = []

    def ingest_sol_klines_1h(self, raw_klines: list) -> None:
        by_open = {r[1]: r for r in self.closed_sol_1h}
        for k in raw_klines:
            ot = int(k[0])
            ct = ot + INTERVAL_MS["1h"]
            by_open[ot] = (ct, ot, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7]))
        self.closed_sol_1h = sorted(by_open.values(), key=lambda x: x[0])
        self._close_ts = [x[0] for x in self.closed_sol_1h]

    def register_ecosystem_activity(self, created_ts_ms: int, mint: str, motif: str, pre_swaps: list, cutoff_ts_ms: int) -> None:
        idx = bisect.bisect_right(self._launch_ts, created_ts_ms)
        if mint not in {x[1] for x in self.ecosystem_launches[max(0, idx - 5):idx + 5]}:
            self.ecosystem_launches.insert(idx, (int(created_ts_ms), mint, motif))
            self._launch_ts.insert(idx, int(created_ts_ms))
        for tr in pre_swaps:
            tms = int(tr.get("blockTimeMs") or 0)
            if 0 < tms <= cutoff_ts_ms and tr.get("side") == "buy":
                vsol = float(tr.get("valueNative") or 0.0)
                if vsol > 0:
                    s_idx = bisect.bisect_right(self._swap_ts, tms)
                    self.ecosystem_swaps_1h.insert(s_idx, (tms, vsol))
                    self._swap_ts.insert(s_idx, tms)

    def query_regime_at(self, cutoff_ts_ms: int) -> dict:
        idx = bisect.bisect_right(self._close_ts, cutoff_ts_ms) - 1
        if idx < 0:
            return {
                "status": "UNKNOWN",
                "sol_price_usd": "UNKNOWN",
                "sol_ret_6h_pct": "UNKNOWN",
                "sol_ret_24h_pct": "UNKNOWN",
                "sol_realized_vol_24h_pct": "UNKNOWN",
                "sol_1h_volume_usdt": "UNKNOWN",
                "sol_trend_regime": "UNKNOWN",
                "sol_volatility_regime": "UNKNOWN",
                "ecosystem_launches_last_1h": 0,
                "ecosystem_buy_sol_last_1h": 0.0,
                "last_closed_bar_ts_ms": 0,
            }

        cur = self.closed_sol_1h[idx]
        ct_cur = cur[0]
        assert ct_cur <= cutoff_ts_ms, "CRITICAL: Unclosed SOL candle leaked!"
        px_now = cur[5]
        vol_1h = cur[6]

        # 6h and 24h returns & realized hourly return std over last 24 closed bars
        idx_6h = max(0, idx - 6)
        idx_24h = max(0, idx - 24)
        ret_6h = ((px_now / self.closed_sol_1h[idx_6h][5]) - 1.0) * 100.0 if idx >= 6 and self.closed_sol_1h[idx_6h][5] > 0 else None
        ret_24h = ((px_now / self.closed_sol_1h[idx_24h][5]) - 1.0) * 100.0 if idx >= 12 and self.closed_sol_1h[idx_24h][5] > 0 else None

        window_bars = self.closed_sol_1h[max(0, idx - 24):idx + 1]
        if len(window_bars) >= 6:
            closes = [b[5] for b in window_bars]
            h_rets = [(closes[k] / closes[k - 1] - 1.0) * 100.0 for k in range(1, len(closes)) if closes[k - 1] > 0]
            rvol_24h = float(np.std(h_rets) * math.sqrt(24.0)) if h_rets else None
        else:
            rvol_24h = None

        if ret_24h is None:
            trend = "UNKNOWN"
        elif ret_24h >= 2.0:
            trend = "BULL"
        elif ret_24h <= -2.0:
            trend = "BEAR"
        else:
            trend = "SIDEWAYS"

        if rvol_24h is None:
            vol_reg = "UNKNOWN"
        elif rvol_24h >= 4.5:
            vol_reg = "HIGH_VOL"
        else:
            vol_reg = "LOW_VOL"

        # Ecosystem activity in `(cutoff_ts_ms - 1h, cutoff_ts_ms]`
        l_hi = bisect.bisect_right(self._launch_ts, cutoff_ts_ms)
        l_lo = bisect.bisect_left(self._launch_ts, cutoff_ts_ms - INTERVAL_MS["1h"])
        s_hi = bisect.bisect_right(self._swap_ts, cutoff_ts_ms)
        s_lo = bisect.bisect_left(self._swap_ts, cutoff_ts_ms - INTERVAL_MS["1h"])
        eco_sol_1h = sum(x[1] for x in self.ecosystem_swaps_1h[s_lo:s_hi])

        return {
            "status": "OK",
            "sol_price_usd": round(px_now, 4),
            "sol_ret_6h_pct": round(ret_6h, 4) if ret_6h is not None else "UNKNOWN",
            "sol_ret_24h_pct": round(ret_24h, 4) if ret_24h is not None else "UNKNOWN",
            "sol_realized_vol_24h_pct": round(rvol_24h, 4) if rvol_24h is not None else "UNKNOWN",
            "sol_1h_volume_usdt": round(vol_1h, 2),
            "sol_trend_regime": trend,
            "sol_volatility_regime": vol_reg,
            "ecosystem_launches_last_1h": l_hi - l_lo,
            "ecosystem_buy_sol_last_1h": round(eco_sol_1h, 3),
            "last_closed_bar_ts_ms": ct_cur,
        }


def analyze_narrative_and_social_v2_2(
    coin: dict,
    regime_tracker: CausalMarketRegimeTracker,
    cutoff_ts_ms: int,
) -> dict:
    """
    Section 11.1 Narrative & Social Separation:
    NEVER fabricates historical social engagement or treats current followers as historical!
    Explicitly separates `narrative_potential`, `observed_social_traction`, `historical_social_activity`,
    and `unknown_social_activity`.
    """
    name = (coin.get("name") or "").strip()
    symbol = (coin.get("symbol") or "").strip()
    desc = (coin.get("description") or "").strip()
    blob = f"{name} {symbol} {desc}".lower()

    matched_motif = "Unclassified_Novelty"
    for m_name, pat in NARRATIVE_MOTIFS:
        if re.search(pat, blob, flags=re.IGNORECASE):
            matched_motif = m_name
            break

    # Motif repetition density in prior 24h (`< created_timestamp <= cutoff_ts_ms`)
    cts = int(coin.get("created_timestamp") or cutoff_ts_ms)
    hi = bisect.bisect_left(regime_tracker._launch_ts, cts)
    lo = bisect.bisect_left(regime_tracker._launch_ts, cts - INTERVAL_MS["24h"])
    prior_24h = regime_tracker.ecosystem_launches[lo:hi]
    same_motif_24h = sum(1 for x in prior_24h if x[2] == matched_motif) if len(prior_24h) >= 10 else "INSUFFICIENT_ECOSYSTEM_WINDOW"

    # Lexical & clarity score (does NOT prove virality!)
    alpha_sym = re.sub(r"[^a-zA-Z]", "", symbol.lower())
    vow_ratio = sum(1 for c in alpha_sym if c in "aeiouy") / max(1, len(alpha_sym))
    pronounceable = max(0.0, 1.0 - abs(vow_ratio - 0.40) * 1.6)
    has_desc = 1.0 if len(desc) >= 15 else 0.3
    motif_bonus = 0.85 if matched_motif != "Unclassified_Novelty" else 0.45
    narr_potential = round(min(1.0, 0.4 * pronounceable + 0.3 * has_desc + 0.3 * motif_bonus), 4)

    tw = str(coin.get("twitter") or "").strip()
    tg = str(coin.get("telegram") or "").strip()
    web = str(coin.get("website") or "").strip()
    links_cnt = sum(bool(x) for x in (tw, tg, web))

    return {
        "motif_category": matched_motif,
        "motif_prior_24h_count": same_motif_24h,
        "narrative_potential_score": narr_potential,
        "observed_social_traction": "LAUNCH_METADATA_LINKS_PRESENT" if links_cnt > 0 else "NO_LAUNCH_LINKS",
        "launch_links_count": links_cnt,
        "historical_social_activity": "UNKNOWN",  # Unarchived historical X/Telegram impressions/followers are strictly UNKNOWN!
        "social_data_confidence": "LOW_METADATA_ONLY",
    }


class SharedFeatureEngineV22:
    """
    THE SINGLE SHARED FEATURE IMPLEMENTATION FOR:
      - `training`
      - `validation`
      - `oot`
      - `paper_trading`
      - `live`
    """
    def __init__(
        self,
        temporal_ledger: TemporalIntegrityLedger,
        wallet_engine: WalletIntelligenceEngineV22,
        regime_tracker: CausalMarketRegimeTracker,
    ):
        self.temporal = temporal_ledger
        self.wallets = wallet_engine
        self.regime = regime_tracker

    def compute_features(
        self,
        coin: dict,
        trades: list,
        candles_1m: list,
        decision_cutoff_ts_ms: int,
        acquired_at_ms: int,
        mode: str,
        source_id: str = "pumpfun_v3",
        source_health_status: str = "HEALTHY",
        is_tape_complete: bool = True,
        spl_transfers: Optional[list] = None,
        source_published_at_ms: Optional[int] = None,
        has_historical_availability_proof: bool = False,
    ) -> dict:
        mint = str(coin.get("mint") or "")
        cts = int(coin.get("created_timestamp") or 0)

        # Strictly filter trades & closed 1m candles up to `decision_cutoff_ts_ms`
        vis_swaps = deduplicate_and_order_swaps(trades, cutoff_ts_ms=decision_cutoff_ts_ms)
        closed_1m = [
            b for b in (candles_1m or [])
            if int(b.get("openTimeMs") or 0) > 0 and (int(b["openTimeMs"]) + INTERVAL_MS["1m"]) <= decision_cutoff_ts_ms
        ]
        closed_1m.sort(key=lambda b: int(b["openTimeMs"]))

        last_event_ts = max(
            [cts]
            + [int(tr["blockTimeMs"]) for tr in vis_swaps]
            + [int(b["openTimeMs"]) + INTERVAL_MS["1m"] for b in closed_1m]
        )

        # 1. Reconstruct AMM / Bonding-Curve Reserve State at `decision_cutoff_ts_ms`
        amm_state = reconstruct_reserve_state_at(
            coin=coin,
            trades=vis_swaps,
            cutoff_ts_ms=decision_cutoff_ts_ms,
            is_tape_complete_from_genesis=is_tape_complete,
        )

        # 2. Wallet Intelligence 2.0 Pre-Signal Observation & Chronological FIFO/Supply Ledger
        wi_obs = self.wallets.observe_token_pre_signal(coin, vis_swaps, cutoff_ts_ms=decision_cutoff_ts_ms)
        fifo_sup = compute_chronological_fifo_for_token(
            coin=coin,
            trades=vis_swaps,
            spl_transfers=spl_transfers or [],
            mark_price_sol=amm_state.get("mid_price_sol"),
            cutoff_ts_ms=decision_cutoff_ts_ms,
            is_tape_complete=is_tape_complete,
        )
        sup = fifo_sup["supply_metrics"]

        # 3. H1 Buyer Velocity & Acceleration across 15s, 30s, 60s windows
        excl = fifo_sup["excluded_addresses"]
        first_buy_by_w = {}
        buy_sol_15s = 0.0
        buy_sol_30s = 0.0
        buy_sol_60s = 0.0
        buy_sol_tot = 0.0
        sell_sol_tot = 0.0
        max_single_seller_sol = 0.0
        seller_totals = Counter()
        buyer_totals = Counter()

        for tr in vis_swaps:
            tms = int(tr["blockTimeMs"])
            w = str((tr.get("trader") or {}).get("address") or "")
            if not w or w in excl:
                continue
            vsol = float(tr.get("valueNative") or 0.0)
            if tr.get("side") == "buy":
                buy_sol_tot += vsol
                buyer_totals[w] += vsol
                if w not in first_buy_by_w:
                    first_buy_by_w[w] = tms
                if tms >= decision_cutoff_ts_ms - 15_000:
                    buy_sol_15s += vsol
                if tms >= decision_cutoff_ts_ms - 30_000:
                    buy_sol_30s += vsol
                if tms >= decision_cutoff_ts_ms - 60_000:
                    buy_sol_60s += vsol
            elif tr.get("side") == "sell":
                sell_sol_tot += vsol
                seller_totals[w] += vsol

        if seller_totals:
            max_single_seller_sol = max(seller_totals.values())

        new_b_15s = sum(1 for tms in first_buy_by_w.values() if tms >= decision_cutoff_ts_ms - 15_000)
        new_b_30s = sum(1 for tms in first_buy_by_w.values() if tms >= decision_cutoff_ts_ms - 30_000)
        new_b_60s = sum(1 for tms in first_buy_by_w.values() if tms >= decision_cutoff_ts_ms - 60_000)
        prev_b_30_90s = sum(1 for tms in first_buy_by_w.values() if (decision_cutoff_ts_ms - 90_000) <= tms < (decision_cutoff_ts_ms - 30_000))

        # Rate per 30s in [t-30s, t] vs [t-90s, t-30s]
        recent_rate_30s = float(new_b_30s)
        prior_rate_30s = float(prev_b_30_90s) / 2.0
        buyer_accel_ratio = round((recent_rate_30s + 0.5) / (prior_rate_30s + 0.5), 4)
        accel_15_vs_60 = round(((new_b_15s * 4.0) + 0.5) / (float(new_b_60s) + 0.5), 4)

        raw_buys = wi_obs["raw_buy_swaps_count"]
        uniq_buyers = wi_obs["unique_buyers_count"]
        first_time_share = round(uniq_buyers / max(1, raw_buys), 4) if raw_buys > 0 else 0.0
        if buy_sol_tot > 0 and buyer_totals:
            hhi_buy = round(sum((v / buy_sol_tot) ** 2 for v in buyer_totals.values()), 4)
        else:
            hhi_buy = 1.0

        # 4. Price change from genesis & Buy Pressure Absorption (H5)
        genesis_mid_sol = PUMPFUN_INIT_VIRTUAL_SOL / PUMPFUN_INIT_VIRTUAL_TOKENS
        cur_mid_sol = amm_state.get("mid_price_sol")
        if cur_mid_sol and cur_mid_sol > 0:
            price_mult_from_birth = round(cur_mid_sol / genesis_mid_sol, 4)
            price_chg_pct = round((price_mult_from_birth - 1.0) * 100.0, 2)
        else:
            price_mult_from_birth = None
            price_chg_pct = None

        bs_ratio = round((buy_sol_tot + 0.05) / (sell_sol_tot + 0.05), 4)
        creator = str(coin.get("creator") or "")
        creator_sold_sol = seller_totals.get(creator, 0.0)

        # 5. Narrative & Ecosystem Market Regime
        narr = analyze_narrative_and_social_v2_2(coin, self.regime, decision_cutoff_ts_ms)
        reg = self.regime.query_regime_at(decision_cutoff_ts_ms)

        sol_px_usd = float(reg["sol_price_usd"]) if isinstance(reg["sol_price_usd"], (int, float)) else None
        if sol_px_usd is None:
            for tr in reversed(vis_swaps):
                qp = float(tr.get("quotePriceUsd") or 0.0)
                if qp > 5.0:
                    sol_px_usd = qp
                    break

        liq_sol = (2.0 * float(amm_state["virtual_sol_reserve"])) if amm_state.get("virtual_sol_reserve") else None
        liq_usd = round(liq_sol * sol_px_usd, 2) if (liq_sol and sol_px_usd) else None

        feat_done_ms = max(int(acquired_at_ms), int(time.time() * 1000)) if mode in ("live", "paper_trading") else max(int(acquired_at_ms), int(decision_cutoff_ts_ms))
        sig_gen_ms = feat_done_ms

        envelope = self.temporal.validate_and_build_envelope(
            token_mint=mint,
            created_ts_ms=cts,
            event_ts_ms=last_event_ts,
            source_id=source_id,
            acquired_at_ms=acquired_at_ms,
            feature_computed_at_ms=feat_done_ms,
            signal_generated_at_ms=sig_gen_ms,
            mode=mode,
            decision_cutoff_ts_ms=decision_cutoff_ts_ms,
            source_published_at_ms=source_published_at_ms,
            has_historical_availability_proof=has_historical_availability_proof,
        )

        # Cluster concentration in effective supply
        eff_sup = sup.get("effective_supply") or 1_000_000_000.0
        hbals = fifo_sup["holder_balances"]
        cluster_held_toks = sum(
            hbals.get(w, 0.0)
            for cl in wi_obs["active_clusters"]
            for w in cl["wallets"]
        )
        cluster_supply_pct = round(cluster_held_toks / max(1.0, eff_sup) * 100.0, 4) if sup["supply_status"] != "INVALID_SUPPLY_RECONSTRUCTION" else None

        return {
            "envelope": envelope.to_dict(),
            "token_mint": mint,
            "token_symbol": (coin.get("symbol") or "").strip(),
            "token_name": (coin.get("name") or "").strip(),
            "created_timestamp_ms": cts,
            "decision_cutoff_ts_ms": decision_cutoff_ts_ms,
            "token_age_seconds": round((decision_cutoff_ts_ms - cts) / 1000.0, 2) if cts > 0 else None,
            "source_health_status": source_health_status,
            "amm_state": amm_state,
            "liquidity_sol": round(liq_sol, 4) if liq_sol is not None else None,
            "liquidity_usd": liq_usd,
            "sol_price_usd": sol_px_usd,
            "h1_metrics": {
                "raw_buy_count": raw_buys,
                "unique_buyers_count": uniq_buyers,
                "independent_buyers_estimate": wi_obs["independent_buyers_estimate"],
                "new_buyers_15s": new_b_15s,
                "new_buyers_30s": new_b_30s,
                "new_buyers_60s": new_b_60s,
                "buyer_acceleration_ratio": buyer_accel_ratio,
                "accel_15s_vs_60s": accel_15_vs_60,
                "first_time_buyer_share": first_time_share,
                "purchase_hhi_concentration": hhi_buy,
            },
            "h2_metrics": {
                "active_clusters": wi_obs["active_clusters"],
                "cluster_count": len(wi_obs["active_clusters"]),
                "cluster_wallets_count": sum(c["wallet_count"] for c in wi_obs["active_clusters"]),
                "cluster_buy_sol": round(sum(c["buy_sol"] for c in wi_obs["active_clusters"]), 4),
                "cluster_buy_share": round(sum(c["buy_share"] for c in wi_obs["active_clusters"]), 4),
                "profitable_prior_clusters_count": sum(
                    1 for c in wi_obs["active_clusters"]
                    if c["prior_pre_pump_wins"] >= 1 and c["prior_fifo_realized_pnl_sol"] > 0
                ),
                "cluster_prior_fifo_pnl_sol": round(sum(c["prior_fifo_realized_pnl_sol"] for c in wi_obs["active_clusters"]), 4),
            },
            "h3_metrics": {
                "qualified_smart_wallets_count": len(wi_obs["qualified_smart_wallets"]),
                "smart_money_buy_sol": wi_obs["smart_money_buy_sol"],
                "smart_money_buy_share": wi_obs["smart_money_buy_share"],
                "smart_money_prior_realized_pnl_sol": round(
                    sum(w["prior_realized_pnl_sol"] for w in wi_obs["qualified_smart_wallets"]), 4
                ),
                "insufficient_history_buyers_count": wi_obs["insufficient_history_buyers_count"],
            },
            "h4_metrics": {
                "supply_status": sup["supply_status"],
                "top1_pct": sup["top1_pct"],
                "top5_pct": sup["top5_pct"],
                "top10_pct": sup["top10_pct"],
                "top20_pct": sup["top20_pct"],
                "creator_share_pct": sup["creator_share_pct"],
                "creator_sold_sol": round(creator_sold_sol, 4),
                "creator_linked_buyers_count": wi_obs["creator_linked_buyers_count"],
                "same_slot_buyers_count": wi_obs["same_slot_buyers_count"],
                "cluster_supply_pct": cluster_supply_pct,
                "excluded_addresses_count": sup["excluded_system_pool_addresses_count"],
            },
            "h5_metrics": {
                "buy_volume_sol": round(buy_sol_tot, 4),
                "sell_volume_sol": round(sell_sol_tot, 4),
                "buy_sell_ratio": bs_ratio,
                "price_mult_from_birth": price_mult_from_birth,
                "price_change_from_birth_pct": price_chg_pct,
                "real_sol_reserve_delta": amm_state.get("real_sol_reserve"),
                "max_single_seller_sol": round(max_single_seller_sol, 4),
            },
            "narrative": narr,
            "market_regime": reg,
            "_fifo_internal": fifo_sup,
            "_wi_obs_internal": wi_obs,
        }
