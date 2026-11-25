"""
STANDALONE PAPER TRADING ENGINE V2 (`src/paper_trader_v2.py`) — ZERO REAL TRANSACTIONS.
Never connects a wallet, never signs transactions, never submits orders.

Modes:
  python src/paper_trader_v2.py --mode scan      # Scans live 3m-8m old Pump.fun launches, scores with Frozen V2, logs immutable snapshots
  python src/paper_trader_v2.py --mode evaluate  # Evaluates logged alerts across 15m, 1h, 4h, and 24h horizons (preserving PENDING_CENSORED if not elapsed)
"""
import argparse
import asyncio
import aiohttp
import hashlib
import json
import math
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from config_v2 import (
    PAPER_DIR, MODELS_V2_DIR, SOLANA_CHAIN_ID,
    PUMPFUN_V3_BASE, BINANCE_BASE, CONFIRMED_TECHNICAL_ADDRESSES
)
from temporal_integrity_v2 import (
    get_causal_entry_price,
    candle_close_time_ms,
    filter_candles_strictly_inside_horizon,
    CausalHistoryTracker,
)
from step3_core_pipeline_v2 import extract_causal_features_at_horizon, explain_v2_score

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

LEDGER_JSONL = PAPER_DIR / "paper_alerts_ledger.jsonl"
ALERTS_CSV = PAPER_DIR / "paper_alerts.csv"

def load_frozen_v2_model() -> dict:
    p = MODELS_V2_DIR / "v2_frozen_model.json"
    if not p.exists():
        raise FileNotFoundError(f"Frozen V2 model not found at {p}. Run step3_core_pipeline_v2.py first.")
    m = json.loads(p.read_text(encoding="utf-8"))
    # Verify integrity hash
    check_copy = {k: v for k, v in m.items() if k != "frozen_sha256"}
    calc_hash = hashlib.sha256(json.dumps(check_copy, indent=2).encode("utf-8")).hexdigest()
    assert calc_hash == m["frozen_sha256"], "Frozen V2 model SHA-256 mismatch!"
    return m

def score_with_frozen_v2(feat_dict: dict, model: dict) -> float:
    x = np.array([float(feat_dict.get(f, 0.0)) for f in model["feature_names"]], dtype=np.float64)
    mean = np.array(model["scaler_mean"], dtype=np.float64)
    scale = np.array(model["scaler_scale"], dtype=np.float64)
    x_std = np.clip((x - mean) / scale, -6.0, 6.0)
    z = float(x_std @ np.array(model["coef"], dtype=np.float64) + float(model["intercept"]))
    prob = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z))))
    return round(prob * 100.0, 2)

async def fetch_json(session, url, sem):
    for att in range(3):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    await asyncio.sleep(0.6 * (att + 1))
            except Exception:
                await asyncio.sleep(0.5)
    return None

async def run_live_scan(min_age_sec: int = 180, max_age_sec: int = 600, max_tokens: int = 40):
    model = load_frozen_v2_model()
    now_ms = int(time.time() * 1000)
    sem = asyncio.Semaphore(8)
    tracker = CausalHistoryTracker()

    existing_mints = set()
    if LEDGER_JSONL.exists():
        for line in LEDGER_JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing_mints.add(json.loads(line)["mint"])

    conn = aiohttp.TCPConnector(limit=12, ssl=False, force_close=True)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        # Get current SOL price
        kl = await fetch_json(session, f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&limit=25", sem)
        sol_px = float(kl[-1][4]) if kl else 70.0
        sol_r24 = ((sol_px / float(kl[0][4])) - 1.0) * 100.0 if (kl and len(kl) >= 24) else 0.0

        # Scan recent chronological launches (~offset 0..350 covers last ~18 minutes)
        candidates = []
        for off in range(0, 350, 50):
            batch = await fetch_json(session, f"{PUMPFUN_V3_BASE}/coins?offset={off}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true", sem)
            if isinstance(batch, list):
                for c in batch:
                    cts = int(c.get("created_timestamp") or 0)
                    age_s = (now_ms - cts) / 1000.0
                    if min_age_sec <= age_s <= max_age_sec and c.get("mint") and c["mint"] not in existing_mints:
                        candidates.append(c)
            await asyncio.sleep(0.15)

        candidates = sorted(candidates, key=lambda x: int(x["created_timestamp"]))[:max_tokens]
        alerts_logged = []

        for c in candidates:
            m = c["mint"]
            cts = int(c["created_timestamp"])
            sig_ms = int(time.time() * 1000)
            r_tr, r_c1m = await asyncio.gather(
                fetch_json(session, f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{m}?limit=100&after=1-0-0-{max(0, cts-5000)}", sem),
                fetch_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=1m&to={sig_ms}", sem),
            )
            trades = (r_tr or {}).get("trades", [])
            c_1m = (r_c1m or {}).get("candles", [])

            tok_tech = set(CONFIRMED_TECHNICAL_ADDRESSES.keys())
            for fld in ["bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address"]:
                if c.get(fld):
                    tok_tech.add(c[fld])

            pack = extract_causal_features_at_horizon(
                c, trades, c_1m, cts, sig_ms, sol_px, round(sol_r24, 3), tracker, 1, tok_tech
            )
            feat = pack["features"]
            pot_v2 = score_with_frozen_v2(feat, model)
            reasons = explain_v2_score(feat, pot_v2, pack["manipulation_risk_v2"], pack["insider_supply_risk_v2"])

            alert_rec = {
                "mint": m,
                "symbol": (c.get("symbol") or "").strip(),
                "name": (c.get("name") or "").strip(),
                "alert_timestamp_utc": datetime.fromtimestamp(sig_ms / 1000.0, tz=timezone.utc).isoformat(),
                "created_timestamp_ms": cts,
                "signal_timestamp_ms": sig_ms,
                "data_max_timestamp_ms": pack["data_max_timestamp_ms"],
                "pump_potential_v2": pot_v2,
                "manipulation_risk_v2": pack["manipulation_risk_v2"],
                "insider_supply_risk_v2": pack["insider_supply_risk_v2"],
                "alert_tier": "WATCHLIST_HIGH_POTENTIAL" if (pot_v2 >= 58.0 and pack["manipulation_risk_v2"] < 60.0) else "MONITOR_BASELINE",
                "entry_price_usd": pack["entry_price_usd"],
                "implied_liquidity_usd": pack["implied_liquidity_usd"],
                "unique_buyers": int(feat["unique_buyers_cum"]),
                "independent_buyer_velocity": feat["independent_buyer_velocity"],
                "same_slot_bundle_wallets": int(feat["same_slot_bundle_wallets_at_T"]),
                "score_reasons": reasons,
                "feature_snapshot": feat,
                "eval_15m_status": "PENDING_CENSORED",
                "eval_15m_ret_pct": None,
                "eval_1h_status": "PENDING_CENSORED",
                "eval_1h_ret_pct": None,
                "eval_4h_status": "PENDING_CENSORED",
                "eval_4h_ret_pct": None,
                "eval_24h_status": "PENDING_CENSORED",
                "eval_24h_ret_pct": None,
            }
            alerts_logged.append(alert_rec)

    if alerts_logged:
        with open(LEDGER_JSONL, "a", encoding="utf-8") as f:
            for rec in alerts_logged:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    await evaluate_logged_alerts()
    return len(alerts_logged)

async def evaluate_logged_alerts():
    if not LEDGER_JSONL.exists():
        return
    lines = [json.loads(line) for line in LEDGER_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    now_ms = int(time.time() * 1000)
    sem = asyncio.Semaphore(8)

    conn = aiohttp.TCPConnector(limit=12, ssl=False, force_close=True)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        for rec in lines:
            sig_ms = int(rec["signal_timestamp_ms"])
            entry_px = float(rec["entry_price_usd"])
            m = rec["mint"]

            # Fetch 1m & 15m candles up to now_ms if any horizon has newly matured
            needs_check = any(
                rec[f"eval_{h}_status"] == "PENDING_CENSORED" and now_ms >= sig_ms + h_ms
                for h, h_ms in [("15m", 900_000), ("1h", 3_600_000), ("4h", 14_400_000), ("24h", 86_400_000)]
            )
            if not needs_check:
                continue

            r_1m, r_15m = await asyncio.gather(
                fetch_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=1m&to={min(now_ms, sig_ms + 3*3600_000)}", sem),
                fetch_json(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=15m&to={min(now_ms, sig_ms + 25*3600_000)}", sem),
            )
            c_1m = (r_1m or {}).get("candles", [])
            c_15m = (r_15m or {}).get("candles", [])

            for h_lbl, h_ms in [("15m", 900_000), ("1h", 3_600_000), ("4h", 14_400_000), ("24h", 86_400_000)]:
                end_ms = sig_ms + h_ms
                if now_ms < end_ms:
                    rec[f"eval_{h_lbl}_status"] = "PENDING_CENSORED"
                    rec[f"eval_{h_lbl}_ret_pct"] = None
                    continue
                bars = filter_candles_strictly_inside_horizon(c_1m, "1m", sig_ms, end_ms) if h_ms <= 3_600_000 else filter_candles_strictly_inside_horizon(c_15m, "15m", sig_ms, end_ms)
                term_px = float(bars[-1]["close"]) if (bars and float(bars[-1].get("close") or 0) > 0) else entry_px
                rec[f"eval_{h_lbl}_status"] = "EVALUATED_COMPLETE"
                rec[f"eval_{h_lbl}_ret_pct"] = round(((term_px / max(entry_px, 1e-11)) - 1.0) * 100.0, 2)

    # Rewrite updated ledger & flat CSV
    with open(LEDGER_JSONL, "w", encoding="utf-8") as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    flat_rows = [{k: v for k, v in rec.items() if k != "feature_snapshot"} for rec in lines]
    pd.DataFrame(flat_rows).to_csv(ALERTS_CSV, index=False, encoding="utf-8-sig")

def main():
    parser = argparse.ArgumentParser(description="PumpFun Alpha V2 Paper Trading Engine (Zero Real Transactions)")
    parser.add_argument("--mode", choices=["scan", "evaluate"], default="scan")
    parser.add_argument("--max-tokens", type=int, default=35)
    args = parser.parse_args()
    if args.mode == "scan":
        n = asyncio.run(run_live_scan(max_tokens=args.max_tokens))
        print(f"Paper trading scan logged {n} live token snapshots to {ALERTS_CSV}")
    else:
        asyncio.run(evaluate_logged_alerts())
        print(f"Paper trading evaluation updated {ALERTS_CSV}")

if __name__ == "__main__":
    main()
