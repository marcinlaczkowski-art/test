"""
STEP 2: Deep Historical Price (Candles), Millisecond Trade Reconstruction, DexScreener Pool Enrichment,
and Stratified Cohort + Control Group Construction.

Reconstructs for ~500 stratified tokens (out of 8,462+ harvested tokens):
- Group A Pump Candidates (200 tokens launched in 30d window across 2x..100x+ tiers)
- Group B Legacy / Stagnation / Multi-Wave Candidates (80 older pump.fun tokens active/pumping in 30d window + $COOL case check)
- Matched Control Group (220 tokens launched in the same 30d day/hour/SOL-regime windows that failed to pump, including 'false-positive looking' launches with socials/descriptions)

Fetches and caches per token:
1. Launch 1-minute candles (`res=1m&to=created+195m`)
2. 30-day 4-hour candles (`res=4h`, covering 800h = 33.3 days)
3. Genesis chronological trades from `t=0s` (up to 300 trades covering `t=0..30m`)
4. Peak / ATH window trades + Latest trades (for seller/insider profit & dump reconstruction)
5. DexScreener batch pool enrichment (liquidity USD, pair address, DEX venue, socials, boosts)
"""
import asyncio
import aiohttp
import json
import time
import logging
import numpy as np
from pathlib import Path

from config import (
    RAW_DIR, TRADES_CACHE_DIR, CANDLES_CACHE_DIR, LOGS_DIR,
    WINDOW_START_MS, WINDOW_END_MS, SOLANA_CHAIN_ID,
    PUMPFUN_V3_BASE, DEXSCREENER_BASE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step2_candles_trades.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step2")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

async def fetch_json(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore, retries: int = 3):
    for attempt in range(retries):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    elif resp.status in (429, 500, 502, 503, 504):
                        await asyncio.sleep(1.0 * (attempt + 1))
                    else:
                        return None
            except Exception:
                await asyncio.sleep(0.7 * (attempt + 1))
    return None

def is_spoofed_wash_pool(c: dict) -> bool:
    ath = float(c.get("ath_market_cap") or 0.0)
    cur = float(c.get("usd_market_cap") or c.get("market_cap_usd") or 0.0)
    liq = float(c.get("canonical_pool_liquidity_usd") or 0.0)
    comp = bool(c.get("complete"))
    # 1. Unmigrated bonding curve cannot legitimately exceed ~$180k USD mcap (graduates at ~85 SOL curve cap)
    if not comp and max(ath, cur) > 180_000:
        return True
    # 2. Extreme spoofed Raydium/CLMM single-tick wash pools: >$50M ATH with <$50k cur & <$10k canonical liquidity
    if ath > 50_000_000 and cur < 50_000 and liq < 10_000:
        return True
    # 3. >$3M ATH with virtually zero canonical liquidity (<$1,500) and <$10k current mcap
    if ath > 3_000_000 and cur < 10_000 and liq < 1_500:
        return True
    return False

def select_stratified_cohort(coins_by_mint: dict):
    group_a_all = []
    older_candidates = []

    for m, c in coins_by_mint.items():
        if not c.get("initialized", True) or is_spoofed_wash_pool(c):
            continue
        cts = int(c.get("created_timestamp") or 0)
        lts = int(c.get("last_trade_timestamp") or 0)
        ath_ts = int(c.get("ath_market_cap_timestamp") or 0)
        ath_mc = float(c.get("ath_market_cap") or c.get("usd_market_cap") or c.get("market_cap_usd") or 0.0)
        cur_mc = float(c.get("usd_market_cap") or c.get("market_cap_usd") or 0.0)
        best_mc = max(ath_mc, cur_mc)

        if WINDOW_START_MS <= cts <= WINDOW_END_MS:
            group_a_all.append((best_mc, cts, m, c))
        elif cts > 0 and cts < WINDOW_START_MS and (lts >= WINDOW_START_MS or ath_ts >= WINDOW_START_MS or str(c.get("symbol", "")).strip().upper() in ("COOL", "$COOL")):
            older_candidates.append((best_mc, cts, m, c))

    group_a_all.sort(key=lambda x: x[0], reverse=True)
    older_candidates.sort(key=lambda x: x[0], reverse=True)

    logger.info(f"Universe breakdown: Group A (30d launches) = {len(group_a_all)}, Older active in 30d = {len(older_candidates)}")

    # 1. Select Group A Pump Candidates (~210 tokens: top 160 by peak mcap + 50 mid-tier $8k-$35k pumps)
    # Note: standard pump.fun initial bonding curve mcap at ~70-100 SOL price is ~$2,800 - $4,200 USD (28-30 SOL virtual reserve * SOL_USD / 1.073B * 1B)
    pump_a_high = [x for x in group_a_all if x[0] >= 12000]
    pump_a_mid = [x for x in group_a_all if 6500 <= x[0] < 12000]

    selected_pumps_a = pump_a_high[:175]
    if len(pump_a_mid) > 45:
        idxs = np.linspace(0, len(pump_a_mid) - 1, 45, dtype=int)
        selected_pumps_a.extend([pump_a_mid[i] for i in idxs])
    else:
        selected_pumps_a.extend(pump_a_mid)

    selected_mints = {x[2]: "group_a_pump_candidate" for x in selected_pumps_a}

    # 2. Select Older Group B Candidates (~75 tokens: top 65 active/high-mcap + any $COOL tokens)
    cool_tokens = [x for x in older_candidates if str(x[3].get("symbol", "")).strip().upper().replace("$", "") == "COOL"]
    selected_older = older_candidates[:65]
    for ct in cool_tokens[:5]:
        if ct[2] not in {x[2] for x in selected_older}:
            selected_older.append(ct)
    for x in selected_older:
        if x[2] not in selected_mints:
            selected_mints[x[2]] = "group_b_legacy_candidate"

    # 3. Matched Control Group (Propensity/Time-Matched Non-Pumps in 30d window: best_mc < $7,500 & not complete)
    # Using <$7,500 accounts for late-Oct ~$102 SOL initial curve cap (~$3.5k-$4.8k) so controls never reached reliable 2x
    control_pool = [
        x for x in group_a_all
        if x[2] not in selected_mints and x[0] < 7500 and not x[3].get("complete", False)
    ]
    # Sort control pool by created_timestamp for nearest-neighbor temporal matching
    control_pool.sort(key=lambda x: x[1])
    control_ts = np.array([x[1] for x in control_pool], dtype=np.int64)
    used_control = set()
    control_matches = {}

    # Also ensure half of controls have at least some initial engagement / social metadata if available ("promising-looking flops")
    for best_mc, target_cts, pump_mint, pump_c in selected_pumps_a:
        if len(control_pool) == 0:
            break
        pos = int(np.searchsorted(control_ts, target_cts))
        # Search local window around pos for unused control token
        best_idx = None
        best_dist = 10**18
        for offset in range(-40, 41):
            cand_idx = pos + offset
            if 0 <= cand_idx < len(control_pool):
                cmint = control_pool[cand_idx][2]
                if cmint in used_control:
                    continue
                dist = abs(int(control_pool[cand_idx][1]) - target_cts)
                # Slight bonus if it has trades (last_trade_timestamp > created_timestamp) so we have active failed tokens too, not just 0-tx ghosts
                cand_c = control_pool[cand_idx][3]
                has_activity = 1 if (cand_c.get("last_trade_timestamp") or 0) > (cand_c.get("created_timestamp") or 0) else 0
                adj_dist = dist - (has_activity * 3600_000)
                if adj_dist < best_dist:
                    best_dist = adj_dist
                    best_idx = cand_idx
        if best_idx is not None:
            cmint = control_pool[best_idx][2]
            used_control.add(cmint)
            selected_mints[cmint] = "control_matched"
            control_matches[cmint] = {
                "matched_to_pump_mint": pump_mint,
                "pump_created_ts": target_cts,
                "control_created_ts": int(control_pool[best_idx][1]),
                "time_diff_minutes": round(abs(int(control_pool[best_idx][1]) - target_cts) / 60000.0, 2)
            }

    logger.info(
        f"Selected Deep Cohort: Total={len(selected_mints)} | "
        f"Group A Pump Candidates={len(selected_pumps_a)} | "
        f"Group B Older Candidates={len(selected_older)} | "
        f"Matched Controls={len(control_matches)}"
    )
    return selected_mints, control_matches

async def fetch_token_candles_and_trades(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    mint: str,
    coin: dict,
    role: str
):
    c_file = CANDLES_CACHE_DIR / f"{mint}.json"
    t_file = TRADES_CACHE_DIR / f"{mint}.json"

    created_ts = int(coin.get("created_timestamp") or 0)
    ath_ts = int(coin.get("ath_market_cap_timestamp") or 0)

    # 1. Candles (1m launch window + 4h 33-day window + 15m recent/mid window)
    if not c_file.exists():
        to_1m = created_ts + 195 * 60 * 1000 if created_ts > 0 else WINDOW_END_MS
        u_1m = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={to_1m}"
        u_4h = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=4h"
        # If created in 30d window and pumped later, also grab 15m around ATH or first 50 hours
        to_15m = max(ath_ts + 6 * 3600 * 1000, created_ts + 48 * 3600 * 1000) if created_ts >= WINDOW_START_MS else WINDOW_END_MS
        to_15m = min(to_15m, WINDOW_END_MS + 3600 * 1000)
        u_15m = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=15m&to={to_15m}"

        r_1m, r_15m, r_4h = await asyncio.gather(
            fetch_json(session, u_1m, sem),
            fetch_json(session, u_15m, sem),
            fetch_json(session, u_4h, sem),
        )
        candle_payload = {
            "mint": mint,
            "candles_1m": (r_1m or {}).get("candles", []),
            "candles_15m": (r_15m or {}).get("candles", []),
            "candles_4h": (r_4h or {}).get("candles", []),
            "supplyUsed": (r_4h or r_1m or {}).get("supplyUsed"),
        }
        with open(c_file, "w", encoding="utf-8") as f:
            json.dump(candle_payload, f)

    # 2. Chronological Genesis Trades (t=0..30m, up to 250 trades) + ATH/Latest Trades
    if not t_file.exists():
        genesis_trades = []
        start_ts = max(0, created_ts - 10000) if role != "group_b_legacy_candidate" else max(0, WINDOW_START_MS - 3600_000)
        cursor_key = f"1-0-0-{start_ts}"
        max_pages = 3 if role == "group_a_pump_candidate" else 2

        for page in range(max_pages):
            u_tr = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after={cursor_key}"
            r_tr = await fetch_json(session, u_tr, sem)
            batch = (r_tr or {}).get("trades", [])
            if not batch:
                break
            genesis_trades.extend(batch)
            cursor_key = batch[-1]["ordinalKey"]
            last_t_ms = int(batch[-1].get("blockTimeMs") or 0)
            # If we already passed created_ts + 30 minutes or got < 100 trades, stop paging genesis
            if len(batch) < 100 or (created_ts > 0 and role != "group_b_legacy_candidate" and last_t_ms > created_ts + 32 * 60 * 1000):
                break

        # Also fetch latest 100 trades (captures exits, creator sells, top holder profit taking, current state)
        u_latest = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100"
        r_latest = await fetch_json(session, u_latest, sem)
        latest_trades = (r_latest or {}).get("trades", [])

        # Also if ATH timestamp is distinct from genesis & latest, fetch 100 trades right around ATH!
        ath_trades = []
        if ath_ts >= WINDOW_START_MS and abs(ath_ts - created_ts) > 35 * 60 * 1000:
            u_ath = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{ath_ts - 10 * 60 * 1000}"
            r_ath = await fetch_json(session, u_ath, sem)
            ath_trades = (r_ath or {}).get("trades", [])

        # Deduplicate by ordinalKey and sort chronologically ascending
        by_key = {}
        for t in genesis_trades + ath_trades + latest_trades:
            ok = t.get("ordinalKey")
            if ok:
                by_key[ok] = t
        merged = sorted(by_key.values(), key=lambda x: (int(x.get("blockTimeMs") or 0), int(x.get("blockId") or 0), int(x.get("txIndex") or 0), int(x.get("eventIndex") or 0)))

        with open(t_file, "w", encoding="utf-8") as f:
            json.dump({
                "mint": mint,
                "role": role,
                "genesis_fetched": len(genesis_trades),
                "latest_fetched": len(latest_trades),
                "ath_fetched": len(ath_trades),
                "total_unique_trades": len(merged),
                "trades": merged
            }, f)

async def enrich_dexscreener(session: aiohttp.ClientSession, sem: asyncio.Semaphore, mints: list) -> dict:
    ds_cache = RAW_DIR / "dexscreener_enrichment.json"
    out = {}
    if ds_cache.exists():
        with open(ds_cache, "r", encoding="utf-8") as f:
            out = json.load(f)

    missing_mints = [m for m in mints if m not in out]
    logger.info(f"Fetching DexScreener batch pool/liquidity/social enrichment for {len(missing_mints)} uncached cohort tokens...")
    for i in range(0, len(missing_mints), 30):
        chunk = missing_mints[i:i+30]
        url = f"{DEXSCREENER_BASE}/tokens/v1/solana/{','.join(chunk)}"
        pairs = await fetch_json(session, url, sem)
        if isinstance(pairs, list):
            for p in pairs:
                base_addr = p.get("baseToken", {}).get("address")
                if not base_addr:
                    continue
                liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
                prev_liq = float((out.get(base_addr, {}).get("liquidity") or {}).get("usd") or -1.0)
                if liq > prev_liq:
                    out[base_addr] = p
        await asyncio.sleep(0.2)

    with open(ds_cache, "w", encoding="utf-8") as f:
        json.dump(out, f)
    logger.info(f"DexScreener returned active DEX/curve pair records for {len(out)}/{len(mints)} tokens.")
    return out

async def main():
    t0 = time.time()
    universe_path = RAW_DIR / "pumpfun_universe_raw.json"
    with open(universe_path, "r", encoding="utf-8") as f:
        coins_by_mint = json.load(f)

    sem = asyncio.Semaphore(16)
    connector = aiohttp.TCPConnector(limit=24, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        # Ensure $COOL tokens are explicitly queried too (per Section 9 reference)
        cool_res = await fetch_json(session, f"{PUMPFUN_V3_BASE}/coins?offset=0&limit=50&sort=ath_market_cap&order=DESC&searchTerm=COOL&includeNsfw=true", sem)
        if isinstance(cool_res, list):
            added_cool = 0
            for c in cool_res:
                if c.get("mint") and c["mint"] not in coins_by_mint:
                    c["_discovery_source"] = "explicit_cool_case_search"
                    coins_by_mint[c["mint"]] = c
                    added_cool += 1
            if added_cool > 0:
                with open(universe_path, "w", encoding="utf-8") as f:
                    json.dump(coins_by_mint, f)
                logger.info(f"Added {added_cool} explicit $COOL search tokens -> Universe size: {len(coins_by_mint)}")

        selected_mints, control_matches = select_stratified_cohort(coins_by_mint)
        with open(RAW_DIR / "cohort_selection.json", "w", encoding="utf-8") as f:
            json.dump({"selected_mints": selected_mints, "control_matches": control_matches}, f, indent=2)

        cohort_list = list(selected_mints.items())
        await enrich_dexscreener(session, sem, [m for m, _ in cohort_list])

        logger.info(f"Starting candle & millisecond trade acquisition for {len(cohort_list)} cohort tokens...")
        batch_sz = 25
        for i in range(0, len(cohort_list), batch_sz):
            batch = cohort_list[i:i+batch_sz]
            await asyncio.gather(*[
                fetch_token_candles_and_trades(session, sem, m, coins_by_mint[m], role)
                for m, role in batch
            ])
            if (i // batch_sz) % 2 == 0 or i + batch_sz >= len(cohort_list):
                logger.info(f"Cohort progress: {min(i+batch_sz, len(cohort_list))}/{len(cohort_list)} tokens processed ({time.time()-t0:.1f}s)")

    logger.info(f"Step 2 completed in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    asyncio.run(main())
