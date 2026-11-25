"""
SECTION 8 (MULTI-SIGNAL CONFLUENCE SCORING ENGINE — FROZEN A-PRIORI RULES):
Combines H1–H5 (`0–20` each -> `0–100` max) WITHOUT tuning on OOT or Paper Trading!
Outputs:
  - `component_scores`
  - `total_score`
  - `triggered_hypotheses`
  - `missing_hypotheses`
  - `data_quality_score`
  - `execution_confidence`
  - `risk_flags`
  - `confluence_class` in `{"INSUFFICIENT_DATA", "LOW_CONFLUENCE", "MEDIUM_CONFLUENCE", "HIGH_CONFLUENCE", "HIGH_RISK"}`
Never emits `HIGH_CONFLUENCE` when essential data is incomplete!
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hypothesis_engine.hypotheses_v2_2 import (
    evaluate_h1_buyer_acceleration,
    evaluate_h2_wallet_group_accumulation,
    evaluate_h3_smart_money_accumulation,
    evaluate_h4_supply_safety,
    evaluate_h5_buy_pressure_absorption,
)

FROZEN_SCORER_VERSION = "v2.2_confluence_frozen_v1"


def score_multi_signal_confluence(snapshot: dict) -> dict:
    r1 = evaluate_h1_buyer_acceleration(snapshot)
    r2 = evaluate_h2_wallet_group_accumulation(snapshot)
    r3 = evaluate_h3_smart_money_accumulation(snapshot)
    r4 = evaluate_h4_supply_safety(snapshot)
    r5 = evaluate_h5_buy_pressure_absorption(snapshot)

    evals = [r1, r2, r3, r4, r5]
    comp_scores = {
        "buyer_acceleration": r1["score_0_20"],
        "wallet_cluster_accumulation": r2["score_0_20"],
        "smart_money_accumulation": r3["score_0_20"],
        "supply_safety": r4["score_0_20"],
        "buy_pressure_absorption": r5["score_0_20"],
    }
    total_score = round(sum(comp_scores.values()), 2)

    triggered = [r["hypothesis"] for r in evals if r["triggered"]]
    missing = [r["hypothesis"] for r in evals if r["status"].startswith("MISSING") or r["status"].startswith("INSUFFICIENT")]

    # Compute Data Quality Score (0–100) and Risk Flags
    env = snapshot["envelope"]
    amm = snapshot["amm_state"]
    h4 = snapshot["h4_metrics"]
    reg = snapshot["market_regime"]

    dq = 100.0
    essential_incomplete = False
    risk_flags = []

    if env["temporal_status"] != "VALID":
        dq = 0.0
        essential_incomplete = True
        risk_flags.append(f"TEMPORAL_INVALID:{env['temporal_status']}")

    if snapshot["source_health_status"] != "HEALTHY":
        dq -= 25.0
        essential_incomplete = True
        risk_flags.append(f"SOURCE_NOT_HEALTHY:{snapshot['source_health_status']}")

    if not amm.get("usable_in_exact_backtest"):
        dq -= 30.0
        essential_incomplete = True
        risk_flags.append(f"RESERVE_INCOMPLETE:{amm.get('reserve_completeness')}")

    if h4["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION":
        dq -= 30.0
        essential_incomplete = True
        risk_flags.append("INVALID_SUPPLY_RECONSTRUCTION")

    if reg.get("status") != "OK":
        dq -= 15.0
        essential_incomplete = True
        risk_flags.append("MARKET_REGIME_UNKNOWN")

    if "H2_REPEATED_WALLET_GROUPS" in missing:
        dq -= 5.0
    if "H3_SMART_MONEY_ACCUMULATION" in missing:
        dq -= 5.0

    dq = round(max(0.0, dq), 1)

    # Microstructure / Insider High-Risk Flags
    if float(h4.get("creator_sold_sol") or 0.0) >= 0.5:
        risk_flags.append("CREATOR_EARLY_SELL")
    if float(h4.get("top5_pct") or 0.0) > 35.0:
        risk_flags.append("EXTREME_TOP5_CONCENTRATION")
    if int(h4.get("creator_linked_buyers_count") or 0) >= 2:
        risk_flags.append("CREATOR_LINKED_SNIPERS")
    if env.get("discovery_status") == "LATE_DISCOVERY":
        risk_flags.append("LATE_DISCOVERY")

    has_severe_risk = any(
        rf in risk_flags
        for rf in ("CREATOR_EARLY_SELL", "EXTREME_TOP5_CONCENTRATION", "CREATOR_LINKED_SNIPERS")
    )

    # Assign mandatory Confluence Class (Rule 8: NEVER emit HIGH_CONFLUENCE if essential data is incomplete!)
    if env["temporal_status"] != "VALID" or dq < 50.0 or h4["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION":
        c_class = "INSUFFICIENT_DATA"
    elif has_severe_risk:
        c_class = "HIGH_RISK"
    elif total_score >= 55.0 and len(triggered) >= 3 and not essential_incomplete:
        c_class = "HIGH_CONFLUENCE"
    elif total_score >= 36.0 and len(triggered) >= 2:
        c_class = "MEDIUM_CONFLUENCE"
    else:
        c_class = "LOW_CONFLUENCE"

    return {
        "scorer_version": FROZEN_SCORER_VERSION,
        "component_scores": comp_scores,
        "hypothesis_details": {r["hypothesis"]: r for r in evals},
        "total_score": total_score,
        "triggered_hypotheses": triggered,
        "triggered_count": len(triggered),
        "missing_hypotheses": missing,
        "data_quality_score": dq,
        "essential_data_complete": not essential_incomplete,
        "execution_confidence": amm.get("execution_confidence", "NONE"),
        "source_health_all_healthy": snapshot["source_health_status"] == "HEALTHY",
        "risk_flags": risk_flags,
        "confluence_class": c_class,
    }
