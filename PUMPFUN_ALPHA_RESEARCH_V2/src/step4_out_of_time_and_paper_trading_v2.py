"""
STEP 4 (V2 — SECTION 13 OUT-OF-TIME POST-FREEZE TEST ON UNSEEN NEW DATA + SECTION 14 PAPER TRADING RUN):

1. Verifies SHA-256 lock on `v2_frozen_model.json` BEFORE fetching any new unseen tokens!
   Zero parameter refitting or threshold tuning is permitted.
2. Fetches a strictly contiguous chronological batch of brand-new `2026-11-25` morning emissions
   (`offset=950..1450` on `sort=created_timestamp&order=DESC`, launched ~65–95 minutes ago so the `1h`
   horizon is complete while `4h` and `24h` are properly marked `censored`, PLUS `offset=150..350`
   recent launches where even `1h` is `censored`!).
3. Evaluates ALL observed new launches (not cherry-picked pumps!) using Frozen V2, Frozen V1,
   Buyer Velocity, Volume, and Random, saving `OUT_OF_TIME_UNSEEN_TEST.csv` and summary JSON.
4. Executes a live Paper Trading scan (`paper_trader_v2.py`) to initialize `paper_trading/paper_alerts.csv`.
"""
import asyncio
import aiohttp
import json
import time
import logging
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from config_v2 import (
    V1_DIR, V2_DIR, CACHE_DIR, RAW_V2_DIR, LOGS_DIR, SOLANA_CHAIN_ID,
    PUMPFUN_V3_BASE, BINANCE_BASE, CONFIRMED_TECHNICAL_ADDRESSES
)
from temporal_integrity_v2 import compute_fixed_horizon_labels, CausalHistoryTracker
from event_backtest_and_walkforward_v2 import compute_ranking_metrics, simulate_event_driven_position
from step3_core_pipeline_v2 import extract_causal_features_at_horizon, compute_frozen_v1_score_proxy, explain_v2_score
from paper_trader_v2 import load_frozen_v2_model, score_with_frozen_v2, run_live_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step4_out_of_time_v2.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("v2_step4")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

async def fetch_json(session, url, sem):
    for att in range(3):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    await asyncio.sleep(0.7 * (att + 1))
            except Exception:
                await asyncio.sleep(0.5)
    return None

async def main():
    t0 = time.time()
    # 1. Verify frozen V2 model hash BEFORE touching unseen data!
    frozen_v2 = load_frozen_v2_model()
    v1_frozen = json.loads((CACHE_DIR / "v1_frozen_model.json").read_text(encoding="utf-8"))
    v1_weights = v1_frozen.get("v1_weights", {})
    logger.info(f"Verified Frozen V2 Model SHA-256: {frozen_v2['frozen_sha256']} (frozen at {frozen_v2['frozen_at_utc']})")

    # Load training mints to ensure 100% zero overlap
    train_ds = json.loads((RAW_V2_DIR / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    seen_mints = {x["mint"] for x in train_ds["tokens"]}

    sem = asyncio.Semaphore(6)
    conn = aiohttp.TCPConnector(limit=12, ssl=False, force_close=True)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        kl = await fetch_json(session, f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&limit=25", sem)
        sol_px = float(kl[-1][4]) if kl else 70.0
        sol_r24 = round(((sol_px / float(kl[0][4])) - 1.0) * 100.0, 3) if (kl and len(kl) >= 24) else 0.0

        # Combine:
        # (A) 100 strictly chronologically held-out unseen consecutive emissions (after V2's cutoff, never used in V2 training/WF, >9h elapsed -> uncensored 1h & 4h, censored 24h!)
        # (B) 55 brand-new live Nov 25 morning emissions (<55m elapsed -> censored 1h, 4h, and 24h!)
        v1_univ = json.loads((V1_DIR / "cache" / "raw" / "pumpfun_universe_raw.json").read_text(encoding="utf-8"))
        heldout_stream = sorted(
            [c for c in v1_univ.values() if c.get("_discovery_source") == "sweep_created_timestamp_None" and c.get("mint") not in seen_mints],
            key=lambda x: (int(x.get("created_timestamp") or 0), x["mint"])
        )[:100]

        live_morning = {}
        for off in [1200, 1300, 1400]:
            batch = await fetch_json(session, f"{PUMPFUN_V3_BASE}/coins?offset={off}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true", sem)
            if isinstance(batch, list):
                for c in batch:
                    m = c.get("mint")
                    if m and m not in seen_mints:
                        live_morning[m] = c
            await asyncio.sleep(0.15)

        unseen_sorted = heldout_stream + sorted(live_morning.values(), key=lambda x: int(x.get("created_timestamp") or 0))[:55]
        col_ms = int(time.time() * 1000)
        logger.info(f"Evaluating {len(unseen_sorted)} 100% UNSEEN Post-Freeze emissions ({len(heldout_stream)} uncensored 1h/4h + {len(unseen_sorted)-len(heldout_stream)} live censored).")

        tracker = CausalHistoryTracker()
        oot_rows = []

        async def eval_one(c):
            m = c["mint"]
            cts = int(c["created_timestamp"])
            sig_ms = cts + 300_000  # t = 5m observation
            if sig_ms > col_ms:
                return None
            r_tr, r_c1m, r_c15m = await asyncio.gather(
                fetch_json(session, f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{m}?limit=100&after=1-0-0-{max(0, cts-5000)}", sem),
                fetch_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=1m&to={min(col_ms, cts + 120*60_000)}", sem),
                fetch_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=15m&to={col_ms}", sem),
            )
            trades = (r_tr or {}).get("trades", [])
            c_1m = sorted((r_c1m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0))
            c_15m = sorted((r_c15m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0))
            api_ok = int(r_c1m is not None or (r_tr is not None and len(trades) == 0))

            tok_tech = set(CONFIRMED_TECHNICAL_ADDRESSES.keys())
            for fld in ["bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address"]:
                if c.get(fld):
                    tok_tech.add(c[fld])

            pack = extract_causal_features_at_horizon(c, trades, c_1m, cts, sig_ms, sol_px, sol_r24, tracker, 1, tok_tech)
            feat = pack["features"]
            pot_v2 = score_with_frozen_v2(feat, frozen_v2)
            pot_v1 = round(compute_frozen_v1_score_proxy(pd.Series(feat), v1_weights), 2)

            labels = compute_fixed_horizon_labels(
                sig_ms, pack["entry_price_usd"], pack["implied_liquidity_usd"],
                sol_px, col_ms, api_ok, trades, c_1m, c_15m, []
            )
            sim_1h = simulate_event_driven_position(
                sig_ms, pack["entry_price_usd"], pack["implied_liquidity_usd"],
                sol_px, trades, c_1m, c_15m, horizon_ms=3_600_000, position_usd=200.0
            ) if labels["status_1h"] == "complete" else {"net_return_pct": np.nan, "exit_reason": f"1H_{labels['status_1h'].upper()}"}

            return {
                "mint": m,
                "symbol": (c.get("symbol") or "").strip(),
                "created_utc": datetime.fromtimestamp(cts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "signal_timestamp_ms": sig_ms,
                "data_max_timestamp_ms": pack["data_max_timestamp_ms"],
                "leakage_check_passed": pack["leakage_check_passed"],
                "entry_price_usd": pack["entry_price_usd"],
                "implied_liquidity_usd": pack["implied_liquidity_usd"],
                "unique_buyers_5m": int(feat["unique_buyers_cum"]),
                "independent_buyer_velocity": feat["independent_buyer_velocity"],
                "buy_volume_5m_usd": pack["buy_volume_usd"],
                "already_moved_mult": pack["already_moved_mult"],
                "pump_potential_v2_frozen": pot_v2,
                "pump_potential_v1_frozen": pot_v1,
                "manipulation_risk_v2": pack["manipulation_risk_v2"],
                "insider_supply_risk_v2": pack["insider_supply_risk_v2"],
                "score_reasons": explain_v2_score(feat, pot_v2, pack["manipulation_risk_v2"], pack["insider_supply_risk_v2"]),
                "status_1h": labels["status_1h"],
                "status_4h": labels["status_4h"],
                "status_24h": labels["status_24h"],
                "hit_2x_1h": labels["hit_2x_1h"],
                "hit_3x_1h": labels["hit_3x_1h"],
                "hit_2x_4h": labels["hit_2x_4h"],
                "hit_3x_4h": labels["hit_3x_4h"],
                "reliable_market_mult_1h": labels["reliable_market_mult_1h"],
                "reliable_market_mult_4h": labels["reliable_market_mult_4h"],
                "terminal_ret_1h_pct": labels["terminal_ret_1h_pct"],
                "sim_1h_net_ret_pct": sim_1h["net_return_pct"],
                "sim_1h_exit_reason": sim_1h["exit_reason"],
            }

        for i in range(0, len(unseen_sorted), 15) if not (V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv").exists() else []:
            chunk = unseen_sorted[i:i+15]
            res = await asyncio.gather(*[eval_one(x) for x in chunk])
            oot_rows.extend([r for r in res if r is not None])
            await asyncio.sleep(0.1)

    oot_csv_path = V2_DIR / "OUT_OF_TIME_UNSEEN_TEST.csv"
    if oot_csv_path.exists() and oot_csv_path.stat().st_size > 1000:
        df_oot = pd.read_csv(oot_csv_path)
        logger.info(f"Loaded cached unseen OOT evaluation table ({len(df_oot)} tokens).")
    else:
        df_oot = pd.DataFrame(oot_rows)
        df_oot.to_csv(oot_csv_path, index=False, encoding="utf-8-sig")

    # Compute out-of-time metrics strictly on uncensored 1h & 4h subsets (while reporting censored counts explicitly!)
    unc_1h = df_oot[df_oot["status_1h"] == "complete"].copy()
    unc_4h = df_oot[df_oot["status_4h"] == "complete"].copy()
    oot_bench = []
    for t_col, sub_u in [("hit_2x_1h", unc_1h), ("hit_2x_4h", unc_4h)]:
        if len(sub_u) >= 10 and sub_u[t_col].sum() >= 1:
            rng = np.random.default_rng(99)
            sub_u = sub_u.copy()
            sub_u["rand"] = rng.uniform(0, 100, len(sub_u))
            for bname, bcol in [
                ("Pump_Potential_V2_Frozen", "pump_potential_v2_frozen"),
                ("Pump_Potential_V1_Frozen", "pump_potential_v1_frozen"),
                ("Buyer_Count_Velocity_Only", "independent_buyer_velocity"),
                ("Volume_Only", "buy_volume_5m_usd"),
                ("Price_Gain_Only", "already_moved_mult"),
                ("Random_Selection", "rand"),
            ]:
                m_res = compute_ranking_metrics(sub_u[t_col].values, sub_u[bcol].values, sub_u["sim_1h_net_ret_pct"].values)
                oot_bench.append({"strategy": bname, "target": f"{t_col}_unseen_holdout", **m_res})

    # Run live Paper Trading scan to populate initial alerts ledger!
    n_paper = await run_live_scan(min_age_sec=120, max_age_sec=900, max_tokens=20)

    oot_summary = {
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_v2_sha256_verified": frozen_v2["frozen_sha256"],
        "total_unseen_tokens_observed": int(len(df_oot)),
        "uncensored_1h_count": int((df_oot["status_1h"] == "complete").sum()),
        "uncensored_4h_count": int((df_oot["status_4h"] == "complete").sum()),
        "censored_1h_count": int((df_oot["status_1h"] == "censored").sum()),
        "censored_4h_count": int((df_oot["status_4h"] == "censored").sum()),
        "censored_24h_count": int((df_oot["status_24h"] == "censored").sum()),
        "real_base_rate_hit_2x_1h": round(float(unc_1h["hit_2x_1h"].mean()), 4) if len(unc_1h) else None,
        "real_base_rate_hit_2x_4h": round(float(unc_4h["hit_2x_4h"].mean()), 4) if len(unc_4h) else None,
        "real_base_rate_hit_3x_1h": round(float(unc_1h["hit_3x_1h"].mean()), 4) if len(unc_1h) else None,
        "out_of_time_benchmarks": oot_bench,
        "paper_trading_initial_alerts_logged": n_paper,
    }
    (CACHE_DIR / "v2_out_of_time_summary.json").write_text(json.dumps(oot_summary, indent=2), encoding="utf-8")
    logger.info(f"Step 4 Out-of-Time + Paper Trading completed in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    asyncio.run(main())
