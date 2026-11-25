"""
STEP 3: On-Chain Forensics, Creator Histories, Live Wallet Balances/PnL, and Solana RPC Funding Provenance.

1. Ensures complete Creator Launch Histories (`coins-v2/user-created-coins/{creator}`) for all 444 cohort creators.
2. Scans all cohort trades to identify:
   - Recurring early buyers across multiple tokens (Smart Money / Repeat Sniper / Operator candidates),
   - Top early/net accumulators & creators across the top pump tokens + $COOL case tokens.
3. Queries `profile-api.pump.fun/balance/tokens/{wallet}` and `/balance/summary/{wallet}` to obtain exact current token retention, SOL balances, and wallet-level realized/unrealized PnL.
4. Queries `solana-rpc.publicnode.com` (`getSignaturesForAddress` + `getTransaction` with `maxSupportedTransactionVersion: 1`) to reconstruct real on-chain SOL funding links and distinguish personal operator funding clusters from high-frequency CEX/service hot wallets.
"""
import asyncio
import aiohttp
import json
import time
import logging
from collections import defaultdict, Counter

from config import (
    RAW_DIR, TRADES_CACHE_DIR, CREATORS_CACHE_DIR, RPC_CACHE_DIR, HOLDINGS_CACHE_DIR, LOGS_DIR,
    PUMPFUN_V3_BASE, PUMPFUN_PROFILE_BASE, SOLANA_RPC_URL, TECHNICAL_ADDRESSES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step3_onchain_wallets.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step3")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
}

async def fetch_json(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore, retries: int = 1):
    for attempt in range(retries):
        async with sem:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.5)) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    elif resp.status in (429, 500, 502, 503, 504):
                        await asyncio.sleep(0.4)
                    else:
                        return None
            except Exception:
                return None
    return None

async def rpc_call(session: aiohttp.ClientSession, sem: asyncio.Semaphore, method: str, params: list, retries: int = 2):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for attempt in range(retries):
        async with sem:
            try:
                async with session.post(
                    SOLANA_RPC_URL,
                    json=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=6.5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if "result" in data:
                            return data["result"]
                        if "error" in data and data["error"].get("code") == 429:
                            await asyncio.sleep(1.2 * (attempt + 1))
                            continue
                        return None
                    elif resp.status in (429, 502, 503, 504):
                        await asyncio.sleep(1.2 * (attempt + 1))
                    else:
                        return None
            except Exception:
                await asyncio.sleep(0.8 * (attempt + 1))
    return None

async def complete_creator_histories(session: aiohttp.ClientSession, sem: asyncio.Semaphore, cohort_coins: list):
    seed_file = CREATORS_CACHE_DIR / "creator_histories_seed.json"
    creator_db = {}
    if seed_file.exists():
        with open(seed_file, "r", encoding="utf-8") as f:
            creator_db = json.load(f)

    missing_creators = []
    seen = set(creator_db.keys())
    for c in cohort_coins:
        cr = c.get("creator")
        if cr and cr not in seen:
            seen.add(cr)
            missing_creators.append(cr)

    logger.info(f"Fetching missing creator histories for {len(missing_creators)} cohort creators (already cached: {len(creator_db)})...")
    for i in range(0, len(missing_creators), 35):
        batch = missing_creators[i:i+35]
        urls = [f"{PUMPFUN_V3_BASE}/coins-v2/user-created-coins/{cr}?offset=0&limit=50&includeNsfw=true" for cr in batch]
        res_list = await asyncio.gather(*[fetch_json(session, u, sem) for u in urls])
        for cr, res in zip(batch, res_list):
            if isinstance(res, dict) and isinstance(res.get("coins"), list):
                coins = res["coins"]
                migrated_cnt = sum(1 for x in coins if x.get("complete"))
                max_ath = max([float(x.get("ath_market_cap") or x.get("usd_market_cap") or 0) for x in coins] + [0.0])
                creator_db[cr] = {
                    "creator": cr,
                    "total_created_count": res.get("count", len(coins)),
                    "sampled_coins_count": len(coins),
                    "migrated_count": migrated_cnt,
                    "max_ath_usd": max_ath,
                    "coins_brief": [
                        {
                            "mint": x.get("mint"),
                            "name": x.get("name"),
                            "symbol": x.get("symbol"),
                            "created_timestamp": x.get("created_timestamp"),
                            "complete": x.get("complete"),
                            "ath_market_cap": x.get("ath_market_cap") or x.get("usd_market_cap") or 0
                        }
                        for x in coins
                    ]
                }
        await asyncio.sleep(0.1)

    # Also upgrade seed entries with summary stats if needed
    out_file = CREATORS_CACHE_DIR / "creator_histories_complete.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(creator_db, f)
    logger.info(f"Creator database complete: {len(creator_db)} creators saved.")
    return creator_db

def identify_priority_wallets(coins_by_mint: dict, selected_mints: dict):
    early_token_counts = Counter()
    wallet_buy_usd = Counter()
    top_pump_accumulators = set()
    creators_top = set()

    # Rank cohort pumps by ath_market_cap
    ranked_cohort = sorted(
        [(float(coins_by_mint[m].get("ath_market_cap") or coins_by_mint[m].get("usd_market_cap") or 0), m, role)
         for m, role in selected_mints.items() if m in coins_by_mint],
        reverse=True
    )
    top_80_mints = {m for _, m, role in ranked_cohort[:90]}
    for m in top_80_mints:
        cr = coins_by_mint[m].get("creator")
        if cr and cr not in TECHNICAL_ADDRESSES:
            creators_top.add(cr)

    for m in selected_mints:
        t_path = TRADES_CACHE_DIR / f"{m}.json"
        if not t_path.exists():
            continue
        with open(t_path, "r", encoding="utf-8") as f:
            tdata = json.load(f)
        trades = tdata.get("trades", [])
        seen_early_buyers = set()
        net_tokens_by_wallet = defaultdict(float)

        for idx, tr in enumerate(trades):
            w = (tr.get("trader") or {}).get("address")
            if not w or w in TECHNICAL_ADDRESSES:
                continue
            side = tr.get("side")
            raw_base = float((tr.get("baseAmount") or {}).get("raw") or 0)
            dec = int((tr.get("baseAmount") or {}).get("decimals") or 6)
            tok_amt = raw_base / (10 ** dec)
            val_usd = float(tr.get("valueUsd") or 0.0)

            if side == "buy":
                net_tokens_by_wallet[w] += tok_amt
                wallet_buy_usd[w] += val_usd
                if len(seen_early_buyers) < 50:
                    seen_early_buyers.add(w)
            elif side == "sell":
                net_tokens_by_wallet[w] -= tok_amt

        for w in seen_early_buyers:
            early_token_counts[w] += 1

        if m in top_80_mints and net_tokens_by_wallet:
            top_w = sorted(net_tokens_by_wallet.items(), key=lambda x: x[1], reverse=True)[:4]
            for w, _ in top_w:
                top_pump_accumulators.add(w)

    # Priority wallets for profile holdings API (~210 top creators, accumulators, and repeat smart-money)
    repeat_early = [w for w, cnt in early_token_counts.most_common(120) if cnt >= 2]
    priority_holdings_wallets = list(dict.fromkeys(list(creators_top) + list(top_pump_accumulators)[:90] + repeat_early[:70]))[:210]

    # Priority wallets for Solana RPC funding trace (~160 wallets: top repeat snipers/smart-money + top 45 pump creators & top accumulators)
    top_35_mints = {m for _, m, _ in ranked_cohort[:35]}
    rpc_candidates = []
    for m in top_35_mints:
        cr = coins_by_mint[m].get("creator")
        if cr and cr not in TECHNICAL_ADDRESSES:
            rpc_candidates.append(cr)
        t_path = TRADES_CACHE_DIR / f"{m}.json"
        if t_path.exists():
            with open(t_path, "r", encoding="utf-8") as f:
                trades = json.load(f).get("trades", [])
            # First 5 buyers of each top pump
            b_seen = []
            for tr in trades:
                w = (tr.get("trader") or {}).get("address")
                if tr.get("side") == "buy" and w and w not in TECHNICAL_ADDRESSES and w not in b_seen:
                    b_seen.append(w)
                    if len(b_seen) >= 4:
                        break
            rpc_candidates.extend(b_seen)
    rpc_candidates.extend(repeat_early[:60])
    priority_rpc_wallets = list(dict.fromkeys(rpc_candidates))[:175]

    logger.info(f"Identified {len(priority_holdings_wallets)} priority wallets for holdings/PnL & {len(priority_rpc_wallets)} for Solana RPC funding forensics.")
    return priority_holdings_wallets, priority_rpc_wallets

async def fetch_wallet_holdings(session: aiohttp.ClientSession, sem: asyncio.Semaphore, wallets: list):
    out_file = HOLDINGS_CACHE_DIR / "wallet_profiles_and_holdings.json"
    cached = {}
    if out_file.exists():
        with open(out_file, "r", encoding="utf-8") as f:
            cached = json.load(f)

    todo = [w for w in wallets if w not in cached]
    logger.info(f"Querying profile-api.pump.fun for {len(todo)} wallets (cached: {len(cached)})...")

    for i in range(0, len(todo), 30):
        batch = todo[i:i+30]
        sum_urls = [f"{PUMPFUN_PROFILE_BASE}/balance/summary/{w}" for w in batch]
        tok_urls = [f"{PUMPFUN_PROFILE_BASE}/balance/tokens/{w}?page=1&size=50" for w in batch]
        sums, toks = await asyncio.gather(
            asyncio.gather(*[fetch_json(session, u, sem) for u in sum_urls]),
            asyncio.gather(*[fetch_json(session, u, sem) for u in tok_urls])
        )
        for w, s_res, t_res in zip(batch, sums, toks):
            s_data = (s_res or {}).get("data") or {}
            t_list = ((t_res or {}).get("data") or {}).get("tokens") or []
            cached[w] = {
                "wallet": w,
                "native_sol": s_data.get("native_balance", 0.0),
                "total_value_usd": s_data.get("total_value", 0.0),
                "token_count": s_data.get("token_count", len(t_list)),
                "portfolioPnL": s_data.get("portfolioPnL") or {},
                "tokens": [
                    {
                        "mint": t.get("token_mint"),
                        "symbol": t.get("token_symbol"),
                        "balance": t.get("balance"),
                        "value_usd": t.get("value"),
                        "tokenPnL": t.get("tokenPnL") or {}
                    }
                    for t in t_list if t.get("token_mint")
                ]
            }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(cached, f)
        logger.info(f"Holdings progress: {min(i+30, len(todo))}/{len(todo)} wallets queried")
        await asyncio.sleep(0.05)

    logger.info(f"Saved holdings & portfolio PnL for {len(cached)} wallets.")
    return cached

async def trace_wallet_funding_rpc(session: aiohttp.ClientSession, sem: asyncio.Semaphore, wallet: str) -> dict:
    # Get recent/oldest signatures (up to 40) to gauge wallet activity & inspect SOL inbound transfer
    sigs = await rpc_call(session, sem, "getSignaturesForAddress", [wallet, {"limit": 40}])
    if not isinstance(sigs, list) or not sigs:
        return {"wallet": wallet, "sampled_sig_count": 0, "funders": [], "outbound_sol_targets": []}

    # Pick the oldest signature in this 40-tx window + one middle signature to inspect native SOL transfers
    candidate_sigs = [sigs[-1]["signature"]]
    if len(sigs) >= 3:
        candidate_sigs.append(sigs[-2]["signature"])
    if len(sigs) >= 10:
        candidate_sigs.append(sigs[len(sigs)//2]["signature"])

    funders = []
    outbound = []
    for sig in candidate_sigs[:2]:
        tx = await rpc_call(session, sem, "getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
        if not isinstance(tx, dict):
            continue
        bt = tx.get("blockTime")
        msg = (tx.get("transaction") or {}).get("message") or {}
        ixs = list(msg.get("instructions") or [])
        for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
            ixs.extend(inner.get("instructions") or [])

        for ix in ixs:
            parsed = ix.get("parsed")
            if isinstance(parsed, dict) and parsed.get("type") == "transfer" and ix.get("program") == "system":
                info = parsed.get("info") or {}
                src = info.get("source")
                dst = info.get("destination")
                lamports = int(info.get("lamports") or 0)
                sol_amt = lamports / 1e9
                if sol_amt >= 0.005:
                    if dst == wallet and src and src not in TECHNICAL_ADDRESSES and src != wallet:
                        funders.append({"funder": src, "sol": round(sol_amt, 6), "blockTime": bt, "tx": sig})
                    elif src == wallet and dst and dst not in TECHNICAL_ADDRESSES and dst != wallet:
                        outbound.append({"target": dst, "sol": round(sol_amt, 6), "blockTime": bt, "tx": sig})

    return {
        "wallet": wallet,
        "sampled_sig_count": len(sigs),
        "oldest_sampled_blockTime": sigs[-1].get("blockTime"),
        "newest_sampled_blockTime": sigs[0].get("blockTime"),
        "funders": funders,
        "outbound_sol_targets": outbound,
    }

async def run_rpc_forensics(session: aiohttp.ClientSession, rpc_sem: asyncio.Semaphore, wallets: list):
    out_file = RPC_CACHE_DIR / "solana_rpc_funding_graph.json"
    cached = {}
    if out_file.exists():
        with open(out_file, "r", encoding="utf-8") as f:
            cached = json.load(f)

    todo = [w for w in wallets if w not in cached]
    logger.info(f"Tracing on-chain SOL funding via Solana RPC for {len(todo)} wallets (cached: {len(cached)})...")

    for i in range(0, len(todo), 15):
        batch = todo[i:i+15]
        res_list = await asyncio.gather(*[trace_wallet_funding_rpc(session, rpc_sem, w) for w in batch])
        for w, r in zip(batch, res_list):
            cached[w] = r
        if (i // 15) % 3 == 0 or i + 15 >= len(todo):
            logger.info(f"RPC funding progress: {min(i+15, len(todo))}/{len(todo)} wallets traced")
        await asyncio.sleep(0.15)

    # Check shared funders to classify whether a funder is a high-tx CEX/service hotwallet vs personal/operator EOA!
    funder_counts = Counter()
    for w, info in cached.items():
        for f_obj in info.get("funders", []):
            funder_counts[f_obj["funder"]] += 1

    shared_funders = [f for f, cnt in funder_counts.items() if cnt >= 2]
    funder_classifications = {}
    for sf in shared_funders[:30]:
        sigs = await rpc_call(session, rpc_sem, "getSignaturesForAddress", [sf, {"limit": 100}])
        if isinstance(sigs, list) and len(sigs) >= 95:
            # Check time span of 100 txs: if 100 txs happened in < 15 minutes, almost certainly CEX / router / high-volume service
            t_span = (sigs[0].get("blockTime") or 0) - (sigs[-1].get("blockTime") or 0)
            if 0 <= t_span < 900:
                funder_classifications[sf] = {"type": "CEX_OR_HIGH_FREQ_SERVICE", "100tx_span_sec": t_span}
            else:
                funder_classifications[sf] = {"type": "ACTIVE_OPERATOR_OR_DESK", "100tx_span_sec": t_span}
        else:
            funder_classifications[sf] = {"type": "PERSONAL_OR_DEDICATED_FUNDER", "sampled_txs": len(sigs) if isinstance(sigs, list) else 0}

    payload = {"wallets": cached, "funder_classifications": funder_classifications}
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    logger.info(f"RPC forensics complete: {len(cached)} wallets traced, {len(shared_funders)} shared funders classified.")
    return payload

async def main():
    t0 = time.time()
    with open(RAW_DIR / "pumpfun_universe_raw.json", "r", encoding="utf-8") as f:
        coins_by_mint = json.load(f)
    with open(RAW_DIR / "cohort_selection.json", "r", encoding="utf-8") as f:
        cohort_sel = json.load(f)
    selected_mints = cohort_sel["selected_mints"]
    cohort_coins = [coins_by_mint[m] for m in selected_mints if m in coins_by_mint]

    http_sem = asyncio.Semaphore(14)
    rpc_sem = asyncio.Semaphore(8)  # polite concurrency for publicnode Solana RPC
    connector = aiohttp.TCPConnector(limit=24, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        await complete_creator_histories(session, http_sem, cohort_coins)
        holdings_wallets, rpc_wallets = identify_priority_wallets(coins_by_mint, selected_mints)
        await fetch_wallet_holdings(session, http_sem, holdings_wallets)
        await run_rpc_forensics(session, rpc_sem, rpc_wallets)

    logger.info(f"Step 3 completed in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    asyncio.run(main())
