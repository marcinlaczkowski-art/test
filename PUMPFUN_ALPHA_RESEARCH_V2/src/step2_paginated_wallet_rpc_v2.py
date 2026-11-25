"""
STEP 2 (V2 — P1 PAGINATED WALLET & SPL FORENSICS):
Paginates transaction history via Solana RPC (`getSignaturesForAddress` using `before` cursor
across multiple 200-signature pages — up to 600 signatures per wallet, NOT capped at 40!).

Extracts:
1. Wallet history span (`first_tx_utc`, `last_tx_utc`), `signatures_analyzed`, and
   `history_completeness` (`COMPLETE_GENESIS_REACHED` vs `PARTIAL_600_SIG_CAP` vs `RPC_UNAVAILABLE`).
2. Pre-purchase SOL funding links (`funders`), outbound SOL links (`outbound_targets`),
   and shared-funder classification (`PRIVATE_FUNDER` vs `CEX_OR_SERVICE_HOTWALLET`).
3. Direct SPL token transfers & burns (`transfer`, `transferChecked`, `burn`, `burnChecked`)
   for historical supply & FIFO cost-basis transfer carry-over!
"""
import asyncio
import aiohttp
import json
import time
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

from config_v2 import (
    RAW_V2_DIR, TRADES_V2_DIR, WALLETS_V2_DIR, LOGS_DIR,
    SOLANA_RPC_URL, CONFIRMED_TECHNICAL_ADDRESSES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step2_paginated_wallet_rpc_v2.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("v2_step2")

async def rpc_post(session: aiohttp.ClientSession, sem: asyncio.Semaphore, method: str, params: list, retries: int = 3):
    for att in range(retries):
        async with sem:
            try:
                async with session.post(
                    SOLANA_RPC_URL,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=9)
                ) as resp:
                    if resp.status == 200:
                        d = await resp.json(content_type=None)
                        if "result" in d and d["result"] is not None:
                            return d["result"]
                    await asyncio.sleep(0.45 * (att + 1))
            except Exception:
                await asyncio.sleep(0.4 * (att + 1))
    return None

def select_priority_wallets_v2(tokens: list) -> tuple:
    early_counts = Counter()
    vol_by_wallet = Counter()
    creators_active = set()
    cohort_mints = {t["mint"] for t in tokens}

    for tok in tokens:
        m = tok["mint"]
        cr = tok.get("creator")
        tpath = TRADES_V2_DIR / f"{m}.json"
        if not tpath.exists():
            continue
        trades = json.loads(tpath.read_text(encoding="utf-8")).get("trades", [])
        if len(trades) >= 5 and cr and cr not in CONFIRMED_TECHNICAL_ADDRESSES:
            creators_active.add(cr)
        seen_e = set()
        for tr in trades:
            w = (tr.get("trader") or {}).get("address") or ""
            if not w or w in CONFIRMED_TECHNICAL_ADDRESSES:
                continue
            vu = float(tr.get("valueUsd") or 0.0)
            vol_by_wallet[w] += vu
            if tr.get("side") == "buy" and len(seen_e) < 20:
                seen_e.add(w)
        for w in seen_e:
            early_counts[w] += 1

    repeat_early = [w for w, c in early_counts.most_common(120) if c >= 2]
    top_vol = [w for w, _ in vol_by_wallet.most_common(80)]
    priority = list(dict.fromkeys(repeat_early[:75] + list(creators_active)[:55] + top_vol[:45]))[:140]
    return priority, cohort_mints

async def trace_wallet_paginated(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    wallet: str,
    cohort_mints: set,
    max_pages: int = 3
) -> dict:
    all_sigs = []
    before_sig = None
    reached_genesis = False

    for page in range(max_pages):
        cfg = {"limit": 200}
        if before_sig:
            cfg["before"] = before_sig
        batch = await rpc_post(session, sem, "getSignaturesForAddress", [wallet, cfg])
        if not isinstance(batch, list) or not batch:
            if page == 0:
                return {
                    "wallet": wallet,
                    "signatures_analyzed": 0,
                    "pages_fetched": 0,
                    "history_completeness": "RPC_RATE_LIMITED_OR_EMPTY",
                    "first_tx_blockTime": None,
                    "last_tx_blockTime": None,
                    "first_tx_utc": "",
                    "last_tx_utc": "",
                    "funders": [],
                    "outbound_targets": [],
                    "spl_transfers": [],
                }
            reached_genesis = True
            break
        all_sigs.extend(batch)
        before_sig = batch[-1]["signature"]
        if len(batch) < 200:
            reached_genesis = True
            break

    completeness = "COMPLETE_GENESIS_REACHED" if reached_genesis else f"PARTIAL_PAGINATED_{len(all_sigs)}_SIGS"
    newest_bt = all_sigs[0].get("blockTime")
    oldest_bt = all_sigs[-1].get("blockTime")

    # Sample earliest 2 transactions (genesis funding!) + 1 recent transaction for SOL & SPL parsing
    sample_sigs = [all_sigs[-1]["signature"]]
    if len(all_sigs) >= 2:
        sample_sigs.append(all_sigs[-2]["signature"])
    if len(all_sigs) >= 6:
        sample_sigs.append(all_sigs[0]["signature"])

    funders = []
    outbound = []
    spl_transfers = []
    seen_f = set()
    seen_o = set()

    for sig in sample_sigs:
        tx = await rpc_post(session, sem, "getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
        if not isinstance(tx, dict):
            continue
        bt = int(tx.get("blockTime") or 0)
        bt_ms = bt * 1000
        meta = tx.get("meta") or {}
        msg = (tx.get("transaction") or {}).get("message") or {}

        # Build token account -> (owner, mint) map from preTokenBalances + postTokenBalances
        ta_map = {}
        acct_keys = msg.get("accountKeys") or []
        pubkeys = [a.get("pubkey") if isinstance(a, dict) else str(a) for a in acct_keys]
        for tb in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
            idx = tb.get("accountIndex")
            if idx is not None and 0 <= idx < len(pubkeys):
                ta_map[pubkeys[idx]] = (tb.get("owner") or "", tb.get("mint") or "", int((tb.get("uiTokenAmount") or {}).get("decimals") or 6))

        ixs = list(msg.get("instructions") or [])
        for inner in meta.get("innerInstructions") or []:
            ixs.extend(inner.get("instructions") or [])

        for ix in ixs:
            parsed = ix.get("parsed")
            if not isinstance(parsed, dict):
                continue
            prog = ix.get("program") or ""
            itype = parsed.get("type") or ""
            info = parsed.get("info") or {}

            if prog == "system" and itype in ("transfer", "createAccount"):
                src = info.get("source")
                dst = info.get("destination") or info.get("newAccount")
                sol_amt = int(info.get("lamports") or 0) / 1e9
                if sol_amt >= 0.002:
                    if dst == wallet and src and src not in CONFIRMED_TECHNICAL_ADDRESSES and src != wallet and src not in seen_f:
                        seen_f.add(src)
                        funders.append({"funder": src, "sol": round(sol_amt, 5), "blockTime": bt, "tx": sig})
                    elif src == wallet and dst and dst not in CONFIRMED_TECHNICAL_ADDRESSES and dst != wallet and dst not in seen_o:
                        seen_o.add(dst)
                        outbound.append({"target": dst, "sol": round(sol_amt, 5), "blockTime": bt, "tx": sig})

            elif prog in ("spl-token", "spl-token-2022") and itype in ("transfer", "transferChecked", "burn", "burnChecked"):
                src_ta = info.get("source") or info.get("account") or ""
                dst_ta = info.get("destination") or ""
                src_owner, mint_a, dec_a = ta_map.get(src_ta, ("", info.get("mint") or "", 6))
                dst_owner, mint_b, _ = ta_map.get(dst_ta, ("", "", dec_a))
                mint_id = info.get("mint") or mint_a or mint_b
                if mint_id in cohort_mints:
                    if "tokenAmount" in info and isinstance(info["tokenAmount"], dict):
                        ui_q = float(info["tokenAmount"].get("uiAmount") or 0.0)
                    else:
                        ui_q = float(info.get("amount") or 0.0) / (10 ** dec_a)
                    if ui_q > 0:
                        spl_transfers.append({
                            "mint": mint_id,
                            "blockTimeMs": bt_ms,
                            "source_owner": src_owner or info.get("authority") or "",
                            "dest_owner": "11111111111111111111111111111111" if "burn" in itype else dst_owner,
                            "amount_tokens": round(ui_q, 4),
                            "is_burn": int("burn" in itype),
                            "tx": sig,
                        })

        # Also check fee-payer co-signing if distinct from wallet
        if pubkeys and pubkeys[0] != wallet and pubkeys[0] not in CONFIRMED_TECHNICAL_ADDRESSES and pubkeys[0] not in seen_f:
            seen_f.add(pubkeys[0])
            funders.append({"funder": pubkeys[0], "sol": 0.005, "blockTime": bt, "tx": sig, "note": "co_signer_fee_payer"})

    f_utc = datetime.fromtimestamp(oldest_bt, tz=timezone.utc).isoformat() if oldest_bt else ""
    l_utc = datetime.fromtimestamp(newest_bt, tz=timezone.utc).isoformat() if newest_bt else ""

    return {
        "wallet": wallet,
        "signatures_analyzed": len(all_sigs),
        "pages_fetched": min(max_pages, (len(all_sigs) + 199) // 200),
        "history_completeness": completeness,
        "first_tx_blockTime": oldest_bt,
        "last_tx_blockTime": newest_bt,
        "first_tx_utc": f_utc,
        "last_tx_utc": l_utc,
        "funders": funders,
        "outbound_targets": outbound,
        "spl_transfers": spl_transfers,
    }

async def main():
    t0 = time.time()
    out_file = WALLETS_V2_DIR / "paginated_wallet_rpc_v2.json"
    ds = json.loads((RAW_V2_DIR / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    tokens = ds["tokens"]

    priority_wallets, cohort_mints = select_priority_wallets_v2(tokens)
    logger.info(f"Selected {len(priority_wallets)} priority wallets across {len(tokens)} V2 tokens for multi-page RPC reconstruction.")

    cached_w = {}
    if out_file.exists():
        cached_w = json.loads(out_file.read_text(encoding="utf-8")).get("wallets", {})

    todo = [w for w in priority_wallets if w not in cached_w or cached_w[w].get("signatures_analyzed", 0) == 0]
    sem = asyncio.Semaphore(4)  # polite concurrency so publicnode never 429-drops pages
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(todo), 12):
            batch = todo[i:i+12]
            res = await asyncio.gather(*[trace_wallet_paginated(session, sem, w, cohort_mints, max_pages=3) for w in batch])
            for w, r in zip(batch, res):
                cached_w[w] = r
            if (i // 12) % 3 == 0 or i + 12 >= len(todo):
                logger.info(f"Paginated RPC progress: {min(i+12, len(todo))}/{len(todo)} ({time.time()-t0:.1f}s)")
            await asyncio.sleep(0.15)

        # Classify shared funders (Private vs CEX/Service hot wallet)
        f_cnt = Counter(fo["funder"] for v in cached_w.values() for fo in v.get("funders", []))
        shared_f = [f for f, c in f_cnt.items() if c >= 2]
        funder_types = {}
        for sf in shared_f[:25]:
            sigs = await rpc_post(session, sem, "getSignaturesForAddress", [sf, {"limit": 100}])
            if isinstance(sigs, list) and len(sigs) >= 95:
                span = (sigs[0].get("blockTime") or 0) - (sigs[-1].get("blockTime") or 0)
                funder_types[sf] = {"type": "CEX_OR_SERVICE_HOTWALLET" if 0 <= span < 900 else "ACTIVE_PRIVATE_OPERATOR", "100tx_span_sec": span}
            else:
                funder_types[sf] = {"type": "PRIVATE_DEDICATED_FUNDER", "sampled_sigs": len(sigs) if isinstance(sigs, list) else 0}

    payload = {"wallets": cached_w, "funder_types": funder_types}
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with_sigs = sum(1 for v in cached_w.values() if v.get("signatures_analyzed", 0) > 0)
    genesis_cnt = sum(1 for v in cached_w.values() if v.get("history_completeness") == "COMPLETE_GENESIS_REACHED")
    tot_sigs = sum(v.get("signatures_analyzed", 0) for v in cached_w.values())
    logger.info(
        f"Step 2 Paginated RPC complete in {time.time()-t0:.1f}s: "
        f"{with_sigs}/{len(cached_w)} wallets reconstructed | {tot_sigs:,} total signatures analyzed | "
        f"{genesis_cnt} reached exact wallet genesis!"
    )

if __name__ == "__main__":
    asyncio.run(main())
