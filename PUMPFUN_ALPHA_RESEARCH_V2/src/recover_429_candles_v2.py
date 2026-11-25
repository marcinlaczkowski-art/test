"""
Polite recovery pass (`sem=3`) for tokens whose candle requests experienced HTTP 429 (`api_ok == 0`)
during initial bulk harvest, maximizing uncensored 1h, 4h, and 24h completeness.
"""
import asyncio
import aiohttp
import json
import time
from config_v2 import RAW_V2_DIR, CANDLES_V2_DIR, SOLANA_CHAIN_ID, PUMPFUN_V3_BASE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

async def fetch_polite(session, url, sem):
    for att in range(4):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    elif r.status == 429:
                        await asyncio.sleep(1.5 * (att + 1))
                    else:
                        return {"candles": []}
            except Exception:
                await asyncio.sleep(0.8 * (att + 1))
    return None

async def main():
    ds = json.loads((RAW_V2_DIR / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    col_ms = int(ds["collection_timestamp_ms"])
    todo = []
    for c in ds["tokens"]:
        m = c["mint"]
        cp = CANDLES_V2_DIR / f"{m}.json"
        if not cp.exists() or json.loads(cp.read_text(encoding="utf-8")).get("api_ok", 0) == 0:
            todo.append(c)

    print(f"Recovering {len(todo)} rate-limited candle histories with polite sem=3...")
    sem = asyncio.Semaphore(3)
    recovered = 0
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i, c in enumerate(todo):
            m = c["mint"]
            cts = int(c.get("created_timestamp") or 0)
            to_1m = min(col_ms, cts + 195 * 60_000) if cts > 0 else col_ms
            to_15m = min(col_ms, cts + 28 * 3600_000) if cts > 0 else col_ms
            r1, r15, r4 = await asyncio.gather(
                fetch_polite(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=1m&to={to_1m}", sem),
                fetch_polite(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=15m&to={to_15m}", sem),
                fetch_polite(session, f"{PUMPFUN_V3_BASE}/candles/{SOLANA_CHAIN_ID}/{m}?res=4h&to={col_ms}", sem),
            )
            ok = int(r1 is not None or r15 is not None)
            if ok:
                recovered += 1
            (CANDLES_V2_DIR / f"{m}.json").write_text(json.dumps({
                "mint": m,
                "collection_timestamp_ms": col_ms,
                "candles_1m": sorted((r1 or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
                "candles_15m": sorted((r15 or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
                "candles_4h": sorted((r4 or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)),
                "api_ok": ok,
            }), encoding="utf-8")
            if (i + 1) % 40 == 0:
                print(f"Progress {i+1}/{len(todo)} (recovered={recovered})")
            await asyncio.sleep(0.12)
    print(f"Done: recovered {recovered}/{len(todo)} candle files.")

if __name__ == "__main__":
    asyncio.run(main())
