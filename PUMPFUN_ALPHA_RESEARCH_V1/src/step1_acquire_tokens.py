"""
STEP 1: Comprehensive Token Universe & SOL Market Context Acquisition (30-Day Window).
Collects:
- GRUPA A (NEW TOKENS): Tokens launched on pump.fun within [WINDOW_START_MS, WINDOW_END_MS] across all outcomes (massive winners, mid-pumps, rugs, dead/illiquid control tokens, migrated & unmigrated).
- GRUPA B (PUMP EVENTS): All pump.fun tokens experiencing major price surges during [WINDOW_START_MS, WINDOW_END_MS], including older tokens launched prior to WINDOW_START_MS.
- Hourly & Daily SOL/USDT klines from Binance for 30-day Market Context.
- GeckoTerminal & DexScreener trending/boosted/PumpSwap pools for cross-source completeness.

Includes disk caching, rate-limit handling, retries, and structured logging.
"""
import asyncio
import aiohttp
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import (
    BASE_DIR, RAW_DIR, CREATORS_CACHE_DIR, LOGS_DIR,
    WINDOW_START_MS, WINDOW_END_MS, RESEARCH_START_UTC, RESEARCH_END_UTC,
    PUMPFUN_V3_BASE, DEXSCREENER_BASE, GECKOTERMINAL_BASE, BINANCE_BASE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step1_acquire.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step1")

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
                        await asyncio.sleep(1.2 * (attempt + 1))
                    else:
                        return None
            except Exception as e:
                await asyncio.sleep(0.8 * (attempt + 1))
    return None

async def harvest_pumpfun_coins(session: aiohttp.ClientSession, sem: asyncio.Semaphore) -> dict:
    cache_file = RAW_DIR / "pumpfun_universe_raw.json"
    if cache_file.exists():
        logger.info(f"Loading cached universe from {cache_file}")
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if len(data) >= 2500:
            return data

    coins_by_mint = {}

    def ingest_list(items, tag):
        if not isinstance(items, list):
            return 0
        added = 0
        for c in items:
            if isinstance(c, dict) and c.get("mint"):
                m = c["mint"]
                if m not in coins_by_mint:
                    c["_discovery_source"] = tag
                    coins_by_mint[m] = c
                    added += 1
                else:
                    # keep richer fields if present
                    for k, v in c.items():
                        if v is not None and coins_by_mint[m].get(k) is None:
                            coins_by_mint[m][k] = v
        return added

    # 1. Core global sweeps across sort orders & completion status
    sweep_configs = [
        ("market_cap", "DESC", None, 25),
        ("market_cap", "DESC", "true", 25),
        ("market_cap", "DESC", "false", 25),
        ("ath_market_cap", "DESC", None, 25),
        ("ath_market_cap", "DESC", "true", 25),
        ("ath_market_cap", "DESC", "false", 25),
        ("last_trade_timestamp", "DESC", None, 20),
        ("last_trade_timestamp", "DESC", "true", 15),
        ("created_timestamp", "DESC", None, 25),
        ("created_timestamp", "DESC", "true", 20),
    ]

    tasks = []
    for sort_col, order, comp, pages in sweep_configs:
        for page in range(pages):
            offset = page * 50
            comp_q = f"&complete={comp}" if comp is not None else ""
            url = f"{PUMPFUN_V3_BASE}/coins?offset={offset}&limit=50&sort={sort_col}&order={order}&includeNsfw=true{comp_q}"
            tag = f"sweep_{sort_col}_{comp}"
            tasks.append((tag, url))

    logger.info(f"Executing {len(tasks)} primary sweep requests...")
    batch_size = 40
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        res_list = await asyncio.gather(*[fetch_json(session, u, sem) for _, u in batch])
        for (tag, _), res in zip(batch, res_list):
            ingest_list(res, tag)
        await asyncio.sleep(0.15)
    logger.info(f"After primary sweeps: {len(coins_by_mint)} unique tokens.")

    # 2. Alphanumeric + narrative search sweeps across sort=ath_market_cap, market_cap, created_timestamp
    # This eliminates top-offset truncation and samples broadly across the entire 30-day window!
    queries = list("abcdefghijklmnopqrstuvwxyz0123456789") + [
        "ai", "agent", "gpt", "claude", "grok", "dog", "cat", "pepe", "frog",
        "trump", "elon", "musk", "meme", "sol", "pump", "chad", "wojak",
        "moon", "baby", "mini", "meta", "chill", "fart", "goat", "pnut",
        "act", "quant", "anime", "game", "bot", "coin", "official", "real"
    ]
    search_tasks = []
    for q in queries:
        for sort_col, pages in [("ath_market_cap", 4), ("market_cap", 3), ("created_timestamp", 3), ("last_trade_timestamp", 2)]:
            for p in range(pages):
                offset = p * 50
                url = f"{PUMPFUN_V3_BASE}/coins?offset={offset}&limit=50&sort={sort_col}&order=DESC&searchTerm={q}&includeNsfw=true"
                search_tasks.append((f"search_{q}_{sort_col}", url))

    logger.info(f"Executing {len(search_tasks)} stratified search queries...")
    for i in range(0, len(search_tasks), 50):
        batch = search_tasks[i:i+50]
        res_list = await asyncio.gather(*[fetch_json(session, u, sem) for _, u in batch])
        for (tag, _), res in zip(batch, res_list):
            ingest_list(res, tag)
        if (i // 50) % 5 == 0:
            logger.info(f"Progress {i}/{len(search_tasks)} -> {len(coins_by_mint)} unique tokens")
        await asyncio.sleep(0.1)

    # 3. Expand via Creator Histories (crucial: pulls unbiased failed/dead/stagnant coins launched across all 30 days!)
    # Select 350 diverse creators from our 30-day tokens & winners
    creators_seen = []
    seen_set = set()
    for c in coins_by_mint.values():
        cr = c.get("creator")
        cts = c.get("created_timestamp") or 0
        if cr and cr not in seen_set and (WINDOW_START_MS <= cts <= WINDOW_END_MS or (c.get("ath_market_cap") or 0) > 50000):
            seen_set.add(cr)
            creators_seen.append(cr)
        if len(creators_seen) >= 400:
            break

    logger.info(f"Fetching creator launch histories for {len(creators_seen)} creators (unbiased 30d control & serial dev data)...")
    creator_summary = {}
    for i in range(0, len(creators_seen), 40):
        batch_cr = creators_seen[i:i+40]
        urls = [f"{PUMPFUN_V3_BASE}/coins-v2/user-created-coins/{cr}?offset=0&limit=50&includeNsfw=true" for cr in batch_cr]
        res_list = await asyncio.gather(*[fetch_json(session, u, sem) for u in urls])
        for cr, res in zip(batch_cr, res_list):
            if isinstance(res, dict) and isinstance(res.get("coins"), list):
                creator_summary[cr] = {
                    "creator": cr,
                    "total_created_count": res.get("count", len(res["coins"])),
                    "sampled_coins_count": len(res["coins"]),
                    "coin_mints": [x.get("mint") for x in res["coins"] if x.get("mint")]
                }
                ingest_list(res["coins"], "creator_history_expansion")
        await asyncio.sleep(0.1)

    with open(CREATORS_CACHE_DIR / "creator_histories_seed.json", "w", encoding="utf-8") as f:
        json.dump(creator_summary, f)

    # 4. Also check DexScreener boosts/profiles & GeckoTerminal trending/new/pumpswap pools
    extra_mints = set()
    ds_boosts = await fetch_json(session, f"{DEXSCREENER_BASE}/token-boosts/top/v1", sem)
    ds_profiles = await fetch_json(session, f"{DEXSCREENER_BASE}/token-profiles/latest/v1", sem)
    for ds_list in [ds_boosts, ds_profiles]:
        if isinstance(ds_list, list):
            for item in ds_list:
                if item.get("chainId") == "solana" and str(item.get("tokenAddress", "")).endswith("pump"):
                    extra_mints.add(item["tokenAddress"])

    for gt_path in [
        "networks/solana/trending_pools?page=1",
        "networks/solana/trending_pools?page=2",
        "networks/solana/dexes/pumpswap/pools?page=1",
        "networks/solana/dexes/pumpswap/pools?page=2",
        "networks/solana/dexes/pump-fun/pools?page=1",
        "networks/solana/dexes/pump-fun/pools?page=2",
    ]:
        gt_res = await fetch_json(session, f"{GECKOTERMINAL_BASE}/{gt_path}", sem)
        if isinstance(gt_res, dict) and isinstance(gt_res.get("data"), list):
            for pool in gt_res["data"]:
                rel = pool.get("relationships", {}).get("base_token", {}).get("data", {}).get("id", "")
                if rel.startswith("solana_"):
                    m_addr = rel.replace("solana_", "")
                    if m_addr.endswith("pump"):
                        extra_mints.add(m_addr)

    missing_extra = [m for m in extra_mints if m not in coins_by_mint]
    logger.info(f"Cross-source DexScreener/GeckoTerminal discovered {len(extra_mints)} pump mints ({len(missing_extra)} new).")
    # Search missing mints via searchTerm
    for i in range(0, len(missing_extra), 25):
        batch_m = missing_extra[i:i+25]
        res_list = await asyncio.gather(*[
            fetch_json(session, f"{PUMPFUN_V3_BASE}/coins?offset=0&limit=5&searchTerm={m}&includeNsfw=true", sem)
            for m in batch_m
        ])
        for res in res_list:
            ingest_list(res, "cross_dex_discovery")

    logger.info(f"TOTAL UNIQUE PUMP.FUN TOKENS HARVESTED: {len(coins_by_mint)}")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(coins_by_mint, f)

    return coins_by_mint

async def harvest_sol_market_context(session: aiohttp.ClientSession, sem: asyncio.Semaphore):
    # Fetch 1h SOLUSDT klines across the entire 30-day window (720 hours = 1 request of limit=1000!)
    url_1h = f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&startTime={WINDOW_START_MS - 7*86400*1000}&endTime={WINDOW_END_MS}&limit=1000"
    klines_1h = await fetch_json(session, url_1h, sem)
    url_1d = f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1d&startTime={WINDOW_START_MS - 14*86400*1000}&endTime={WINDOW_END_MS}&limit=60"
    klines_1d = await fetch_json(session, url_1d, sem)

    out = {"sol_1h": klines_1h or [], "sol_1d": klines_1d or []}
    with open(RAW_DIR / "sol_market_context.json", "w", encoding="utf-8") as f:
        json.dump(out, f)
    logger.info(f"Saved SOLUSDT market context: {len(out['sol_1h'])} hourly bars, {len(out['sol_1d'])} daily bars.")
    return out

async def main():
    t0 = time.time()
    warsaw_tz = ZoneInfo("Europe/Warsaw")
    meta = {
        "research_window_start_utc": RESEARCH_START_UTC.isoformat(),
        "research_window_end_utc": RESEARCH_END_UTC.isoformat(),
        "research_window_start_warsaw": RESEARCH_START_UTC.astimezone(warsaw_tz).isoformat(),
        "research_window_end_warsaw": RESEARCH_END_UTC.astimezone(warsaw_tz).isoformat(),
        "execution_started_utc": datetime.now(timezone.utc).isoformat(),
        "timezone_storage": "UTC",
        "timezone_presentation": "Europe/Warsaw (CET UTC+1 / CEST UTC+2)",
    }
    with open(BASE_DIR / "research_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    sem = asyncio.Semaphore(12)
    connector = aiohttp.TCPConnector(limit=20, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        coins_by_mint = await harvest_pumpfun_coins(session, sem)
        await harvest_sol_market_context(session, sem)

    # Summarize Group A (created within 30d window) vs older active/pumped tokens
    in_30d = 0
    older_active_30d = 0
    migrated_30d = 0
    high_ath_30d = 0
    for m, c in coins_by_mint.items():
        cts = c.get("created_timestamp") or 0
        lts = c.get("last_trade_timestamp") or 0
        ath_ts = c.get("ath_market_cap_timestamp") or 0
        ath_mc = float(c.get("ath_market_cap") or c.get("usd_market_cap") or 0)
        if WINDOW_START_MS <= cts <= WINDOW_END_MS:
            in_30d += 1
            if c.get("complete"):
                migrated_30d += 1
            if ath_mc >= 15000:
                high_ath_30d += 1
        elif lts >= WINDOW_START_MS or ath_ts >= WINDOW_START_MS:
            older_active_30d += 1

    logger.info(
        f"Summary in {time.time()-t0:.1f}s: Total={len(coins_by_mint)} | "
        f"Group A (New 30d)={in_30d} (Migrated={migrated_30d}, ATH>=$15k={high_ath_30d}) | "
        f"Older Active/Pumped in 30d={older_active_30d}"
    )

if __name__ == "__main__":
    asyncio.run(main())
