"""
WALLET & INSIDER INTELLIGENCE V2 + FIFO COST-BASIS PNL + HISTORICAL SUPPLY RECONSTRUCTION (P1).

Implements:
1. Strict 8-Category Relationship & Confidence Taxonomy:
   - `1_Same_slot_co_buyers` (LOW_HEURISTIC — explicitly NOT proof of shared control)
   - `2_Same_slot_bundle_buyers` (MEDIUM_STRUCTURAL / HIGH_CORROBORATED)
   - `3_Shared_private_funder` (HIGH_ONCHAIN)
   - `4_Directly_linked_wallets` (HIGH_ONCHAIN — direct SOL or SPL transfer)
   - `5_Repeated_co_snipers` (MEDIUM_BEHAVIORAL)
   - `6_Creator_connected_wallets` (HIGH_ONCHAIN)
   - `7_Confirmed_technical_addresses` (CONFIRMED_SYSTEM — LP, curve, burn, router, CEX)
   - `8_Unknown_relationship` (UNKNOWN — absence of found funder != proof of independence)

2. Explicit FIFO Lot Accounting (`compute_fifo_pnl_for_token`):
   - Separates `fifo_realized_pnl_sol`, `fifo_unrealized_pnl_sol`, `internal_transfer_tokens`,
     and `unmatched_sell_proceeds_sol` (never treats raw SOL cashflow as exact realized profit
     when cost basis is incomplete!).

3. Historical Ledger Supply Concentration Reconstruction:
   - Tracks mint supply, burn reductions, LP/bonding-curve vaults, technical addresses,
     and human holder balances, explicitly marking `EXACT_LEDGER` vs `APPROXIMATE_TRUNCATED_TAPE`.
"""
from collections import deque, defaultdict, Counter
import math
import numpy as np
import networkx as nx

from config_v2 import CONFIRMED_TECHNICAL_ADDRESSES

RELATIONSHIP_CATEGORIES = {
    1: "1_Same_slot_co_buyers",
    2: "2_Same_slot_bundle_buyers",
    3: "3_Shared_private_funder",
    4: "4_Directly_linked_wallets",
    5: "5_Repeated_co_snipers",
    6: "6_Creator_connected_wallets",
    7: "7_Confirmed_technical_addresses",
    8: "8_Unknown_relationship",
}

def compute_fifo_pnl_for_token(
    trades: list,
    spl_transfers: list,
    total_supply_tokens: float,
    mark_price_usd: float,
    sol_price_usd: float,
    technical_addrs: set,
    is_tape_complete: bool,
    tx_fee_sol_est: float = 0.00015
) -> dict:
    """
    Reconstructs per-wallet FIFO cost basis, realized PnL, unrealized PnL,
    internal SPL transfers, and remaining token balances.
    """
    fifo_queues = defaultdict(deque)  # wallet -> deque of [qty, unit_cost_sol, unit_cost_usd, ts_ms]
    stats = defaultdict(lambda: {
        "tokens_bought": 0.0,
        "tokens_sold": 0.0,
        "sol_spent_gross": 0.0,
        "sol_received_gross": 0.0,
        "est_fees_sol": 0.0,
        "fifo_matched_sold_tokens": 0.0,
        "unmatched_sold_tokens": 0.0,
        "fifo_cost_of_matched_sells_sol": 0.0,
        "fifo_realized_pnl_sol": 0.0,
        "fifo_realized_pnl_usd": 0.0,
        "unattributed_sell_proceeds_sol": 0.0,
        "internal_transfer_in_tokens": 0.0,
        "internal_transfer_out_tokens": 0.0,
        "buy_tx_count": 0,
        "sell_tx_count": 0,
        "first_tx_ms": None,
        "last_tx_ms": None,
    })

    # Merge swap events and any observed SPL transfers chronologically
    events = []
    for tr in trades:
        tms = int(tr.get("blockTimeMs") or 0)
        events.append((tms, 0, "swap", tr))
    for tf in spl_transfers:
        tms = int(tf.get("blockTimeMs") or 0)
        events.append((tms, 1, "spl_transfer", tf))
    events.sort(key=lambda x: (x[0], x[1]))

    burned_tokens = 0.0

    for tms, _, ev_kind, obj in events:
        if ev_kind == "swap":
            w = (obj.get("trader") or {}).get("address") or ""
            if not w or w in technical_addrs:
                continue
            side = obj.get("side")
            raw_b = float((obj.get("baseAmount") or {}).get("raw") or 0.0)
            dec_b = int((obj.get("baseAmount") or {}).get("decimals") or 6)
            qty = raw_b / (10 ** dec_b)
            if qty <= 0:
                continue
            val_sol = float(obj.get("valueNative") or 0.0)
            val_usd = float(obj.get("valueUsd") or 0.0)
            q_sol_px = float(obj.get("quotePriceUsd") or sol_price_usd or 70.0)

            st = stats[w]
            if st["first_tx_ms"] is None or tms < st["first_tx_ms"]:
                st["first_tx_ms"] = tms
            if st["last_tx_ms"] is None or tms > st["last_tx_ms"]:
                st["last_tx_ms"] = tms

            if side == "buy":
                total_cost_sol = val_sol + tx_fee_sol_est
                total_cost_usd = val_usd + (tx_fee_sol_est * q_sol_px)
                unit_sol = total_cost_sol / qty
                unit_usd = total_cost_usd / qty
                fifo_queues[w].append([qty, unit_sol, unit_usd, tms])
                st["tokens_bought"] += qty
                st["sol_spent_gross"] += val_sol
                st["est_fees_sol"] += tx_fee_sol_est
                st["buy_tx_count"] += 1

            elif side == "sell":
                net_proceeds_sol = max(0.0, val_sol - tx_fee_sol_est)
                net_proceeds_usd = max(0.0, val_usd - tx_fee_sol_est * q_sol_px)
                sell_unit_sol = net_proceeds_sol / qty
                sell_unit_usd = net_proceeds_usd / qty

                st["tokens_sold"] += qty
                st["sol_received_gross"] += val_sol
                st["est_fees_sol"] += tx_fee_sol_est
                st["sell_tx_count"] += 1

                rem_to_match = qty
                q = fifo_queues[w]
                while rem_to_match > 1e-9 and q:
                    lot_qty, lot_u_sol, lot_u_usd, _ = q[0]
                    take = min(rem_to_match, lot_qty)
                    st["fifo_matched_sold_tokens"] += take
                    st["fifo_cost_of_matched_sells_sol"] += take * lot_u_sol
                    st["fifo_realized_pnl_sol"] += take * (sell_unit_sol - lot_u_sol)
                    st["fifo_realized_pnl_usd"] += take * (sell_unit_usd - lot_u_usd)
                    rem_to_match -= take
                    if take >= lot_qty - 1e-9:
                        q.popleft()
                    else:
                        q[0][0] -= take

                if rem_to_match > 1e-6:
                    # Unmatched inventory (e.g. received via unindexed transfer or truncated trade window)
                    st["unmatched_sold_tokens"] += rem_to_match
                    st["unattributed_sell_proceeds_sol"] += rem_to_match * sell_unit_sol

        elif ev_kind == "spl_transfer":
            src = obj.get("source_owner") or ""
            dst = obj.get("dest_owner") or ""
            qty = float(obj.get("amount_tokens") or 0.0)
            if qty <= 0:
                continue
            if dst in ("11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111") or obj.get("is_burn"):
                burned_tokens += qty
            if src and src not in technical_addrs:
                stats[src]["internal_transfer_out_tokens"] += qty
                # Carry over FIFO cost basis to recipient if available!
                rem = qty
                carried_lots = []
                q_src = fifo_queues[src]
                while rem > 1e-9 and q_src:
                    lq, lus, luu, lts = q_src[0]
                    take = min(rem, lq)
                    carried_lots.append([take, lus, luu, lts])
                    rem -= take
                    if take >= lq - 1e-9:
                        q_src.popleft()
                    else:
                        q_src[0][0] -= take
                if dst and dst not in technical_addrs:
                    stats[dst]["internal_transfer_in_tokens"] += qty
                    for cl in carried_lots:
                        fifo_queues[dst].append(cl)

    mark_sol = mark_price_usd / max(sol_price_usd, 1.0)
    wallet_fifo_out = {}
    for w, st in stats.items():
        rem_lots = fifo_queues[w]
        rem_qty = sum(l[0] for l in rem_lots)
        rem_cost_sol = sum(l[0] * l[1] for l in rem_lots)
        rem_cost_usd = sum(l[0] * l[2] for l in rem_lots)
        mtm_val_sol = rem_qty * mark_sol
        mtm_val_usd = rem_qty * mark_price_usd
        unreal_sol = mtm_val_sol - rem_cost_sol
        unreal_usd = mtm_val_usd - rem_cost_usd

        if st["unmatched_sold_tokens"] > 1.0:
            completeness = "PARTIAL_UNMATCHED_INVENTORY"
        elif not is_tape_complete:
            completeness = "APPROXIMATE_TRUNCATED_TAPE"
        else:
            completeness = "EXACT_FIFO_VERIFIED"

        wallet_fifo_out[w] = {
            **st,
            "remaining_fifo_tokens": round(rem_qty, 4),
            "remaining_cost_basis_sol": round(rem_cost_sol, 6),
            "remaining_cost_basis_usd": round(rem_cost_usd, 2),
            "fifo_realized_pnl_sol": round(st["fifo_realized_pnl_sol"], 6),
            "fifo_realized_pnl_usd": round(st["fifo_realized_pnl_usd"], 2),
            "fifo_unrealized_pnl_sol": round(unreal_sol, 6),
            "fifo_unrealized_pnl_usd": round(unreal_usd, 2),
            "unattributed_sell_proceeds_sol": round(st["unattributed_sell_proceeds_sol"], 6),
            "raw_net_sol_cashflow_deprecated": round(st["sol_received_gross"] - st["sol_spent_gross"] - st["est_fees_sol"], 6),
            "pnl_completeness": completeness,
        }

    eff_circulating_supply = max(1.0, total_supply_tokens - burned_tokens)
    holder_bals = sorted([v["remaining_fifo_tokens"] for w, v in wallet_fifo_out.items() if w not in technical_addrs and v["remaining_fifo_tokens"] > 0], reverse=True)
    observed_held_sum = sum(holder_bals)
    lp_or_curve_residual = max(0.0, eff_circulating_supply - observed_held_sum)

    supply_summary = {
        "initial_mint_supply": total_supply_tokens,
        "burned_tokens": round(burned_tokens, 2),
        "effective_supply": round(eff_circulating_supply, 2),
        "lp_and_bonding_curve_residual_pct": round((lp_or_curve_residual / eff_circulating_supply) * 100.0, 4),
        "top1_human_holder_pct": round((sum(holder_bals[:1]) / eff_circulating_supply) * 100.0, 4),
        "top5_human_holders_pct": round((sum(holder_bals[:5]) / eff_circulating_supply) * 100.0, 4),
        "top10_human_holders_pct": round((sum(holder_bals[:10]) / eff_circulating_supply) * 100.0, 4),
        "top20_human_holders_pct": round((sum(holder_bals[:20]) / eff_circulating_supply) * 100.0, 4),
        "active_human_holders_count": len(holder_bals),
        "reconstruction_quality": "EXACT_LEDGER_FROM_GENESIS" if is_tape_complete else "APPROXIMATE_PARTIAL_TAPE",
    }

    return {"wallets": wallet_fifo_out, "supply": supply_summary}

def classify_token_wallet_relationships_v2(
    mint: str,
    creator: str,
    trades: list,
    token_technical_addrs: dict,
    rpc_wallet_profiles: dict,
    funder_types: dict,
    co_sniper_pair_counts: Counter,
    wallet_fifo_map: dict,
    effective_supply: float,
) -> tuple:
    """
    Classifies wallets and relationships strictly into the 8 V2 categories.
    Never treats same-slot co-buying alone as proof of shared control!
    """
    G_verified_insider = nx.Graph()  # ONLY High/Corroborated links (Categories 3, 4, 6, and corroborated 2)
    relationship_rows = []

    participants = [w for w in wallet_fifo_map.keys() if w not in token_technical_addrs]
    for w in participants:
        G_verified_insider.add_node(w)

    # Map RPC funders & direct transfers
    wallet_private_funders = defaultdict(set)
    wallet_cex_funders = defaultdict(set)
    direct_links = set()

    for w, prof in rpc_wallet_profiles.items():
        for fo in prof.get("funders", []):
            f_addr = fo["funder"]
            ftype = funder_types.get(f_addr, {}).get("type", "PRIVATE_FUNDER")
            if ftype == "CEX_OR_SERVICE_HOTWALLET":
                wallet_cex_funders[w].add(f_addr)
            else:
                wallet_private_funders[w].add(f_addr)
                direct_links.add((f_addr, w))
        for out_o in prof.get("outbound_targets", []):
            direct_links.add((w, out_o["target"]))

    # Inspect launch-window slot/block buying
    created_block = int(trades[0].get("blockId") or 0) if trades else 0
    slot_buyers = defaultdict(list)
    for tr in trades:
        if tr.get("side") == "buy":
            w = (tr.get("trader") or {}).get("address") or ""
            if w and w not in token_technical_addrs:
                blk = int(tr.get("blockId") or 0)
                txi = int(tr.get("txIndex") or 0)
                slot_buyers[blk].append((txi, w))

    same_slot_co_buyers = set()
    same_slot_bundle_buyers = set()
    for blk, items in slot_buyers.items():
        items_sorted = sorted(items, key=lambda x: x[0])
        uniq_w = list(dict.fromkeys([w for _, w in items_sorted]))
        if len(uniq_w) >= 2:
            # Check deterministic contiguous txIndex bundle structure ( >=3 wallets or creation block adjacent txIndex <= 2 )
            tx_indices = [txi for txi, _ in items_sorted]
            max_gap = max(tx_indices[k+1] - tx_indices[k] for k in range(len(tx_indices)-1)) if len(tx_indices) >= 2 else 99
            if (blk == created_block and max_gap <= 2) or (len(uniq_w) >= 3 and max_gap <= 2):
                same_slot_bundle_buyers.update(uniq_w)
                relationship_rows.append({
                    "mint": mint,
                    "category": "2_Same_slot_bundle_buyers",
                    "wallets_count": len(uniq_w),
                    "wallet_sample": ";".join(uniq_w[:5]),
                    "evidence": f"Contiguous txIndex (max_gap={max_gap}) in block {blk}",
                    "confidence": "MEDIUM_STRUCTURAL",
                    "proven_shared_control": 0,
                    "note": "Deterministic Jito/bundler execution pattern; requires funding/transfer link to prove single entity.",
                })
            else:
                same_slot_co_buyers.update(uniq_w)
                relationship_rows.append({
                    "mint": mint,
                    "category": "1_Same_slot_co_buyers",
                    "wallets_count": len(uniq_w),
                    "wallet_sample": ";".join(uniq_w[:5]),
                    "evidence": f"Co-bought in block {blk} (non-contiguous txIndex gap={max_gap})",
                    "confidence": "LOW_HEURISTIC",
                    "proven_shared_control": 0,
                    "note": "Same-slot co-purchase is NOT proof of shared control (independent bots/traders).",
                })

    # Pairwise & Creator verified checks (Categories 3, 4, 5, 6)
    creator_connected = set()
    shared_funder_wallets = set()
    directly_linked = set()
    repeated_co_snipers = set()

    for i, u in enumerate(participants):
        if creator and u != creator:
            if (creator, u) in direct_links or (u, creator) in direct_links or (wallet_private_funders[u] & wallet_private_funders.get(creator, set())):
                creator_connected.add(u)
                G_verified_insider.add_edge(creator, u, category="6_Creator_connected_wallets", confidence="HIGH_ONCHAIN")

        for j in range(i + 1, len(participants)):
            v = participants[j]
            if (u, v) in direct_links or (v, u) in direct_links:
                directly_linked.update([u, v])
                G_verified_insider.add_edge(u, v, category="4_Directly_linked_wallets", confidence="HIGH_ONCHAIN")
            else:
                sf = wallet_private_funders[u] & wallet_private_funders[v]
                if sf:
                    shared_funder_wallets.update([u, v])
                    G_verified_insider.add_edge(u, v, category="3_Shared_private_funder", confidence="HIGH_ONCHAIN")
                else:
                    pair_k = tuple(sorted((u, v)))
                    if co_sniper_pair_counts.get(pair_k, 0) >= 3:
                        repeated_co_snipers.update([u, v])

    if creator_connected:
        relationship_rows.append({
            "mint": mint,
            "category": "6_Creator_connected_wallets",
            "wallets_count": len(creator_connected),
            "wallet_sample": ";".join(sorted(creator_connected)[:5]),
            "evidence": "Direct SOL/SPL transfer or shared private funder with token creator",
            "confidence": "HIGH_ONCHAIN",
            "proven_shared_control": 1,
            "note": "Verified on-chain link to creator wallet.",
        })
    if directly_linked:
        relationship_rows.append({
            "mint": mint,
            "category": "4_Directly_linked_wallets",
            "wallets_count": len(directly_linked),
            "wallet_sample": ";".join(sorted(directly_linked)[:5]),
            "evidence": "Direct wallet-to-wallet SOL/SPL transfer verified via RPC",
            "confidence": "HIGH_ONCHAIN",
            "proven_shared_control": 1,
            "note": "Direct on-chain value transfer between buyer addresses.",
        })
    if shared_funder_wallets:
        relationship_rows.append({
            "mint": mint,
            "category": "3_Shared_private_funder",
            "wallets_count": len(shared_funder_wallets),
            "wallet_sample": ";".join(sorted(shared_funder_wallets)[:5]),
            "evidence": "Funded prior to trade by identical private low-frequency EOA",
            "confidence": "HIGH_ONCHAIN",
            "proven_shared_control": 1,
            "note": "Excludes high-frequency CEX/bridge hot wallets.",
        })
    if repeated_co_snipers:
        relationship_rows.append({
            "mint": mint,
            "category": "5_Repeated_co_snipers",
            "wallets_count": len(repeated_co_snipers),
            "wallet_sample": ";".join(sorted(repeated_co_snipers)[:5]),
            "evidence": "Co-entered top-15 early buyers across >=3 independent tokens",
            "confidence": "MEDIUM_BEHAVIORAL",
            "proven_shared_control": 0,
            "note": "Heuristic behavioral correlation; may reflect competing sniper bots triggering on same block.",
        })

    # Category 7: Confirmed technical addresses
    if token_technical_addrs:
        relationship_rows.append({
            "mint": mint,
            "category": "7_Confirmed_technical_addresses",
            "wallets_count": len(token_technical_addrs),
            "wallet_sample": ";".join(list(token_technical_addrs.keys())[:4]),
            "evidence": "Protocol vault, bonding curve, DEX LP pool, or SPL system program",
            "confidence": "CONFIRMED_SYSTEM",
            "proven_shared_control": 0,
            "note": "Excluded from human holder and insider supply metrics.",
        })

    # Category 8: Unknown relationship (explicitly noting absence of funder != independence!)
    known_special = creator_connected | directly_linked | shared_funder_wallets | same_slot_bundle_buyers | same_slot_co_buyers | repeated_co_snipers | ({creator} if creator else set())
    unknown_wallets = [w for w in participants if w not in known_special]
    if unknown_wallets:
        relationship_rows.append({
            "mint": mint,
            "category": "8_Unknown_relationship",
            "wallets_count": len(unknown_wallets),
            "wallet_sample": ";".join(unknown_wallets[:4]),
            "evidence": "No direct transfer or shared private funder observed in sampled history",
            "confidence": "UNKNOWN",
            "proven_shared_control": 0,
            "note": "Absence of detected funder does NOT prove independence (CEX/bridge/unindexed hops possible).",
        })

    # Calculate SEPARATED supply shares: Verified On-Chain Insiders vs Heuristic Bundles/Snipers!
    verified_insider_wallets = creator_connected | directly_linked | shared_funder_wallets | ({creator} if creator else set())
    heuristic_bundle_sniper_wallets = (same_slot_bundle_buyers | repeated_co_snipers) - verified_insider_wallets

    ver_ins_pct = round((sum(wallet_fifo_map.get(w, {}).get("remaining_fifo_tokens", 0.0) for w in verified_insider_wallets) / max(1.0, effective_supply)) * 100.0, 4)
    heur_bun_pct = round((sum(wallet_fifo_map.get(w, {}).get("remaining_fifo_tokens", 0.0) for w in heuristic_bundle_sniper_wallets) / max(1.0, effective_supply)) * 100.0, 4)

    summary_insider = {
        "mint": mint,
        "verified_onchain_insider_wallets_count": len(verified_insider_wallets),
        "verified_onchain_insider_supply_pct": ver_ins_pct,
        "heuristic_bundle_sniper_wallets_count": len(heuristic_bundle_sniper_wallets),
        "heuristic_bundle_sniper_supply_pct": heur_bun_pct,
        "same_slot_co_buyers_count_non_insider": len(same_slot_co_buyers),
        "unknown_relationship_wallets_count": len(unknown_wallets),
    }

    return relationship_rows, summary_insider
