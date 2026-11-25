"""
WALLET INTELLIGENCE V2.1, VALIDATED SUPPLY CONCENTRATION (`INVALID_SUPPLY_RECONSTRUCTION` guard),
AND STRICT FIFO REALIZED PNL (`UNKNOWN_COST_BASIS` guard) — P1 (Sections 5 & 6).
"""
from collections import deque, defaultdict, Counter
import numpy as np

from config_v2_1 import CONFIRMED_TECHNICAL_ADDRESSES
from feature_engine import deduplicate_and_filter_trades_before, build_token_technical_set, get_token_supply_at_birth

RELATIONSHIP_TYPES_V2_1 = [
    "same_slot_co_buyers",
    "same_slot_bundle_buyers",
    "shared_private_funder",
    "directly_linked_wallets",
    "repeated_co_snipers",
    "creator_connected_wallets",
    "exchange_funded_wallets",
    "unknown_relationship",
]

CONFIDENCE_LEVELS_V2_1 = [
    "confirmed_technical_relationship",
    "high_confidence",
    "medium_confidence",
    "low_confidence",
    "unknown",
]

def reconstruct_supply_and_fifo_v2_1(
    coin: dict,
    trades: list,
    spl_transfers: list,
    rpc_wallets_db: dict,
    mark_price_sol: float,
    sol_price_usd: float,
    cutoff_ts_ms: int,
    is_swap_tape_complete: bool,
    tx_fee_sol: float = 0.00015,
) -> dict:
    """
    Reconstructs:
    1. Deduplicated, LP/pool/burn/technical-excluded holder balances and validates `sum <= 100%`.
       Any token where off-swap transfers or missing LP pool addresses cause holder sum > 100%
       is flagged `INVALID_SUPPLY_RECONSTRUCTION` and blocked from model usage!
    2. Strict FIFO cost-basis PnL per wallet, separating:
       - `realized_pnl_sol` (ONLY when cost basis of all sold tokens is known; otherwise `None` + `UNKNOWN_COST_BASIS`!),
       - `unrealized_pnl_sol`,
       - `internal_transfer_in_tokens` / `internal_transfer_out_tokens`,
       - `non_token_sol_flows_sol` (from RPC native SOL transfers unrelated to this token's swaps),
       - `fees_paid_sol`.
    """
    dedup_trades = deduplicate_and_filter_trades_before(trades, cutoff_ts_ms)
    tok_tech = build_token_technical_set(coin, dedup_trades)
    birth_supply = get_token_supply_at_birth(coin)

    fifo_lots = defaultdict(deque)  # wallet -> deque([qty, unit_cost_sol])
    w_ledger = defaultdict(lambda: {
        "tokens_bought": 0.0,
        "tokens_sold": 0.0,
        "matched_sold_tokens": 0.0,
        "unmatched_sold_tokens": 0.0,
        "sol_spent_swaps": 0.0,
        "sol_received_swaps": 0.0,
        "fees_paid_sol": 0.0,
        "fifo_realized_pnl_sol_acc": 0.0,
        "internal_transfer_in_tokens": 0.0,
        "internal_transfer_out_tokens": 0.0,
        "buy_count": 0,
        "sell_count": 0,
    })

    events = []
    for tr in dedup_trades:
        events.append((int(tr["blockTimeMs"]), 0, "swap", tr))
    for tf in spl_transfers:
        tms = int(tf.get("blockTimeMs") or 0)
        if 0 < tms <= cutoff_ts_ms:
            events.append((tms, 1, "spl", tf))
    events.sort(key=lambda x: (x[0], x[1]))

    burned_tokens = 0.0
    seen_spl_sigs = set()

    for tms, _, ekind, obj in events:
        if ekind == "swap":
            w = str((obj.get("trader") or {}).get("address") or "")
            if not w or w in tok_tech:
                continue
            dec = int((obj.get("baseAmount") or {}).get("decimals") or 6)
            qty = float((obj.get("baseAmount") or {}).get("raw") or 0.0) / (10 ** dec)
            if qty <= 0:
                continue
            val_sol = float(obj.get("valueNative") or 0.0)
            side = obj.get("side")
            rec = w_ledger[w]

            if side == "buy":
                cost_sol = val_sol + tx_fee_sol
                fifo_lots[w].append([qty, cost_sol / qty])
                rec["tokens_bought"] += qty
                rec["sol_spent_swaps"] += val_sol
                rec["fees_paid_sol"] += tx_fee_sol
                rec["buy_count"] += 1

            elif side == "sell":
                net_sol = max(0.0, val_sol - tx_fee_sol)
                sell_u_sol = net_sol / qty
                rec["tokens_sold"] += qty
                rec["sol_received_swaps"] += val_sol
                rec["fees_paid_sol"] += tx_fee_sol
                rec["sell_count"] += 1

                rem = qty
                q = fifo_lots[w]
                while rem > 1e-9 and q:
                    lq, lu_cost = q[0]
                    take = min(rem, lq)
                    rec["matched_sold_tokens"] += take
                    rec["fifo_realized_pnl_sol_acc"] += take * (sell_u_sol - lu_cost)
                    rem -= take
                    if take >= lq - 1e-9:
                        q.popleft()
                    else:
                        q[0][0] -= take

                if rem > 1e-6:
                    rec["unmatched_sold_tokens"] += rem

        elif ekind == "spl":
            sig_k = (obj.get("tx") or "", obj.get("source_owner") or "", obj.get("dest_owner") or "", float(obj.get("amount_tokens") or 0))
            if sig_k in seen_spl_sigs:
                continue
            seen_spl_sigs.add(sig_k)
            src = str(obj.get("source_owner") or "")
            dst = str(obj.get("dest_owner") or "")
            qty = float(obj.get("amount_tokens") or 0.0)
            if qty <= 0:
                continue
            if obj.get("is_burn") or dst in ("11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111"):
                burned_tokens += qty
            if src and src not in tok_tech:
                w_ledger[src]["internal_transfer_out_tokens"] += qty
                rem = qty
                q_s = fifo_lots[src]
                carried = []
                while rem > 1e-9 and q_s:
                    lq, luc = q_s[0]
                    take = min(rem, lq)
                    carried.append([take, luc])
                    rem -= take
                    if take >= lq - 1e-9:
                        q_s.popleft()
                    else:
                        q_s[0][0] -= take
                if dst and dst not in tok_tech:
                    w_ledger[dst]["internal_transfer_in_tokens"] += qty
                    for c_lot in carried:
                        fifo_lots[dst].append(c_lot)

    effective_supply = max(1.0, birth_supply - burned_tokens)

    wallet_pnl_out = {}
    holder_balances = {}

    for w, rec in w_ledger.items():
        if w in tok_tech:
            continue
        q = fifo_lots[w]
        rem_qty = sum(l[0] for l in q)
        rem_cost_sol = sum(l[0] * l[1] for l in q)
        if rem_qty > 0:
            holder_balances[w] = rem_qty

        rpc_info = rpc_wallets_db.get(w, {})
        non_tok_sol_in = sum(float(x.get("sol") or 0) for x in rpc_info.get("funders", []) if int(x.get("blockTime") or 0) * 1000 <= cutoff_ts_ms)
        non_tok_sol_out = sum(float(x.get("sol") or 0) for x in rpc_info.get("outbound_targets", []) if int(x.get("blockTime") or 0) * 1000 <= cutoff_ts_ms)

        if rec["unmatched_sold_tokens"] > 1e-4:
            cb_status = "UNKNOWN_COST_BASIS"
            realized_sol = None
            realized_usd = None
        else:
            cb_status = "FIFO_VERIFIED" if is_swap_tape_complete else "FIFO_PARTIAL_TAPE"
            realized_sol = round(rec["fifo_realized_pnl_sol_acc"], 6)
            realized_usd = round(realized_sol * sol_price_usd, 2)

        unreal_sol = round(rem_qty * mark_price_sol - rem_cost_sol, 6) if rem_qty > 0 else 0.0

        wallet_pnl_out[w] = {
            "tokens_bought": round(rec["tokens_bought"], 4),
            "tokens_sold": round(rec["tokens_sold"], 4),
            "matched_sold_tokens": round(rec["matched_sold_tokens"], 4),
            "unmatched_sold_tokens": round(rec["unmatched_sold_tokens"], 4),
            "fees_paid_sol": round(rec["fees_paid_sol"], 6),
            "cost_basis_status": cb_status,
            "fifo_realized_pnl_sol": realized_sol,
            "fifo_realized_pnl_usd": realized_usd,
            "remaining_tokens": round(rem_qty, 4),
            "remaining_cost_basis_sol": round(rem_cost_sol, 6),
            "fifo_unrealized_pnl_sol": unreal_sol,
            "internal_transfer_in_tokens": round(rec["internal_transfer_in_tokens"], 4),
            "internal_transfer_out_tokens": round(rec["internal_transfer_out_tokens"], 4),
            "non_token_sol_flows_net_sol": round(non_tok_sol_in - non_tok_sol_out, 6),
        }

    sorted_bals = sorted(holder_balances.values(), reverse=True)
    sum_holders = sum(sorted_bals)

    # STRICT INVARIANT (Section 6): Holder sum MUST NOT exceed effective_supply!
    if sum_holders > effective_supply * 1.0001:
        supply_out = {
            "supply_status": "INVALID_SUPPLY_RECONSTRUCTION",
            "usable_in_model": 0,
            "birth_supply": birth_supply,
            "burned_tokens": round(burned_tokens, 2),
            "effective_supply": round(effective_supply, 2),
            "raw_reconstructed_holder_sum_pct": round((sum_holders / effective_supply) * 100.0, 4),
            "lp_and_curve_vault_pct": None,
            "top1_holder_pct": None,
            "top5_holders_pct": None,
            "top10_holders_pct": None,
            "top20_holders_pct": None,
            "active_human_holders": len(sorted_bals),
            "invalid_reason": "Off-swap SPL transfer or secondary unindexed LP deposit created >100% swap-ledger balance sum",
        }
    else:
        lp_residual = max(0.0, effective_supply - sum_holders)
        supply_out = {
            "supply_status": "VALID_RECONSTRUCTION" if is_swap_tape_complete else "APPROXIMATE_PARTIAL_TAPE",
            "usable_in_model": 1,
            "birth_supply": birth_supply,
            "burned_tokens": round(burned_tokens, 2),
            "effective_supply": round(effective_supply, 2),
            "raw_reconstructed_holder_sum_pct": round((sum_holders / effective_supply) * 100.0, 4),
            "lp_and_curve_vault_pct": round((lp_residual / effective_supply) * 100.0, 4),
            "top1_holder_pct": round((sum(sorted_bals[:1]) / effective_supply) * 100.0, 4),
            "top5_holders_pct": round((sum(sorted_bals[:5]) / effective_supply) * 100.0, 4),
            "top10_holders_pct": round((sum(sorted_bals[:10]) / effective_supply) * 100.0, 4),
            "top20_holders_pct": round((sum(sorted_bals[:20]) / effective_supply) * 100.0, 4),
            "active_human_holders": len(sorted_bals),
            "invalid_reason": "",
        }

    return {"supply": supply_out, "wallets_pnl": wallet_pnl_out, "technical_excluded_count": len(tok_tech)}


def classify_relationships_v2_1(
    mint: str,
    creator: str,
    trades: list,
    tok_tech_addrs: set,
    rpc_wallets_db: dict,
    funder_types: dict,
    co_sniper_counts: Counter,
    cutoff_ts_ms: int,
) -> list:
    """
    Classifies wallet relationships into the 8 mandatory V2.1 categories with the 5 exact confidence levels,
    using ONLY events at or before `cutoff_ts_ms`. Never assigns real-world owner identities.
    """
    vis_trades = deduplicate_and_filter_trades_before(trades, cutoff_ts_ms)
    participants = list(dict.fromkeys([
        str((tr.get("trader") or {}).get("address") or "")
        for tr in vis_trades
        if (tr.get("trader") or {}).get("address") and str((tr.get("trader") or {}).get("address")) not in tok_tech_addrs
    ]))

    private_funders = defaultdict(set)
    exchange_funded = set()
    direct_links = set()

    for w in participants + ([creator] if creator else []):
        rinfo = rpc_wallets_db.get(w, {})
        w_conf = rinfo.get("data_confidence", "unknown")
        for fo in rinfo.get("funders", []):
            if int(fo.get("blockTime") or 0) * 1000 > cutoff_ts_ms:
                continue
            f_addr = fo["funder"]
            ft = funder_types.get(f_addr, {}).get("type", "PRIVATE_FUNDER")
            if ft == "CEX_OR_EXCHANGE_HOTWALLET":
                exchange_funded.add(w)
            else:
                private_funders[w].add((f_addr, w_conf))
                direct_links.add((f_addr, w))
        for oo in rinfo.get("outbound_targets", []):
            if int(oo.get("blockTime") or 0) * 1000 <= cutoff_ts_ms:
                direct_links.add((w, oo["target"]))

    rows = []
    # Technical addresses record
    rows.append({
        "mint": mint,
        "relationship_type": "confirmed_technical_addresses",
        "confidence_level": "confirmed_technical_relationship",
        "wallets_count": len(tok_tech_addrs),
        "wallet_sample": ";".join(sorted(tok_tech_addrs)[:4]),
        "shared_control_proven": 0,
        "evidence": "Bonding curve, AMM pool vault, burn, or SPL system program",
    })

    # Slot analysis (same-slot co-buyers vs same-slot bundle buyers)
    first_blk = int(vis_trades[0].get("blockId") or 0) if vis_trades else 0
    slot_map = defaultdict(list)
    for tr in vis_trades:
        if tr.get("side") == "buy":
            w = str((tr.get("trader") or {}).get("address") or "")
            if w and w not in tok_tech_addrs:
                slot_map[int(tr.get("blockId") or 0)].append((int(tr.get("txIndex") or 0), w))

    co_buyers_set = set()
    bundle_buyers_set = set()
    for blk, items in slot_map.items():
        items.sort()
        uw = list(dict.fromkeys([w for _, w in items]))
        if len(uw) >= 2:
            gaps = [items[k+1][0] - items[k][0] for k in range(len(items)-1)]
            max_gap = max(gaps) if gaps else 99
            if (blk == first_blk and max_gap <= 2) or (len(uw) >= 3 and max_gap <= 2):
                bundle_buyers_set.update(uw)
            else:
                co_buyers_set.update(uw)

    if bundle_buyers_set:
        rows.append({
            "mint": mint,
            "relationship_type": "same_slot_bundle_buyers",
            "confidence_level": "medium_confidence",
            "wallets_count": len(bundle_buyers_set),
            "wallet_sample": ";".join(sorted(bundle_buyers_set)[:5]),
            "shared_control_proven": 0,
            "evidence": "Contiguous txIndex execution in launch slot (structural bundle; not standalone proof of identity)",
        })
    if co_buyers_set:
        rows.append({
            "mint": mint,
            "relationship_type": "same_slot_co_buyers",
            "confidence_level": "low_confidence",
            "wallets_count": len(co_buyers_set),
            "wallet_sample": ";".join(sorted(co_buyers_set)[:5]),
            "shared_control_proven": 0,
            "evidence": "Non-contiguous purchases in same block (explicitly NOT proof of shared control)",
        })

    creator_conn = set()
    direct_set = set()
    shared_priv_set = set()
    co_sniper_set = set()

    cr_funders = {f for f, _ in private_funders.get(creator, set())} if creator else set()

    for i, u in enumerate(participants):
        u_f = {f for f, _ in private_funders.get(u, set())}
        if creator and u != creator:
            if (creator, u) in direct_links or (u, creator) in direct_links or (u_f & cr_funders):
                creator_conn.add(u)
        for j in range(i + 1, len(participants)):
            v = participants[j]
            v_f = {f for f, _ in private_funders.get(v, set())}
            if (u, v) in direct_links or (v, u) in direct_links:
                direct_set.update([u, v])
            elif u_f & v_f:
                shared_priv_set.update([u, v])
            elif co_sniper_counts.get(tuple(sorted((u, v))), 0) >= 3:
                co_sniper_set.update([u, v])

    def cap_conf_by_history(w_set: set, target_conf: str) -> str:
        # Section 5: If full history is not available on involved wallets, cap confidence below high_confidence!
        all_complete = all(rpc_wallets_db.get(w, {}).get("history_complete", False) for w in w_set) if w_set else False
        if target_conf == "high_confidence" and not all_complete:
            return "medium_confidence"
        return target_conf

    if creator_conn:
        rows.append({
            "mint": mint,
            "relationship_type": "creator_connected_wallets",
            "confidence_level": cap_conf_by_history(creator_conn, "high_confidence"),
            "wallets_count": len(creator_conn),
            "wallet_sample": ";".join(sorted(creator_conn)[:5]),
            "shared_control_proven": 1,
            "evidence": "On-chain SOL/SPL transfer or shared private funder with creator wallet",
        })
    if direct_set:
        rows.append({
            "mint": mint,
            "relationship_type": "directly_linked_wallets",
            "confidence_level": cap_conf_by_history(direct_set, "high_confidence"),
            "wallets_count": len(direct_set),
            "wallet_sample": ";".join(sorted(direct_set)[:5]),
            "shared_control_proven": 1,
            "evidence": "Direct wallet-to-wallet SOL or SPL transfer",
        })
    if shared_priv_set:
        rows.append({
            "mint": mint,
            "relationship_type": "shared_private_funder",
            "confidence_level": cap_conf_by_history(shared_priv_set, "high_confidence"),
            "wallets_count": len(shared_priv_set),
            "wallet_sample": ";".join(sorted(shared_priv_set)[:5]),
            "shared_control_proven": 1,
            "evidence": "Funded prior to purchase by identical non-exchange private wallet",
        })
    if co_sniper_set:
        rows.append({
            "mint": mint,
            "relationship_type": "repeated_co_snipers",
            "confidence_level": "low_confidence",
            "wallets_count": len(co_sniper_set),
            "wallet_sample": ";".join(sorted(co_sniper_set)[:5]),
            "shared_control_proven": 0,
            "evidence": "Repeated early entry on >=3 independent tokens (behavioral correlation only)",
        })
    if exchange_funded:
        rows.append({
            "mint": mint,
            "relationship_type": "exchange_funded_wallets",
            "confidence_level": "medium_confidence",
            "wallets_count": len(exchange_funded),
            "wallet_sample": ";".join(sorted(exchange_funded)[:5]),
            "shared_control_proven": 0,
            "evidence": "Funded by high-frequency CEX/service hot wallet (independent users sharing exchange)",
        })

    classified_any = creator_conn | direct_set | shared_priv_set | co_sniper_set | exchange_funded | bundle_buyers_set | co_buyers_set
    unknown_w = [w for w in participants if w not in classified_any]
    if unknown_w:
        rows.append({
            "mint": mint,
            "relationship_type": "unknown_relationship",
            "confidence_level": "unknown",
            "wallets_count": len(unknown_w),
            "wallet_sample": ";".join(unknown_w[:5]),
            "shared_control_proven": 0,
            "evidence": "Insufficient or unlinked history (not assumed independent)",
        })

    return rows
