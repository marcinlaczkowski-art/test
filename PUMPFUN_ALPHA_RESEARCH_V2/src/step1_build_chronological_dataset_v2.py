"""
STEP 1 (V2 — P0 DATASET REBUILD):
Constructs an outcome-blind, strictly chronological observed token emission dataset.

CRITICAL P0 GUARANTEE:
- ZERO tokens are selected, filtered, or sorted using future ATH, market cap, migration (`complete`),
  future volume, or survival status.
- Combines two strictly outcome-blind chronological strata for Train / Validation / Walk-Forward Test:
  1. `30d_PreKnown_Creator_Chronological_Emissions`: All 30d launches deployed chronologically by creators
     identified strictly via pre-window (<2026-10-25) existence or pure arrival-time (`created_timestamp`) sweep.
     (Spans 2026-10-25 .. 2026-11-24, providing uncensored 1h, 4h, and 24h horizons.)
  2. `Nov24_Contiguous_Consecutive_Emissions`: A contiguous block of 330 consecutive pump.fun emissions
     captured prospectively by `sort=created_timestamp` on 2026-11-24 (~21:57Z–22:18Z), regardless of whether
     they had 0 trades, rugged, lost 99%, or pumped. (>8.5h elapsed -> uncensored 1h & 4h horizons; 24h marked censored.)

Explicitly records `collection_timestamp_ms`, `universe_scope = "observed_chronological_sample"`,
and per-token data completeness flags.
"""
import asyncio
import aiohttp
import json
import shutil
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

from config_v2 import (
    V1_DIR, V2_DIR, RAW_V2_DIR, CANDLES_V2_DIR, TRADES_V2_DIR,
    CREATORS_V2_DIR, LOGS_DIR, SOLANA_CHAIN_ID, PUMPFUN_V3_BASE,
    DEXSCREENER_BASE, BINANCE_BASE, WINDOW_30D_START_MS, V1_END_MS
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step1_chronological_dataset_v2.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("v2_step1")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

async def fetch_json(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore, retries: int = 3):
    for att in range(retries):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    elif resp.status in (429, 500, 502, 503, 504):
                        await asyncio.sleep(0.9 * (att + 1))
                    else:
                        return None
            except Exception:
                await asyncio.sleep(0.6 * (att + 1))
    return None

async def expand_outcome_blind_creators(session: aiohttp.ClientSession, sem: asyncio.Semaphore, arrival_creators: list, v1_cr_db: dict) -> dict:
    out_path = CREATORS_V2_DIR / "outcome_blind_creator_histories.json"
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))

    cr_histories = {}
    missing = []
    for cr in arrival_creators:
        if cr in v1_cr_db and isinstance(v1_cr_db[cr].get("coins_brief"), list):
            cr_histories[cr] = v1_cr_db[cr]
        else:
            missing.append(cr)

    logger.info(f"Fetching full chronological launch lists for {len(missing)} arrival-sampled creators (reused {len(cr_histories)} from cache)...")
    for i in range(0, len(missing), 25):
        batch = missing[i:i+25]
        urls = [f"{PUMPFUN_V3_BASE}/coins-v2/user-created-coins/{cr}?offset=0&limit=50&includeNsfw=true" for cr in batch]
        res_list = await asyncio.gather(*[fetch_json(session, u, sem) for u in urls])
        for cr, res in zip(batch, res_list):
            if isinstance(res, dict) and isinstance(res.get("coins"), list):
                cr_histories[cr] = {
                    "creator": cr,
                    "total_created_count": res.get("count", len(res["coins"])),
                    "coins_full": res["coins"],
                }
        await asyncio.sleep(0.15)

    out_path.write_text(json.dumps(cr_histories), encoding="utf-8")
    return cr_histories

async def acquire_token_history_v2(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    mint: str,
    coin: dict,
    collection_ms: int
):
    c_file = CANDLES_V2_DIR / f"{mint}.json"
    t_file = TRADES_V2_DIR / f"{mint}.json"
    cts = int(coin.get("created_timestamp") or 0)

    # IMPORTANT: In V2 we ALWAYS fetch fresh 15m candles covering [cts, min(collection_ms, cts + 28h)]
    # AND fresh 1m candles covering [cts, min(collection_ms, cts + 195m)] so post-Nov24 tokens get their
    # newly elapsed 8.5h outcomes and 30d tokens have exact 1h, 4h, and 24h closed bars!
    if not c_file.exists():
        to_1m = min(collection_ms, cts + 195 * 60_000) if cts > 0 else collection_ms
        to_15m = min(collection_ms, cts + 28 * 3600_000) if cts > 0 else collection_ms
        u_1m = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={to_1m}"
        u_15m = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=15m&to={to_15m}"
        u_4h = f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{mint}?res=4h&to={collection_ms}"

        r_1m, r_15m, r_4h = await asyncio.gather(
            fetch_json(session, u_1m, sem),
            fetch_json(session, u_15m, sem),
            fetch_json(session, u_4h, sem),
        )
        c_payload = {
            "mint": mint,
            "collection_timestamp_ms": collection_ms,
            "candles_1m": sorted((r_1m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
            "candles_15m": sorted((r_15m or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
            "candles_4h": sorted((r_4h or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
            "api_ok": int(r_1m is not None or r_15m is not None),
        }
        c_file.write_text(json.dumps(c_payload), encoding="utf-8")

    if not t_file.exists():
        # Paginate chronological trades from genesis t=0 up to 300 trades + latest 100 trades for wallet/FIFO reconstruction
        genesis_trades = []
        cursor_key = f"1-0-0-{max(0, cts - 10_000)}"
        is_truncated_early = 0
        for page in range(3):
            u_tr = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after={cursor_key}"
            r_tr = await fetch_json(session, u_tr, sem)
            batch = (r_tr or {}).get("trades", [])
            if not batch:
                break
            genesis_trades.extend(batch)
            cursor_key = batch[-1]["ordinalKey"]
            last_ms = int(batch[-1].get("blockTimeMs") or 0)
            if len(batch) < 100:
                break
            if page == 2 and last_ms <= cts + 30 * 60_000:
                is_truncated_early = 1

        u_lat = f"{PUMPFUN_V3_BASE}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100"
        r_lat = await fetch_json(session, u_lat, sem)
        latest_trades = (r_lat or {}).get("trades", [])

        by_ok = {}
        for tr in genesis_trades + latest_trades:
            ok = tr.get("ordinalKey")
            if ok:
                by_ok[ok] = tr
        merged = sorted(
            by_ok.values(),
            key=lambda x: (int(x.get("blockTimeMs") or 0), int(x.get("blockId") or 0), int(x.get("txIndex") or 0), int(x.get("eventIndex") or 0))
        )
        t_file.write_text(json.dumps({
            "mint": mint,
            "collection_timestamp_ms": collection_ms,
            "genesis_trades_count": len(genesis_trades),
            "latest_trades_count": len(latest_trades),
            "total_unique_trades": len(merged),
            "early_30m_pagination_truncated": is_truncated_early,
            "trades": merged,
        }), encoding="utf-8")

async def main():
    t0 = time.time()
    collection_ms = int(time.time() * 1000)
    collection_utc = datetime.fromtimestamp(collection_ms / 1000.0, tz=timezone.utc).isoformat()
    logger.info(f"Starting P0 Chronological Dataset Build at {collection_utc} ({collection_ms})")

    # Read V1 raw universe & creator db STRICTLY READ-ONLY
    v1_univ = json.loads((V1_DIR / "cache" / "raw" / "pumpfun_universe_raw.json").read_text(encoding="utf-8"))
    v1_cr_path = V1_DIR / "cache" / "creators" / "creator_histories_complete.json"
    v1_cr_db = json.loads(v1_cr_path.read_text(encoding="utf-8")) if v1_cr_path.exists() else {}

    # 1. Contiguous Consecutive Arrival Stream (Nov 24, sorted strictly by created_timestamp ASC, ZERO outcome filter!)
    arrival_stream = [
        c for c in v1_univ.values()
        if c.get("_discovery_source") == "sweep_created_timestamp_None" and (c.get("created_timestamp") or 0) > 0
    ]
    arrival_stream.sort(key=lambda c: (int(c["created_timestamp"]), c["mint"]))
    # Take contiguous chronological block of first 330 consecutive launches from 2026-11-24T21:57:28Z!
    stratum_consecutive = arrival_stream[:330]
    logger.info(
        f"Stratum B (Contiguous Consecutive Emissions): {len(stratum_consecutive)} tokens | "
        f"span: {stratum_consecutive[0]['created_timestamp']} .. {stratum_consecutive[-1]['created_timestamp']}"
    )

    # 2. Outcome-Blind Creators:
    #    (a) Creators who deployed at least one token BEFORE WINDOW_30D_START_MS (2026-10-25), OR
    #    (b) Creators from the arrival-time sweep `arrival_stream` (discovered purely by launch timestamp, NOT outcome!)
    pre_oct25_creators = [
        cr for cr, info in v1_cr_db.items()
        if any(0 < int(b.get("created_timestamp") or 0) < WINDOW_30D_START_MS for b in info.get("coins_brief", []))
    ]
    arrival_creators = list(dict.fromkeys([c.get("creator") for c in arrival_stream if c.get("creator")]))[:220]
    seed_creators = list(dict.fromkeys(pre_oct25_creators + arrival_creators))

    sem = asyncio.Semaphore(12)
    connector = aiohttp.TCPConnector(limit=20, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        cr_histories = await expand_outcome_blind_creators(session, sem, seed_creators, v1_cr_db)

        # Collect ALL 30-day tokens launched by these outcome-blind seed creators prior to the Nov 24 contiguous block!
        nov24_block_start = int(stratum_consecutive[0]["created_timestamp"])
        panel_30d_by_mint = {}
        for cr, info in cr_histories.items():
            full_list = info.get("coins_full") or []
            for coin_obj in full_list:
                m = coin_obj.get("mint")
                cts = int(coin_obj.get("created_timestamp") or 0)
                if m and WINDOW_30D_START_MS <= cts < nov24_block_start - 3600_000:
                    panel_30d_by_mint[m] = coin_obj
            # Also check v1_univ for pre_oct25_creators whose full coin objects are in v1_univ
            if not full_list:
                for b in info.get("coins_brief", []):
                    m = b.get("mint")
                    cts = int(b.get("created_timestamp") or 0)
                    if m and m in v1_univ and WINDOW_30D_START_MS <= cts < nov24_block_start - 3600_000:
                        panel_30d_by_mint[m] = v1_univ[m]

        panel_30d_sorted = sorted(panel_30d_by_mint.values(), key=lambda c: (int(c["created_timestamp"]), c["mint"]))
        # If > 320 tokens in 30d panel, take deterministic chronological stride (every k-th by birth timestamp, ZERO outcome inspection!)
        if len(panel_30d_sorted) > 320:
            step_f = len(panel_30d_sorted) / 320.0
            stratum_30d = [panel_30d_sorted[int(i * step_f)] for i in range(320)]
        else:
            stratum_30d = panel_30d_sorted

        logger.info(f"Stratum A (30d Outcome-Blind Chronological Panel): {len(stratum_30d)} tokens (from {len(panel_30d_sorted)} unconditional 30d emissions)")

        # Merge Stratum A + Stratum B strictly sorted by created_timestamp
        chron_universe = {}
        for c in stratum_30d:
            c_copy = dict(c)
            c_copy["_v2_stratum"] = "A_30d_outcome_blind_panel"
            chron_universe[c["mint"]] = c_copy
        for c in stratum_consecutive:
            if c["mint"] not in chron_universe:
                c_copy = dict(c)
                c_copy["_v2_stratum"] = "B_nov24_contiguous_arrival_stream"
                chron_universe[c["mint"]] = c_copy

        chron_list = sorted(chron_universe.values(), key=lambda x: (int(x["created_timestamp"]), x["mint"]))
        logger.info(f"TOTAL V2 CHRONOLOGICAL OBSERVED DATASET (Train/Val/Walk-Forward): {len(chron_list)} tokens")

        # Save chronological dataset manifest
        ds_meta = {
            "collection_timestamp_ms": collection_ms,
            "collection_timestamp_utc": collection_utc,
            "universe_scope": "observed_chronological_sample (outcome-blind; API offset bounded to ~1,500 rows per query)",
            "selection_rule": "Strictly chronological by created_timestamp; 0% filtering on future ATH, mcap, migration, volume, or survival.",
            "total_tokens": len(chron_list),
            "stratum_a_30d_panel_count": sum(1 for x in chron_list if x["_v2_stratum"] == "A_30d_outcome_blind_panel"),
            "stratum_b_contiguous_nov24_count": sum(1 for x in chron_list if x["_v2_stratum"] == "B_nov24_contiguous_arrival_stream"),
            "tokens": chron_list,
        }
        (RAW_V2_DIR / "v2_chronological_dataset.json").write_text(json.dumps(ds_meta), encoding="utf-8")

        # Fetch updated SOL/USDT 1h klines up to collection_ms
        u_sol = f"{BINANCE_BASE}/klines?symbol=SOLUSDT&interval=1h&startTime={WINDOW_30D_START_MS - 7*86400_000}&endTime={collection_ms}&limit=1000"
        sol_1h = await fetch_json(session, u_sol, sem)
        (RAW_V2_DIR / "sol_1h_v2.json").write_text(json.dumps(sol_1h or []), encoding="utf-8")

        # Fetch DexScreener current pool enrichment in batches of 30
        ds_enr = {}
        mints_all = [x["mint"] for x in chron_list]
        for i in range(0, len(mints_all), 30):
            chunk = mints_all[i:i+30]
            pairs = await fetch_json(session, f"{DEXSCREENER_BASE}/tokens/v1/solana/{','.join(chunk)}", sem)
            if isinstance(pairs, list):
                for p in pairs:
                    b_addr = (p.get("baseToken") or {}).get("address")
                    if b_addr:
                        liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
                        prev = float((ds_enr.get(b_addr, {}).get("liquidity") or {}).get("usd") or -1.0)
                        if liq > prev:
                            ds_enr[b_addr] = p
            await asyncio.sleep(0.15)
        (RAW_V2_DIR / "dexscreener_v2.json").write_text(json.dumps(ds_enr), encoding="utf-8")
        logger.info(f"DexScreener active pair snapshots found for {len(ds_enr)}/{len(chron_list)} tokens.")

        # Fetch candles (1m, 15m, 4h) and genesis/latest trades for all chronological tokens
        batch_sz = 25
        for i in range(0, len(chron_list), batch_sz):
            batch = chron_list[i:i+batch_sz]
            await asyncio.gather(*[
                acquire_token_history_v2(session, sem, x["mint"], x, collection_ms)
                for x in batch
            ])
            if (i // batch_sz) % 2 == 0 or i + batch_sz >= len(chron_list):
                logger.info(f"History acquisition progress: {min(i+batch_sz, len(chron_list))}/{len(chron_list)} ({time.time()-t0:.1f}s)")

    logger.info(f"V2 Step 1 completed in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    asyncio.run(main())
