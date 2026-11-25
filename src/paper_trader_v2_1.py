"""
PAPER TRADING V2.1 (`src/paper_trader_v2_1.py` — Section 10):
- Uses the EXACT SAME `UnifiedFeatureEngine` (`src/feature_engine.py`) and populated
  `UnifiedStateBundle` checkpoint (`state_post_wf_v2_1.json`) as Training, Validation, and OOT!
- Strictly read-only paper simulation: ZERO real transactions, ZERO wallet connections, ZERO signing.
- Saves complete immutable `feature_snapshot.json` files for every paper alert and maintains
  `paper_trading/paper_alerts_v2_1.csv` with `15m`, `1h`, `4h`, and `24h` post-alert monitoring columns.
"""
import asyncio
import aiohttp
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import expit

from config_v2_1 import (
    PAPER_DIR, SNAPSHOTS_DIR, CHECKPOINTS_DIR, FROZEN_BASELINES_DIR,
    PUMPFUN_V3_BASE, BINANCE_BASE, SOLANA_CHAIN_ID, INTERVAL_MS,
)
from state_trackers_v2_1 import UnifiedStateBundle
from feature_engine import UnifiedFeatureEngine, classify_token_narrative

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}


def score_v2_1_frozen(snapshot: dict, frozen_v2_1: dict, use_pruned: bool = True) -> float:
    spec = frozen_v2_1["pruned_model"] if use_pruned and "pruned_model" in frozen_v2_1 else frozen_v2_1
    mv = snapshot["model_vector"]
    x = np.array([mv[f] for f in spec["feature_names"]], dtype=float)
    mu = np.array(spec["scaler_mean"], dtype=float)
    sc = np.array(spec["scaler_scale"], dtype=float)
    coef = np.array(spec["coef"], dtype=float)
    z = float(np.dot((x - mu) / sc, coef) + float(spec["intercept"]))
    return round(float(expit(np.clip(z, -25.0, 25.0))) * 100.0, 2)


def _sync_http_get(url: str):
    import ssl
    import urllib.request
    import urllib.error
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=7.0, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


async def fetch_polite_json(session, url: str, sem: asyncio.Semaphore, retries: int = 3):
    for att in range(retries):
        async with sem:
            status, data = await asyncio.to_thread(_sync_http_get, url)
            if status == 200:
                return data
            elif status == 429:
                await asyncio.sleep(1.2 * (att + 1))
            elif status in (400, 404):
                return None
            else:
                await asyncio.sleep(0.4 * (att + 1))
    return None


async def run_paper_trading_scan_v2_1(max_candidates: int = 25) -> pd.DataFrame:
    ckpt_path = CHECKPOINTS_DIR / "state_post_wf_v2_1.json"
    frozen_v2_1 = json.loads((FROZEN_BASELINES_DIR / "v2_1_frozen_model.json").read_text(encoding="utf-8"))
    state = UnifiedStateBundle.load_checkpoint(ckpt_path)
    engine = UnifiedFeatureEngine(save_snapshots_dir=SNAPSHOTS_DIR)

    sem = asyncio.Semaphore(3)
    conn = aiohttp.TCPConnector(limit=8, ssl=False, force_close=True)
    now_ms = int(time.time() * 1000)

    rows = []
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        # Refresh strictly closed SOL 1h bars up to `now_ms`
        kl = await fetch_polite_json(session, f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&limit=48", sem)
        if isinstance(kl, list) and kl:
            state.market.ingest_binance_klines(kl, interval="1h")

        # Fetch recent live launches (~2m to 12m old) without any mcap/ATH filter!
        live_coins = []
        for off in (40, 90):
            batch = await fetch_polite_json(
                session,
                f"{PUMPFUN_V3_BASE}/coins?offset={off}&limit=30&sort=created_timestamp&order=DESC&includeNsfw=true",
                sem,
            )
            if isinstance(batch, list):
                for c in batch:
                    cts = int(c.get("created_timestamp") or 0)
                    age_s = (now_ms - cts) / 1000.0
                    if 60.0 <= age_s <= 900.0:
                        live_coins.append(c)

        seen_m = set()
        dedup_live = []
        for c in sorted(live_coins, key=lambda x: int(x.get("created_timestamp") or 0)):
            if c["mint"] not in seen_m:
                seen_m.add(c["mint"])
                dedup_live.append(c)
        dedup_live = dedup_live[:max_candidates]

        for c in dedup_live:
            mint = c["mint"]
            cts = int(c["created_timestamp"])
            eval_ts = int(time.time() * 1000)
            sig_ts = min(eval_ts, cts + 180_000) if (eval_ts - cts) >= 180_000 else eval_ts

            state.tickers.register_launch(cts, mint, c.get("symbol") or "", classify_token_narrative(c.get("name"), c.get("symbol"), c.get("description")))

            u_1m = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={sig_ts}"
            u_tr = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{max(0, cts - 5000)}"
            r_1m, r_tr = await asyncio.gather(
                fetch_polite_json(session, u_1m, sem),
                fetch_polite_json(session, u_tr, sem),
            )
            c1m = sorted((r_1m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0))
            trades = (r_tr or {}).get("trades", [])

            snap = engine.compute_snapshot(
                coin=c,
                trades=trades,
                candles_1m=c1m,
                signal_ts_ms=sig_ts,
                state=state,
                mode="paper_trading",
                acquired_at_ms=sig_ts,
                persist_json=True,
            )

            pot_pruned = score_v2_1_frozen(snap, frozen_v2_1, use_pruned=True)
            pot_full = score_v2_1_frozen(snap, frozen_v2_1, use_pruned=False)
            mv = snap["model_vector"]
            ind_growth = round(mv["independent_buyer_velocity"] * mv["buyer_acceleration_ratio"], 4)

            known_flags = [
                mv["wallet_history_known_flag"],
                mv["creator_history_known_flag"],
                mv["ticker_history_known_flag"],
                mv["supply_valid_flag"],
            ]
            data_comp = round((0.6 + 0.1 * sum(known_flags)), 2)
            conf_lbl = "medium_confidence" if data_comp >= 0.8 and len(trades) >= 3 else "low_confidence"

            is_alert = int(pot_pruned >= 52.0 and snap["manipulation_risk_score"] < 65.0 and snap["supply_status"] == "ok")
            reasons = []
            if mv["independent_buyer_velocity"] >= 1.0:
                reasons.append(f"indep_buyer_vel={mv['independent_buyer_velocity']:.2f}/m")
            if mv["dip_absorption_ratio"] > 1.05:
                reasons.append(f"dip_absorption={mv['dip_absorption_ratio']:.2f}")
            if mv["smart_wallets_count_num"] >= 1:
                reasons.append(f"smart_wallets={int(mv['smart_wallets_count_num'])}")
            if not reasons:
                reasons.append("baseline_chronological_scan_below_alert_threshold" if not is_alert else "composite_v2_1_score")

            snap_file = SNAPSHOTS_DIR / f"{mint}_{sig_ts}_feature_snapshot.json"
            rows.append({
                "alert_timestamp_utc": datetime.fromtimestamp(sig_ts / 1000.0, tz=timezone.utc).isoformat(),
                "signal_timestamp_ms": sig_ts,
                "mint": mint,
                "symbol": snap["symbol"],
                "alert_triggered": is_alert,
                "entry_price_usd": snap["entry_price_usd"],
                "entry_price_source": snap["price_source"],
                "implied_liquidity_usd": snap["implied_liquidity_usd"],
                "pump_potential_v2_1_pruned_score": pot_pruned,
                "pump_potential_v2_1_full_score": pot_full,
                "independent_buyer_growth_score": ind_growth,
                "manipulation_risk_score": snap["manipulation_risk_score"],
                "insider_risk_score": snap["insider_supply_risk_score"],
                "supply_status": snap["supply_status"],
                "confidence": conf_lbl,
                "data_completeness": data_comp,
                "alert_reason": "; ".join(reasons),
                "feature_snapshot_path": str(snap_file.relative_to(PAPER_DIR.parent)),
                # Forward live monitoring placeholders (strictly `censored_pending` until horizon elapses!)
                "return_15m_pct": "censored_pending",
                "return_1h_pct": "censored_pending",
                "return_4h_pct": "censored_pending",
                "return_24h_pct": "censored_pending",
                "max_up_pct": "censored_pending",
                "max_down_pct": "censored_pending",
            })
            await asyncio.sleep(0.1)

    df = pd.DataFrame(rows)
    out_csv = PAPER_DIR / "paper_alerts_v2_1.csv"
    df.to_csv(out_csv, index=False)
    return df


if __name__ == "__main__":
    df_out = asyncio.run(run_paper_trading_scan_v2_1())
    print(f"Paper Trading V2.1 logged {len(df_out)} live candidates ({int(df_out['alert_triggered'].sum()) if len(df_out) else 0} alerts) -> paper_trading/paper_alerts_v2_1.csv")
