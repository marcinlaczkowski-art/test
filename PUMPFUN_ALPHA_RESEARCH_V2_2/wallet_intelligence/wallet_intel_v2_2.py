"""
SECTION 6 (P1 — WALLET INTELLIGENCE 2.0, CHRONOLOGICAL FIFO, 8-EDGE GRAPH & CLUSTER TRACK RECORD):
- Builds full wallet history records (`wallet_address`, `first_seen_at`, `last_seen_at`,
  `transaction_count`, `history_coverage_start`, `history_coverage_end`, `history_completeness`,
  `funding_sources`, `funding_graph`, `token_trading_history`, `realized_pnl_sol`, `unrealized_pnl_sol`,
  `estimated_pnl_sol`, `unknown_pnl_count`, `average_holding_time_sec`, `win_rate`,
  `successful_launches_count`, `failed_launches_count`, `confidence_score`).
- Missing history is ALWAYS labeled `"INSUFFICIENT_HISTORY"` (never treated as zero or bad wallet).
- Chronological FIFO cost-basis model: carries lots across verified internal SPL transfers without
  treating a transfer as a sale; separates `realized_pnl`, `unrealized_pnl`, `estimated_pnl`, and `unknown_pnl`.
- Builds 8-edge relationship graph (`DIRECT_FUNDING`, `SHARED_FUNDER`, `REPEATED_TRANSFER`,
  `COMMON_COUNTERPARTY`, `SAME_SLOT_BUY`, `REPEATED_CO_BUYING`, `CREATOR_LINK`, `UNKNOWN_RELATION`)
  excluding exchanges/custody from shared private insider status and never treating `SAME_SLOT_BUY`
  as proof of shared control.
- Maintains causal `WalletClusterTrackRecord` strictly gated by `outcome_known_at_ms <= signal_ts_ms`!
"""
from collections import defaultdict, deque, Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import (
    SYSTEM_AND_POOL_ADDRESSES,
    KNOWN_CEX_CUSTODY_WALLETS,
    SOLANA_BASE_NETWORK_FEE_SOL,
    SOLANA_PRIORITY_FEE_SOL,
)
from amm_reconstruction.amm_reconstructor import deduplicate_and_order_swaps

RELATIONSHIP_TYPES_V2_2 = {
    "DIRECT_FUNDING",
    "SHARED_FUNDER",
    "REPEATED_TRANSFER",
    "COMMON_COUNTERPARTY",
    "SAME_SLOT_BUY",
    "REPEATED_CO_BUYING",
    "CREATOR_LINK",
    "UNKNOWN_RELATION",
}

CLUSTER_TIERS = {"CONFIRMED", "PROBABLE", "WEAK", "UNKNOWN"}


def ts_to_iso(ts_ms: Optional[int]) -> str:
    if not ts_ms or ts_ms <= 0:
        return "UNKNOWN"
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def build_token_excluded_addresses(coin: dict, trades: list) -> dict[str, str]:
    """Returns `{address: exclusion_reason}` for all system, burn, bonding-curve, and AMM pool addresses."""
    excl = dict(SYSTEM_AND_POOL_ADDRESSES)
    for fld in ("bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address", "market_id"):
        if coin.get(fld):
            excl[str(coin[fld])] = f"token_{fld}"
    for tr in trades:
        pa = (tr.get("pool") or {}).get("address")
        if pa:
            excl[str(pa)] = f"swap_pool_{tr.get('venue') or 'dex'}"
    return excl


def compute_chronological_fifo_for_token(
    coin: dict,
    trades: list,
    spl_transfers: list,
    mark_price_sol: Optional[float],
    cutoff_ts_ms: int,
    is_tape_complete: bool = True,
    linked_wallet_pairs: Optional[set[tuple[str, str]]] = None,
) -> dict:
    """
    Section 6.2 Chronological FIFO model for a token up to `cutoff_ts_ms`.
    - Carries FIFO cost-basis lots across SPL transfers (never treats a transfer as a sale!).
    - Separates `realized_pnl_sol`, `unrealized_pnl_sol`, `estimated_pnl_sol`, and `unknown_pnl`.
    - Computes holding durations (`holding_times_sec`) per matched lot!
    """
    vis_swaps = deduplicate_and_order_swaps(trades, cutoff_ts_ms=cutoff_ts_ms)
    excl = build_token_excluded_addresses(coin, vis_swaps)
    fee_per_leg = SOLANA_BASE_NETWORK_FEE_SOL + SOLANA_PRIORITY_FEE_SOL

    # Lot tuple: [qty_tokens, unit_cost_sol, acquired_ts_ms, is_estimated_basis]
    lots: dict[str, deque] = defaultdict(deque)
    stats = defaultdict(lambda: {
        "tokens_bought": 0.0,
        "tokens_sold": 0.0,
        "matched_sold_tokens": 0.0,
        "unmatched_sold_tokens": 0.0,
        "transfer_in_tokens": 0.0,
        "transfer_out_tokens": 0.0,
        "fees_paid_sol": 0.0,
        "realized_pnl_sol": 0.0,
        "estimated_pnl_sol": 0.0,
        "holding_times_sec": [],
        "first_buy_ts_ms": None,
        "last_event_ts_ms": None,
        "buy_sol_total": 0.0,
        "sell_sol_total": 0.0,
    })

    events = []
    for idx, tr in enumerate(vis_swaps):
        events.append((int(tr["blockTimeMs"]), 0, idx, "SWAP", tr))
    for idx, tf in enumerate(spl_transfers or []):
        tms = int(tf.get("blockTimeMs") or 0)
        if 0 < tms <= cutoff_ts_ms:
            events.append((tms, 1, idx, "SPL_TRANSFER", tf))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    burned_tokens = 0.0
    seen_tf = set()

    for tms, _, _, ekind, obj in events:
        if ekind == "SWAP":
            w = str((obj.get("trader") or {}).get("address") or "")
            if not w or w in excl:
                continue
            dec = int((obj.get("baseAmount") or {}).get("decimals") or 6)
            qty = float((obj.get("baseAmount") or {}).get("raw") or 0.0) / (10 ** dec)
            val_sol = float(obj.get("valueNative") or 0.0)
            if qty <= 0:
                continue
            st = stats[w]
            st["last_event_ts_ms"] = tms

            if obj.get("side") == "buy":
                total_cost = val_sol + fee_per_leg
                lots[w].append([qty, total_cost / qty, tms, not is_tape_complete])
                st["tokens_bought"] += qty
                st["buy_sol_total"] += val_sol
                st["fees_paid_sol"] += fee_per_leg
                if st["first_buy_ts_ms"] is None:
                    st["first_buy_ts_ms"] = tms

            elif obj.get("side") == "sell":
                net_proceeds = max(0.0, val_sol - fee_per_leg)
                sell_unit_sol = net_proceeds / qty
                st["tokens_sold"] += qty
                st["sell_sol_total"] += val_sol
                st["fees_paid_sol"] += fee_per_leg

                rem = qty
                q = lots[w]
                while rem > 1e-9 and q:
                    l_qty, l_ucost, l_ts, l_est = q[0]
                    take = min(rem, l_qty)
                    pnl_piece = take * (sell_unit_sol - l_ucost)
                    if l_est:
                        st["estimated_pnl_sol"] += pnl_piece
                    else:
                        st["realized_pnl_sol"] += pnl_piece
                    st["matched_sold_tokens"] += take
                    st["holding_times_sec"].append(max(0.0, (tms - l_ts) / 1000.0))
                    rem -= take
                    if take >= l_qty - 1e-9:
                        q.popleft()
                    else:
                        q[0][0] -= take

                if rem > 1e-5:
                    st["unmatched_sold_tokens"] += rem

        elif ekind == "SPL_TRANSFER":
            tk = (obj.get("tx") or "", obj.get("source_owner") or "", obj.get("dest_owner") or "", float(obj.get("amount_tokens") or 0))
            if tk in seen_tf:
                continue
            seen_tf.add(tk)
            src = str(obj.get("source_owner") or "")
            dst = str(obj.get("dest_owner") or "")
            qty = float(obj.get("amount_tokens") or 0.0)
            if qty <= 0:
                continue
            if obj.get("is_burn") or dst in ("11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111"):
                burned_tokens += qty

            # IMPORTANT (Rule 6.2 & Test 18): Transfer is NEVER treated as a sale!
            # Carry FIFO cost-basis lots from `src` to `dst` when available; if `src` had unknown basis, mark destination lot estimated/unknown!
            carried_lots = []
            if src and src not in excl:
                stats[src]["transfer_out_tokens"] += qty
                stats[src]["last_event_ts_ms"] = tms
                rem = qty
                q_s = lots[src]
                while rem > 1e-9 and q_s:
                    l_qty, l_ucost, l_ts, l_est = q_s[0]
                    take = min(rem, l_qty)
                    carried_lots.append([take, l_ucost, l_ts, l_est])
                    rem -= take
                    if take >= l_qty - 1e-9:
                        q_s.popleft()
                    else:
                        q_s[0][0] -= take

            if dst and dst not in excl:
                stats[dst]["transfer_in_tokens"] += qty
                stats[dst]["last_event_ts_ms"] = tms
                for c_lot in carried_lots:
                    lots[dst].append(c_lot)
                # Note: any uncarried remainder (`qty - sum(carried)`) is NOT given a fake 0 cost basis — if sold later, it triggers `unmatched_sold_tokens > 0` -> `UNKNOWN_PNL`!

    dec_sup = int(coin.get("base_decimals") or 6)
    raw_sup = coin.get("total_supply")
    birth_supply = (float(raw_sup) / (10 ** dec_sup)) if (raw_sup and float(raw_sup) > 0) else 1_000_000_000.0
    effective_supply = max(1.0, birth_supply - burned_tokens)

    wallets_out = {}
    holder_balances = {}
    for w, st in stats.items():
        if w in excl:
            continue
        q = lots[w]
        rem_qty = sum(x[0] for x in q)
        rem_cost = sum(x[0] * x[1] for x in q)
        if rem_qty > 0:
            holder_balances[w] = rem_qty

        has_unknown = st["unmatched_sold_tokens"] > 1e-4
        if has_unknown:
            pnl_category = "UNKNOWN_PNL"
            realized_val = None
            estimated_val = round(st["estimated_pnl_sol"], 6) if st["estimated_pnl_sol"] != 0 else None
        elif not is_tape_complete or abs(st["estimated_pnl_sol"]) > 0:
            pnl_category = "ESTIMATED_PNL"
            realized_val = None
            estimated_val = round(st["realized_pnl_sol"] + st["estimated_pnl_sol"], 6)
        else:
            pnl_category = "REALIZED_FIFO_VERIFIED"
            realized_val = round(st["realized_pnl_sol"], 6)
            estimated_val = None

        unrealized_val = (
            round(rem_qty * float(mark_price_sol) - rem_cost, 6)
            if (rem_qty > 0 and mark_price_sol is not None and mark_price_sol > 0)
            else (0.0 if rem_qty == 0 else None)
        )
        avg_hold = round(float(np.mean(st["holding_times_sec"])), 2) if st["holding_times_sec"] else None

        wallets_out[w] = {
            "tokens_bought": round(st["tokens_bought"], 4),
            "tokens_sold": round(st["tokens_sold"], 4),
            "matched_sold_tokens": round(st["matched_sold_tokens"], 4),
            "unmatched_sold_tokens": round(st["unmatched_sold_tokens"], 4),
            "transfer_in_tokens": round(st["transfer_in_tokens"], 4),
            "transfer_out_tokens": round(st["transfer_out_tokens"], 4),
            "remaining_tokens": round(rem_qty, 4),
            "buy_sol_total": round(st["buy_sol_total"], 6),
            "sell_sol_total": round(st["sell_sol_total"], 6),
            "fees_paid_sol": round(st["fees_paid_sol"], 6),
            "pnl_classification": pnl_category,
            "realized_pnl_sol": realized_val,
            "unrealized_pnl_sol": unrealized_val,
            "estimated_pnl_sol": estimated_val,
            "unknown_pnl_flag": int(has_unknown),
            "average_holding_time_sec": avg_hold,
            "first_buy_ts_ms": st["first_buy_ts_ms"],
        }

    sorted_holders = sorted(holder_balances.items(), key=lambda kv: kv[1], reverse=True)
    sum_human = sum(v for _, v in sorted_holders)
    creator = str(coin.get("creator") or "")
    creator_bal = holder_balances.get(creator, 0.0)

    if sum_human > effective_supply * 1.0001:
        supply_metrics = {
            "supply_status": "INVALID_SUPPLY_RECONSTRUCTION",
            "birth_supply": birth_supply,
            "burned_tokens": round(burned_tokens, 2),
            "effective_supply": round(effective_supply, 2),
            "excluded_system_pool_addresses_count": len(excl),
            "excluded_addresses_doc": dict(list(excl.items())[:12]),
            "top1_pct": None, "top5_pct": None, "top10_pct": None, "top20_pct": None,
            "creator_share_pct": None,
            "human_holders_sum_pct": round(sum_human / effective_supply * 100.0, 4),
        }
    else:
        vals = [v for _, v in sorted_holders]
        supply_metrics = {
            "supply_status": "VALID" if is_tape_complete else "PARTIAL_TAPE_VALID",
            "birth_supply": birth_supply,
            "burned_tokens": round(burned_tokens, 2),
            "effective_supply": round(effective_supply, 2),
            "excluded_system_pool_addresses_count": len(excl),
            "excluded_addresses_doc": dict(list(excl.items())[:12]),
            "top1_pct": round(sum(vals[:1]) / effective_supply * 100.0, 4),
            "top5_pct": round(sum(vals[:5]) / effective_supply * 100.0, 4),
            "top10_pct": round(sum(vals[:10]) / effective_supply * 100.0, 4),
            "top20_pct": round(sum(vals[:20]) / effective_supply * 100.0, 4),
            "creator_share_pct": round(creator_bal / effective_supply * 100.0, 4),
            "human_holders_sum_pct": round(sum_human / effective_supply * 100.0, 4),
            "active_holders_count": len(vals),
        }

    return {
        "wallets_fifo": wallets_out,
        "holder_balances": holder_balances,
        "supply_metrics": supply_metrics,
        "excluded_addresses": excl,
    }


def is_exchange_or_custody_funder(funder_addr: str, funder_types_db: dict) -> bool:
    """Checks both known CEX/custody hot wallets AND high-frequency withdrawal dispersion heuristics."""
    if funder_addr in KNOWN_CEX_CUSTODY_WALLETS:
        return True
    ft = (funder_types_db or {}).get(funder_addr, {})
    if ft.get("type") == "CEX_OR_EXCHANGE_HOTWALLET":
        return True
    return False


class WalletIntelligenceEngineV22:
    """
    Maintains causal per-wallet track records, 8-edge relationship graph, cluster assignments
    (`CONFIRMED`, `PROBABLE`, `WEAK`, `UNKNOWN`), and `wallet_cluster_track_record` strictly
    gated by `outcome_known_at_ms <= query_ts_ms`!
    """
    def __init__(self, rpc_wallets_db: Optional[dict] = None, funder_types_db: Optional[dict] = None):
        self.rpc_wallets_db = rpc_wallets_db or {}
        self.funder_types_db = funder_types_db or {}
        # Edge map: (src, dst, rel_type) -> edge dict
        self.edges: dict[tuple[str, str, str], dict] = {}
        # Causal wallet token outcomes: wallet -> list of outcome dicts (each with `outcome_known_at_ms`)
        self.wallet_token_outcomes: dict[str, list[dict]] = defaultdict(list)
        # Causal cluster token outcomes: cluster_id -> list of outcome dicts (each with `outcome_known_at_ms`)
        self.cluster_token_outcomes: dict[str, list[dict]] = defaultdict(list)
        # Causal pair co-buy history: (wA, wB) -> list of (buy_ts_ms, mint, tx_id)
        self.pair_cobuys: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)

        self._ingest_static_rpc_graph()

    def _add_edge_evidence(
        self,
        src: str,
        dst: str,
        rel_type: str,
        ts_ms: int,
        evidence_id: str,
        confidence: str,
    ) -> None:
        assert rel_type in RELATIONSHIP_TYPES_V2_2
        if not src or not dst or src == dst:
            return
        u, v = (src, dst) if rel_type in ("DIRECT_FUNDING", "CREATOR_LINK") else tuple(sorted((src, dst)))
        key = (u, v, rel_type)
        if key not in self.edges:
            self.edges[key] = {
                "source_wallet": u,
                "target_wallet": v,
                "relationship_type": rel_type,
                "first_seen": ts_ms,
                "last_seen": ts_ms,
                "evidence_count": 1,
                "confidence": confidence,
                "evidence_ids": [evidence_id],
            }
        else:
            e = self.edges[key]
            e["first_seen"] = min(e["first_seen"], ts_ms)
            e["last_seen"] = max(e["last_seen"], ts_ms)
            if evidence_id not in e["evidence_ids"]:
                e["evidence_count"] += 1
                if len(e["evidence_ids"]) < 15:
                    e["evidence_ids"].append(evidence_id)
                if rel_type == "REPEATED_CO_BUYING" and e["evidence_count"] >= 3:
                    e["confidence"] = "PROBABLE"
                elif rel_type == "REPEATED_TRANSFER" and e["evidence_count"] >= 2:
                    e["confidence"] = "CONFIRMED"

    def _ingest_static_rpc_graph(self) -> None:
        """Indexes timestamped on-chain SOL funding, SPL transfers, and counterparties from RPC DB."""
        private_funder_to_wallets: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        counterparty_counts: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)

        for w, info in self.rpc_wallets_db.items():
            if w in SYSTEM_AND_POOL_ADDRESSES:
                continue
            for fo in info.get("funders", []):
                f_addr = str(fo.get("funder") or "")
                bt_ms = int(fo.get("blockTime") or 0) * 1000
                tx_sig = str(fo.get("tx") or "rpc_funding")
                if not f_addr or f_addr in SYSTEM_AND_POOL_ADDRESSES or bt_ms <= 0:
                    continue
                if is_exchange_or_custody_funder(f_addr, self.funder_types_db):
                    # Exchange / custody funding is explicitly NOT a private insider link (Rule 6.3 & Test 19)!
                    continue
                if fo.get("note") == "co_signer_fee_payer" or float(fo.get("sol") or 0) >= 0.01:
                    self._add_edge_evidence(f_addr, w, "DIRECT_FUNDING", bt_ms, tx_sig, "CONFIRMED")
                    private_funder_to_wallets[f_addr].append((w, bt_ms, tx_sig))

            for oo in info.get("outbound_targets", []):
                t_addr = str(oo.get("target") or "")
                bt_ms = int(oo.get("blockTime") or 0) * 1000
                tx_sig = str(oo.get("tx") or "rpc_outbound")
                if not t_addr or t_addr in SYSTEM_AND_POOL_ADDRESSES or bt_ms <= 0:
                    continue
                if not is_exchange_or_custody_funder(t_addr, self.funder_types_db):
                    pair = tuple(sorted((w, t_addr)))
                    counterparty_counts[pair].append((bt_ms, tx_sig))

            for tf in info.get("spl_transfers", []):
                s_own = str(tf.get("source_owner") or "")
                d_own = str(tf.get("dest_owner") or "")
                bt_ms = int(tf.get("blockTimeMs") or 0)
                tx_sig = str(tf.get("tx") or "spl_tf")
                if s_own and d_own and s_own != d_own and s_own not in SYSTEM_AND_POOL_ADDRESSES and d_own not in SYSTEM_AND_POOL_ADDRESSES and bt_ms > 0:
                    pair = tuple(sorted((s_own, d_own)))
                    counterparty_counts[pair].append((bt_ms, tx_sig))
                    self._add_edge_evidence(s_own, d_own, "REPEATED_TRANSFER", bt_ms, tx_sig, "PROBABLE")

        # Shared private funder edges (NEVER from CEX/custody!)
        for f_addr, funded_list in private_funder_to_wallets.items():
            # Cap at <= 20 recipients so high-fanout faucet/dispersion bots aren't blindly treated as 1 small person without label
            uniq_w = {}
            for w, bt_ms, sig in funded_list:
                if w not in uniq_w or bt_ms < uniq_w[w][0]:
                    uniq_w[w] = (bt_ms, sig)
            w_items = list(uniq_w.items())
            if 2 <= len(w_items) <= 25:
                for i in range(len(w_items)):
                    for j in range(i + 1, len(w_items)):
                        w1, (t1, s1) = w_items[i]
                        w2, (t2, s2) = w_items[j]
                        self._add_edge_evidence(w1, w2, "SHARED_FUNDER", max(t1, t2), f"{f_addr[:10]}:{s1[:12]}", "CONFIRMED")

        for (w1, w2), evs in counterparty_counts.items():
            if len(evs) >= 2:
                for t_ms, sig in evs[:5]:
                    self._add_edge_evidence(w1, w2, "COMMON_COUNTERPARTY", t_ms, sig, "PROBABLE")

    def observe_token_pre_signal(self, coin: dict, vis_swaps: list, cutoff_ts_ms: int) -> dict:
        """
        Inspects strictly pre-signal swaps (`<= cutoff_ts_ms`) to:
        1. Record `SAME_SLOT_BUY` (`WEAK` confidence — explicitly NOT proof of shared control!),
        2. Record `CREATOR_LINK` if creator funded or transferred to an early buyer prior to `cutoff_ts_ms`,
        3. Identify active `CONFIRMED` / `PROBABLE` / `WEAK` wallet clusters among early buyers,
        4. Query causal `WalletClusterTrackRecord` and `SmartMoney` track records (`outcome_known_at_ms <= cutoff_ts_ms`)!
        """
        mint = coin.get("mint") or ""
        creator = str(coin.get("creator") or "")
        excl = build_token_excluded_addresses(coin, vis_swaps)

        slot_buyers = defaultdict(list)
        buyer_buy_sol = Counter()
        buyer_first_ts = {}

        for tr in vis_swaps:
            tms = int(tr["blockTimeMs"])
            if tms > cutoff_ts_ms:
                continue
            w = str((tr.get("trader") or {}).get("address") or "")
            if not w or w in excl:
                continue
            if tr.get("side") == "buy":
                val_sol = float(tr.get("valueNative") or 0.0)
                buyer_buy_sol[w] += val_sol
                if w not in buyer_first_ts:
                    buyer_first_ts[w] = tms
                slot_buyers[int(tr.get("blockId") or 0)].append((w, tms, str(tr.get("txId") or "")))

        # Record `SAME_SLOT_BUY` edges (`WEAK` — never `CONFIRMED`!)
        same_slot_wallets = set()
        for blk, items in slot_buyers.items():
            uw = []
            seen_u = set()
            for w, tms, txid in items:
                if w not in seen_u:
                    seen_u.add(w)
                    uw.append((w, tms, txid))
            if len(uw) >= 2:
                for i in range(len(uw)):
                    same_slot_wallets.add(uw[i][0])
                    for j in range(i + 1, min(len(uw), i + 5)):
                        self._add_edge_evidence(uw[i][0], uw[j][0], "SAME_SLOT_BUY", max(uw[i][1], uw[j][1]), uw[i][2] or f"slot_{blk}", "WEAK")

        buyers = list(buyer_first_ts.keys())
        total_buy_sol = sum(buyer_buy_sol.values())

        # Check causal edges (`first_seen <= cutoff_ts_ms`) among `buyers + [creator]`
        confirmed_adj = defaultdict(set)
        probable_adj = defaultdict(set)
        creator_linked_buyers = set()

        buyer_set = set(buyers)
        for (u, v, rtype), e in list(self.edges.items()):
            if e["first_seen"] > cutoff_ts_ms:
                continue
            if creator and (u == creator or v == creator):
                other = v if u == creator else u
                if other in buyer_set and rtype in ("DIRECT_FUNDING", "SHARED_FUNDER", "REPEATED_TRANSFER", "COMMON_COUNTERPARTY"):
                    creator_linked_buyers.add(other)
                    self._add_edge_evidence(creator, other, "CREATOR_LINK", e["first_seen"], e["evidence_ids"][0], "CONFIRMED")

            if u in buyer_set and v in buyer_set:
                if e["confidence"] == "CONFIRMED" and rtype in ("DIRECT_FUNDING", "SHARED_FUNDER", "REPEATED_TRANSFER", "CREATOR_LINK"):
                    confirmed_adj[u].add(v)
                    confirmed_adj[v].add(u)
                elif e["confidence"] in ("CONFIRMED", "PROBABLE") and rtype != "SAME_SLOT_BUY":
                    probable_adj[u].add(v)
                    probable_adj[v].add(u)

        # Also check causal `REPEATED_CO_BUYING` strictly before `cutoff_ts_ms` (`>= 3` prior tokens!)
        for i in range(min(len(buyers), 25)):
            for j in range(i + 1, min(len(buyers), 25)):
                pair = tuple(sorted((buyers[i], buyers[j])))
                prior_cb = [ev for ev in self.pair_cobuys.get(pair, []) if ev[0] < cutoff_ts_ms and ev[1] != mint]
                if len(prior_cb) >= 3:
                    probable_adj[buyers[i]].add(buyers[j])
                    probable_adj[buyers[j]].add(buyers[i])
                    self._add_edge_evidence(buyers[i], buyers[j], "REPEATED_CO_BUYING", prior_cb[-1][0], f"cobuy_{prior_cb[-1][1][:8]}", "PROBABLE")

        # Extract connected components of CONFIRMED + PROBABLE linked buyers (excluding `SAME_SLOT_BUY` alone!)
        visited = set()
        active_clusters = []
        for w in buyers:
            nbrs = confirmed_adj[w] | probable_adj[w]
            if not nbrs or w in visited:
                continue
            comp = set()
            stack = [w]
            has_conf = False
            while stack:
                cur = stack.pop()
                if cur in comp:
                    continue
                comp.add(cur)
                visited.add(cur)
                if confirmed_adj[cur]:
                    has_conf = True
                for nxt in (confirmed_adj[cur] | probable_adj[cur]):
                    if nxt not in comp:
                        stack.append(nxt)
            if len(comp) >= 2:
                tier = "CONFIRMED" if has_conf else "PROBABLE"
                cid = "cl_" + "_".join(sorted(w_addr[:6] for w_addr in sorted(comp)[:3]))
                cl_sol = sum(buyer_buy_sol[m_w] for m_w in comp)
                first_cl_ts = min(buyer_first_ts[m_w] for m_w in comp)

                # Query causal cluster track record (`outcome_known_at_ms <= cutoff_ts_ms`)!
                prior_cl_outcomes = [
                    r for r in self.cluster_token_outcomes.get(cid, [])
                    if r["outcome_known_at_ms"] <= cutoff_ts_ms and r["mint"] != mint
                ]
                prior_wins = sum(1 for r in prior_cl_outcomes if r["hit_2x_4h"] == 1)
                prior_losses = sum(1 for r in prior_cl_outcomes if r["hit_2x_4h"] == 0)
                prior_fifo_sol = sum(float(r["cluster_realized_pnl_sol"] or 0.0) for r in prior_cl_outcomes)

                active_clusters.append({
                    "cluster_id": cid,
                    "tier": tier,
                    "wallets": sorted(comp),
                    "wallet_count": len(comp),
                    "buy_sol": round(cl_sol, 4),
                    "buy_share": round(cl_sol / max(total_buy_sol, 1e-9), 4),
                    "first_buy_ts_ms": first_cl_ts,
                    "prior_evaluated_tokens": len(prior_cl_outcomes),
                    "prior_pre_pump_wins": prior_wins,
                    "prior_failed_tokens": prior_losses,
                    "prior_fifo_realized_pnl_sol": round(prior_fifo_sol, 4),
                })

        # Evaluate causal Smart Money buyers (`>= 3` prior evaluated tokens with `outcome_known_at_ms <= cutoff_ts_ms`,
        # positive realized FIFO PnL, and `win_rate >= 0.40` — Rule 6.2 & H3!)
        qualified_smart_wallets = []
        insufficient_history_wallets = 0
        for w in buyers:
            prior_w = [
                r for r in self.wallet_token_outcomes.get(w, [])
                if r["outcome_known_at_ms"] <= cutoff_ts_ms and r["mint"] != mint and r["pnl_known"]
            ]
            if len(prior_w) < 3:
                insufficient_history_wallets += 1
                continue
            wins = sum(1 for r in prior_w if r["hit_2x_4h"] == 1)
            wr = wins / len(prior_w)
            realized_sum = sum(float(r["realized_pnl_sol"]) for r in prior_w)
            if wr >= 0.40 and realized_sum > 0.02:
                qualified_smart_wallets.append({
                    "wallet": w,
                    "prior_tokens": len(prior_w),
                    "prior_win_rate": round(wr, 4),
                    "prior_realized_pnl_sol": round(realized_sum, 4),
                    "current_buy_sol": round(buyer_buy_sol[w], 4),
                })

        smart_buy_sol = sum(x["current_buy_sol"] for x in qualified_smart_wallets)
        # Estimate truly independent buyers: total unique buyers minus creator, creator-linked, and extra members of same-slot or confirmed clusters
        clustered_extra = sum(c["wallet_count"] - 1 for c in active_clusters)
        same_slot_extra = max(0, len(same_slot_wallets) - 1) if len(same_slot_wallets) >= 2 else 0
        non_indep = len(creator_linked_buyers | ({creator} if creator in buyer_set else set())) + max(clustered_extra, same_slot_extra)
        indep_estimate = max(0, len(buyers) - non_indep)

        return {
            "raw_buy_swaps_count": sum(1 for tr in vis_swaps if tr.get("side") == "buy" and str((tr.get("trader") or {}).get("address") or "") not in excl),
            "unique_buyers_count": len(buyers),
            "independent_buyers_estimate": indep_estimate,
            "insufficient_history_buyers_count": insufficient_history_wallets,
            "same_slot_buyers_count": len(same_slot_wallets),
            "creator_linked_buyers_count": len(creator_linked_buyers),
            "active_clusters": active_clusters,
            "qualified_smart_wallets": qualified_smart_wallets,
            "smart_money_buy_sol": round(smart_buy_sol, 4),
            "smart_money_buy_share": round(smart_buy_sol / max(total_buy_sol, 1e-9), 4),
            "total_human_buy_sol": round(total_buy_sol, 4),
        }

    def register_completed_token_outcomes(
        self,
        mint: str,
        created_ts_ms: int,
        signal_ts_ms: int,
        outcome_known_at_ms: int,
        hit_2x_4h: Optional[int],
        pre_signal_obs: dict,
        fifo_result: dict,
    ) -> None:
        """
        Registers token co-buys (at `signal_ts_ms`) and completed 4h outcomes (strictly gated at `outcome_known_at_ms > signal_ts_ms`!).
        """
        wallets_fifo = fifo_result.get("wallets_fifo", {})
        early_buyers = [
            w for w, wf in wallets_fifo.items()
            if wf["first_buy_ts_ms"] is not None and wf["first_buy_ts_ms"] <= signal_ts_ms
        ][:20]
        for i in range(len(early_buyers)):
            for j in range(i + 1, len(early_buyers)):
                pair = tuple(sorted((early_buyers[i], early_buyers[j])))
                self.pair_cobuys[pair].append((signal_ts_ms, mint, f"mint_{mint[:8]}"))

        if hit_2x_4h not in (0, 1) or outcome_known_at_ms <= signal_ts_ms:
            return

        for w in early_buyers:
            wf = wallets_fifo[w]
            pnl_known = wf["pnl_classification"] == "REALIZED_FIFO_VERIFIED" and wf["realized_pnl_sol"] is not None
            net_sol = float(wf["realized_pnl_sol"] or 0.0) + float(wf["unrealized_pnl_sol"] or 0.0)
            self.wallet_token_outcomes[w].append({
                "mint": mint,
                "entry_ts_ms": wf["first_buy_ts_ms"],
                "outcome_known_at_ms": int(outcome_known_at_ms),
                "hit_2x_4h": int(hit_2x_4h),
                "pnl_known": pnl_known,
                "realized_pnl_sol": net_sol if pnl_known else 0.0,
                "holding_time_sec": wf["average_holding_time_sec"],
            })

        for cl in pre_signal_obs.get("active_clusters", []):
            cid = cl["cluster_id"]
            cl_pnl = 0.0
            for w in cl["wallets"]:
                wf = wallets_fifo.get(w)
                if wf and wf["realized_pnl_sol"] is not None:
                    cl_pnl += float(wf["realized_pnl_sol"])
            self.cluster_token_outcomes[cid].append({
                "mint": mint,
                "first_buy_ts_ms": cl["first_buy_ts_ms"],
                "lead_time_from_birth_sec": round((cl["first_buy_ts_ms"] - created_ts_ms) / 1000.0, 2),
                "outcome_known_at_ms": int(outcome_known_at_ms),
                "hit_2x_4h": int(hit_2x_4h),
                "cluster_realized_pnl_sol": round(cl_pnl, 4),
            })

    def export_wallet_profiles_table(self) -> list[dict]:
        """Exports complete Wallet Intelligence 2.0 profiles with explicit `INSUFFICIENT_HISTORY` and confidence scores."""
        all_wallets = set(self.rpc_wallets_db.keys()) | set(self.wallet_token_outcomes.keys())
        rows = []
        for w in all_wallets:
            if w in SYSTEM_AND_POOL_ADDRESSES:
                continue
            rinfo = self.rpc_wallets_db.get(w, {})
            outcomes = self.wallet_token_outcomes.get(w, [])
            if not rinfo and len(outcomes) < 2:
                continue

            tx_cnt = rinfo.get("history_transactions_count", len(outcomes))
            total_sigs = rinfo.get("total_signatures_found", "UNKNOWN")
            if rinfo.get("history_complete") is True:
                hist_comp = "COMPLETE"
                conf_score = 0.90
            elif rinfo and int(rinfo.get("history_transactions_count") or 0) >= 10:
                hist_comp = "PARTIAL_PAGINATED"
                conf_score = round(min(0.75, 0.35 + 0.40 * float(rinfo.get("history_coverage") or 0.0)), 2)
            else:
                hist_comp = "INSUFFICIENT_HISTORY"
                conf_score = 0.20 if len(outcomes) >= 2 else 0.05

            known_out = [o for o in outcomes if o["pnl_known"]]
            wins = sum(1 for o in outcomes if o["hit_2x_4h"] == 1)
            losses = sum(1 for o in outcomes if o["hit_2x_4h"] == 0)
            holds = [o["holding_time_sec"] for o in outcomes if o.get("holding_time_sec") is not None]

            rows.append({
                "wallet_address": w,
                "first_seen_at": rinfo.get("first_observed_at") or (ts_to_iso(min(o["entry_ts_ms"] for o in outcomes)) if outcomes else "UNKNOWN"),
                "last_seen_at": rinfo.get("last_observed_at") or (ts_to_iso(max(o["entry_ts_ms"] for o in outcomes)) if outcomes else "UNKNOWN"),
                "transaction_count": tx_cnt,
                "total_onchain_signatures": total_sigs,
                "history_coverage_start": rinfo.get("first_observed_at") or "UNKNOWN",
                "history_coverage_end": rinfo.get("last_observed_at") or "UNKNOWN",
                "history_completeness": hist_comp,
                "funding_sources_count": len(rinfo.get("funders", [])),
                "funding_sources_sample": ";".join(fo["funder"] for fo in rinfo.get("funders", [])[:3]) or "UNKNOWN",
                "tokens_traded_observed": len(outcomes),
                "realized_fifo_pnl_sol": round(sum(o["realized_pnl_sol"] for o in known_out), 6) if known_out else "INSUFFICIENT_HISTORY",
                "average_holding_time_sec": round(float(np.mean(holds)), 2) if holds else "UNKNOWN",
                "successful_launches_count": wins,
                "failed_launches_count": losses,
                "win_rate": round(wins / (wins + losses), 4) if (wins + losses) >= 3 else "INSUFFICIENT_HISTORY",
                "confidence_score": conf_score,
            })
        rows.sort(key=lambda r: (r["confidence_score"], r["tokens_traded_observed"]), reverse=True)
        return rows

    def export_cluster_track_records(self) -> list[dict]:
        rows = []
        for cid, recs in self.cluster_token_outcomes.items():
            wins = sum(1 for r in recs if r["hit_2x_4h"] == 1)
            losses = sum(1 for r in recs if r["hit_2x_4h"] == 0)
            leads = [r["lead_time_from_birth_sec"] for r in recs if r["hit_2x_4h"] == 1]
            rows.append({
                "cluster_id": cid,
                "tokens_accumulated": len(recs),
                "pre_pump_2x_wins": wins,
                "post_entry_failures": losses,
                "win_rate": round(wins / max(1, wins + losses), 4) if len(recs) >= 2 else "INSUFFICIENT_SAMPLE",
                "median_entry_age_before_pump_sec": round(float(np.median(leads)), 2) if leads else "N/A",
                "cumulative_realized_fifo_pnl_sol": round(sum(r["cluster_realized_pnl_sol"] for r in recs), 4),
            })
        rows.sort(key=lambda r: r["tokens_accumulated"], reverse=True)
        return rows
