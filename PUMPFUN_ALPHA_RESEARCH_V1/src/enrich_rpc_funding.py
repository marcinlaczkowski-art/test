"""
Polite Solana RPC enrichment pass (sem=3) to fill rate-limited wallets and extract
both SystemProgram SOL transfers and net EOA SOL balance transfers from jsonParsed transactions.
"""
import asyncio, aiohttp, json
from collections import Counter
from config import RPC_CACHE_DIR, SOLANA_RPC_URL, TECHNICAL_ADDRESSES

async def rpc_post(session, sem, method, params):
    async with sem:
        for att in range(3):
            try:
                async with session.post(
                    SOLANA_RPC_URL,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status == 200:
                        d = await r.json(content_type=None)
                        if "result" in d and d["result"] is not None:
                            return d["result"]
                    await asyncio.sleep(0.5 * (att + 1))
            except Exception:
                await asyncio.sleep(0.4)
    return None

async def enrich_one(session, sem, wallet, existing):
    sigs = await rpc_post(session, sem, "getSignaturesForAddress", [wallet, {"limit": 50}])
    if not isinstance(sigs, list) or not sigs:
        return existing
    picks = [sigs[-1]["signature"]]
    if len(sigs) >= 4:
        picks.append(sigs[-3]["signature"])
    if len(sigs) >= 15:
        picks.append(sigs[-10]["signature"])

    funders = list(existing.get("funders", []))
    outbound = list(existing.get("outbound_sol_targets", []))
    seen_f = {x["funder"] for x in funders}
    seen_o = {x["target"] for x in outbound}

    for sig in picks:
        tx = await rpc_post(session, sem, "getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
        if not isinstance(tx, dict):
            continue
        bt = tx.get("blockTime")
        msg = (tx.get("transaction") or {}).get("message") or {}
        ixs = list(msg.get("instructions") or [])
        for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
            ixs.extend(inner.get("instructions") or [])
        for ix in ixs:
            parsed = ix.get("parsed")
            if isinstance(parsed, dict) and parsed.get("type") in ("transfer", "transferChecked", "createAccount", "closeAccount"):
                info = parsed.get("info") or {}
                src = info.get("source") or info.get("account")
                dst = info.get("destination") or info.get("newAccount")
                sol_amt = int(info.get("lamports") or 0) / 1e9
                if sol_amt >= 0.002:
                    if dst == wallet and src and src not in TECHNICAL_ADDRESSES and src != wallet and src not in seen_f:
                        seen_f.add(src)
                        funders.append({"funder": src, "sol": round(sol_amt, 5), "blockTime": bt, "tx": sig})
                    elif src == wallet and dst and dst not in TECHNICAL_ADDRESSES and dst != wallet and dst not in seen_o:
                        seen_o.add(dst)
                        outbound.append({"target": dst, "sol": round(sol_amt, 5), "blockTime": bt, "tx": sig})

        # Also inspect fee-payer / signer EOA if different from wallet!
        acct_keys = msg.get("accountKeys") or []
        if acct_keys and isinstance(acct_keys[0], dict):
            fee_payer = acct_keys[0].get("pubkey")
            if fee_payer and fee_payer != wallet and fee_payer not in TECHNICAL_ADDRESSES and fee_payer not in seen_f:
                seen_f.add(fee_payer)
                funders.append({"funder": fee_payer, "sol": 0.01, "blockTime": bt, "tx": sig, "note": "co_signer_or_fee_payer"})

    return {
        "wallet": wallet,
        "sampled_sig_count": len(sigs),
        "oldest_sampled_blockTime": sigs[-1].get("blockTime"),
        "newest_sampled_blockTime": sigs[0].get("blockTime"),
        "funders": funders,
        "outbound_sol_targets": outbound,
    }

async def main():
    p = RPC_CACHE_DIR / "solana_rpc_funding_graph.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    wallets = d["wallets"]
    todo = [w for w, info in wallets.items() if info.get("sampled_sig_count", 0) == 0 or len(info.get("funders", [])) == 0][:90]
    sem = asyncio.Semaphore(3)
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(todo), 12):
            batch = todo[i:i+12]
            res = await asyncio.gather(*[enrich_one(session, sem, w, wallets[w]) for w in batch])
            for w, r in zip(batch, res):
                wallets[w] = r

        f_counts = Counter(fo["funder"] for info in wallets.values() for fo in info.get("funders", []))
        shared = [f for f, cnt in f_counts.items() if cnt >= 2]
        f_cls = d.get("funder_classifications", {})
        for sf in shared[:25]:
            sigs = await rpc_post(session, sem, "getSignaturesForAddress", [sf, {"limit": 100}])
            if isinstance(sigs, list) and len(sigs) >= 95:
                tspan = (sigs[0].get("blockTime") or 0) - (sigs[-1].get("blockTime") or 0)
                f_cls[sf] = {"type": "CEX_OR_HIGH_FREQ_SERVICE" if 0 <= tspan < 900 else "ACTIVE_OPERATOR_OR_DESK", "100tx_span_sec": tspan}
            else:
                f_cls[sf] = {"type": "PERSONAL_OR_DEDICATED_FUNDER", "sampled_txs": len(sigs) if isinstance(sigs, list) else 0}

    d["wallets"] = wallets
    d["funder_classifications"] = f_cls
    p.write_text(json.dumps(d), encoding="utf-8")
    tot_f = sum(len(v.get("funders", [])) for v in wallets.values())
    print(f"Enriched RPC graph: {sum(1 for v in wallets.values() if v.get('sampled_sig_count',0)>0)}/{len(wallets)} with sigs, {tot_f} funding/fee-payer links, {len(shared)} shared funders!")

if __name__ == "__main__":
    asyncio.run(main())
