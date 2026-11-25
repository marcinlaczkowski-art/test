"""
SECTIONS 7 & 8 (FIVE RESEARCH HYPOTHESES H1–H5 & MULTI-SIGNAL CONFLUENCE SCORER):
Evaluates each hypothesis independently (`0–20` points + explicit trigger / missing status),
then computes the combined 0–100 Confluence Score and assigns one of the 5 mandatory classes:
  - `INSUFFICIENT_DATA`
  - `LOW_CONFLUENCE`
  - `MEDIUM_CONFLUENCE`
  - `HIGH_CONFLUENCE`
  - `HIGH_RISK`
Strictly forbids `HIGH_CONFLUENCE` whenever critical data is incomplete or degraded!
Parameters are fixed a-priori and frozen BEFORE Out-of-Time and Paper Trading!
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def evaluate_h1_buyer_acceleration(snapshot: dict) -> dict:
    """H1: Acceleration of new, independent buyers across 15s/30s/60s windows prior to price breakout."""
    h1 = snapshot["h1_metrics"]
    indep = h1["independent_buyers_estimate"]
    b30 = h1["new_buyers_30s"]
    b60 = h1["new_buyers_60s"]
    accel = h1["buyer_acceleration_ratio"]
    ft_share = h1["first_time_buyer_share"]
    hhi = h1["purchase_hhi_concentration"]

    if snapshot["amm_state"]["reserve_completeness"] == "RESERVE_RECONSTRUCTION_INCOMPLETE" and h1["raw_buy_count"] == 0:
        return {"hypothesis": "H1_BUYER_ACCELERATION", "status": "MISSING", "score_0_20": 0.0, "triggered": False, "reason": "No swap tape"}

    pts = 0.0
    if indep >= 4:
        pts += min(8.0, (indep - 2) * 1.6)
    if accel >= 1.25 and b30 >= 2:
        pts += min(6.0, (accel - 1.0) * 5.0)
    if ft_share >= 0.65 and indep >= 3:
        pts += 3.0
    if hhi <= 0.35 and b60 >= 3:
        pts += 3.0

    score = round(min(20.0, max(0.0, pts)), 2)
    trig = bool(score >= 11.0 and indep >= 4 and accel >= 1.20)
    return {
        "hypothesis": "H1_BUYER_ACCELERATION",
        "status": "EVALUATED",
        "score_0_20": score,
        "triggered": trig,
        "reason": f"indep={indep}, b30={b30}, accel={accel:.2f}, hhi={hhi:.2f}",
    }


def evaluate_h2_wallet_group_accumulation(snapshot: dict) -> dict:
    """H2: Accumulation by wallet groups with documented profitable pre-pump track record prior to signal."""
    h2 = snapshot["h2_metrics"]
    clusters = h2["active_clusters"]
    if not clusters:
        return {
            "hypothesis": "H2_REPEATED_WALLET_GROUPS",
            "status": "NO_ACTIVE_CLUSTER",
            "score_0_20": 0.0,
            "triggered": False,
            "reason": "0 confirmed/probable multi-wallet clusters in pre-signal buyers",
        }

    eval_clusters = [c for c in clusters if c["prior_evaluated_tokens"] >= 2]
    if not eval_clusters:
        return {
            "hypothesis": "H2_REPEATED_WALLET_GROUPS",
            "status": "INSUFFICIENT_CLUSTER_HISTORY",
            "score_0_20": 0.0,
            "triggered": False,
            "reason": "Active cluster detected, but <2 prior evaluated tokens before signal",
        }

    pts = 0.0
    for c in eval_clusters:
        wr = c["prior_pre_pump_wins"] / max(1, c["prior_evaluated_tokens"])
        if wr >= 0.35 and c["prior_fifo_realized_pnl_sol"] > 0:
            tier_w = 1.0 if c["tier"] == "CONFIRMED" else 0.75
            pts += tier_w * min(20.0, 8.0 + 4.0 * c["prior_pre_pump_wins"] + min(8.0, c["buy_sol"] * 3.0))
        elif c["prior_failed_tokens"] >= 3 and c["prior_pre_pump_wins"] == 0:
            pts -= 6.0

    score = round(min(20.0, max(0.0, pts)), 2)
    trig = bool(score >= 10.0)
    return {
        "hypothesis": "H2_REPEATED_WALLET_GROUPS",
        "status": "EVALUATED",
        "score_0_20": score,
        "triggered": trig,
        "reason": f"eval_clusters={len(eval_clusters)}, prior_pnl={h2['cluster_prior_fifo_pnl_sol']} SOL",
    }


def evaluate_h3_smart_money_accumulation(snapshot: dict) -> dict:
    """H3: Accumulation by individual wallets with >=3 prior tokens, >=40% win rate, and >0 realized FIFO SOL."""
    h3 = snapshot["h3_metrics"]
    sm_cnt = h3["qualified_smart_wallets_count"]
    sm_sol = h3["smart_money_buy_sol"]
    sm_pnl = h3["smart_money_prior_realized_pnl_sol"]

    if sm_cnt == 0:
        st = "INSUFFICIENT_WALLET_HISTORY" if h3["insufficient_history_buyers_count"] > 0 else "EVALUATED_NONE"
        return {
            "hypothesis": "H3_SMART_MONEY_ACCUMULATION",
            "status": st,
            "score_0_20": 0.0,
            "triggered": False,
            "reason": f"qualified_smart_wallets=0 (insufficient_hist_buyers={h3['insufficient_history_buyers_count']})",
        }

    pts = min(10.0, sm_cnt * 5.0) + min(6.0, sm_sol * 3.0) + min(4.0, sm_pnl * 1.5)
    score = round(min(20.0, max(0.0, pts)), 2)
    trig = bool(sm_cnt >= 1 and sm_sol >= 0.20 and score >= 9.0)
    return {
        "hypothesis": "H3_SMART_MONEY_ACCUMULATION",
        "status": "EVALUATED",
        "score_0_20": score,
        "triggered": trig,
        "reason": f"smart_wallets={sm_cnt}, sm_buy={sm_sol:.2f} SOL, prior_fifo={sm_pnl:.2f} SOL",
    }


def evaluate_h4_supply_safety(snapshot: dict) -> dict:
    """H4: Low human supply concentration and absence of creator/linked-cluster overhang."""
    h4 = snapshot["h4_metrics"]
    if h4["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION" or h4["top5_pct"] is None:
        return {
            "hypothesis": "H4_SUPPLY_SAFETY",
            "status": "MISSING_INVALID_SUPPLY",
            "score_0_20": 0.0,
            "triggered": False,
            "reason": f"supply_status={h4['supply_status']}",
        }

    top1 = float(h4["top1_pct"])
    top5 = float(h4["top5_pct"])
    cr_sh = float(h4["creator_share_pct"] or 0.0)
    cr_sold = float(h4["creator_sold_sol"] or 0.0)
    cr_link = int(h4["creator_linked_buyers_count"] or 0)
    cl_sup = float(h4["cluster_supply_pct"] or 0.0)

    pts = 20.0
    if top1 > 6.0:
        pts -= min(10.0, (top1 - 6.0) * 0.7)
    if top5 > 18.0:
        pts -= min(8.0, (top5 - 18.0) * 0.4)
    if cr_sh > 5.0:
        pts -= min(6.0, (cr_sh - 5.0) * 0.6)
    if cr_sold >= 0.5:
        pts -= 8.0
    if cr_link >= 2:
        pts -= 6.0
    if cl_sup > 15.0:
        pts -= 5.0

    # Note: zero-trade dead token has top5 == 0%, which is NOT healthy distributed demand — require >=2 holders!
    if snapshot["h1_metrics"]["unique_buyers_count"] < 2:
        pts = min(pts, 8.0)

    score = round(min(20.0, max(0.0, pts)), 2)
    trig = bool(score >= 13.0 and snapshot["h1_metrics"]["unique_buyers_count"] >= 3 and cr_sold < 0.5)
    return {
        "hypothesis": "H4_SUPPLY_SAFETY",
        "status": "EVALUATED",
        "score_0_20": score,
        "triggered": trig,
        "reason": f"top1={top1:.1f}%, top5={top5:.1f}%, cr_sold={cr_sold:.2f} SOL, cr_links={cr_link}",
    }


def evaluate_h5_buy_pressure_absorption(snapshot: dict) -> dict:
    """
    H5: Rising independent buyer inflow & buy volume with controlled price advance (supply absorbed without spike/dump).
    """
    h5 = snapshot["h5_metrics"]
    h1 = snapshot["h1_metrics"]
    pmult = h5["price_mult_from_birth"]
    b_sol = h5["buy_volume_sol"]
    s_sol = h5["sell_volume_sol"]
    bs_rat = h5["buy_sell_ratio"]
    max_s = h5["max_single_seller_sol"]
    indep = h1["independent_buyers_estimate"]

    if pmult is None or not snapshot["amm_state"]["usable_in_exact_backtest"]:
        return {
            "hypothesis": "H5_BUY_PRESSURE_ABSORPTION",
            "status": "MISSING_RESERVE_STATE",
            "score_0_20": 0.0,
            "triggered": False,
            "reason": "Exact price/reserve state unavailable",
        }

    pts = 0.0
    # Rising independent buyers + real buy volume
    if indep >= 3 and b_sol >= 0.6:
        pts += min(8.0, b_sol * 2.0)
    # Buy/sell absorption (>1.3x inflow over outflow while absorbing supply)
    if bs_rat >= 1.35 and s_sol > 0:
        pts += min(6.0, (bs_rat - 1.0) * 3.0)
    elif bs_rat >= 2.0 and b_sol >= 0.8:
        pts += 5.0

    # Price has NOT already blown off (`1.02x <= pmult <= 2.15x` means early absorption BEFORE parabolic move!)
    if 1.02 <= pmult <= 2.15 and indep >= 3:
        pts += 6.0
    elif pmult > 3.5:
        # Already extended — penalize chasing!
        pts -= 6.0

    # Penalize single-wallet heavy dump into buyers
    if b_sol > 0 and max_s >= 0.50 * b_sol and max_s >= 0.5:
        pts -= 5.0

    score = round(min(20.0, max(0.0, pts)), 2)
    trig = bool(score >= 11.0 and 1.01 <= pmult <= 2.30 and indep >= 3)
    return {
        "hypothesis": "H5_BUY_PRESSURE_ABSORPTION",
        "status": "EVALUATED",
        "score_0_20": score,
        "triggered": trig,
        "reason": f"buy={b_sol:.2f} SOL, sell={s_sol:.2f} SOL, bs={bs_rat:.2f}, pmult={pmult:.2f}x",
    }
