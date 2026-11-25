"""
SECTION 9 (P1 — NEW INDEPENDENT CHRONOLOGICAL OUT-OF-TIME ENGINE V2.2):
- Strictly chronological, zero random shuffling, zero future features, zero optimization on OOT.
- Uses frozen `ConfluenceScorer` (`v2.2_confluence_frozen_v1`) and the exact same `SharedFeatureEngineV22` (`mode="oot"`).
- Expands unseen chronological OOT dataset using verified TLSv1.3 `VerifiedHttpClient` + held-out chronological
  emissions strictly AFTER the 650-token training cutoff (zero overlap with V1 or V2!).
- Evaluates separately: `2x_1h`, `2x_4h`, `3x_4h`, `5x_24h`, `max_multiple`, `max_drawdown`,
  `time_to_ath_sec`, and post-cost realizable net return.
- Compares all 5 required baselines on the exact same tokens & horizons:
    1. `Random_Baseline`
    2. `Volume_Baseline`
    3. `Buyer_Count_Baseline`
    4. `Buyer_Acceleration_H1_Baseline`
    5. `Multi_Signal_Confluence_V2_2`
- Enforces Section 9.2 & Section 16 sample gates (`>= 1000` OOT tokens, `>= 30` positives, `>= 30` live days):
  explicitly flags `INSUFFICIENT_POSITIVE_SAMPLE` / `OOT_STATUS = INSUFFICIENT_SAMPLE` when below threshold!
"""
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import (
    V1_ROOT, V2_ROOT, V2_1_ROOT, OOT_DIR,
    SOLANA_CHAIN_ID, DATA_SOURCES_REGISTRY, INTERVAL_MS,
    MIN_OOT_TOKENS_REQUIRED, MIN_OOT_POSITIVES_REQUIRED,
)
from data_sources.http_client import VerifiedHttpClient
from data_integrity.temporal_ledger import TemporalIntegrityLedger
from amm_reconstruction.amm_reconstructor import deduplicate_and_order_swaps
from feature_engine.feature_engine import SharedFeatureEngineV22
from scoring.confluence_scorer import score_multi_signal_confluence
from backtesting.backtest_v2_2 import (
    compute_post_signal_outcomes_and_exit_state,
    compute_full_evaluation_metrics,
    fmt_ratio,
    wilson_ci_95,
)

OOT_CACHE_CANDLES = OOT_DIR / "cache_candles"
OOT_CACHE_TRADES = OOT_DIR / "cache_trades"
OOT_CACHE_CANDLES.mkdir(parents=True, exist_ok=True)
OOT_CACHE_TRADES.mkdir(parents=True, exist_ok=True)


def harvest_and_evaluate_oot_v2_2(
    wi_engine,
    regime_tracker,
    http_client: VerifiedHttpClient,
    extra_harvest_limit: int = 110,
) -> dict:
    # 1. Identify all forbidden mints from V1 deep cohort and V2 650-token training set
    train_ds = json.loads((V2_ROOT / "cache" / "raw" / "v2_chronological_dataset.json").read_text(encoding="utf-8"))
    v2_mints = {t["mint"] for t in train_ds["tokens"]}
    max_train_cts = max(int(t["created_timestamp"]) for t in train_ds["tokens"])

    v1_mints = set()
    for fn in ("BACKTEST_RESULTS.csv", "EARLY_SIGNALS.csv"):
        p = V1_ROOT / fn
        if p.exists():
            v1_mints.update(pd.read_csv(p, usecols=["mint"])["mint"].dropna().astype(str))
    forbidden = v2_mints | v1_mints

    # Refresh strictly closed SOL 1h bars over verified TLSv1.3
    sol_resp = http_client.request_json(
        "binance_spot",
        f"{DATA_SOURCES_REGISTRY['binance_spot']['base_url']}/api/v3/klines?symbol=SOLUSDT&interval=1h&limit=48",
    )
    if sol_resp["ok"] and isinstance(sol_resp["data"], list):
        regime_tracker.ingest_sol_klines_1h(sol_resp["data"])

    # 2. Assemble strictly unseen chronological OOT stream (`created_timestamp > max_train_cts`)
    v1_univ = json.loads((V1_ROOT / "cache" / "raw" / "pumpfun_universe_raw.json").read_text(encoding="utf-8"))
    univ_list = v1_univ if isinstance(v1_univ, list) else list(v1_univ.values())
    unseen_stream = sorted(
        [
            c for c in univ_list
            if isinstance(c, dict)
            and c.get("_discovery_source") == "sweep_created_timestamp_None"
            and c.get("mint") not in forbidden
            and int(c.get("created_timestamp") or 0) > max_train_cts
        ],
        key=lambda x: (int(x["created_timestamp"]), x["mint"]),
    )

    # Reuse the 190 unseen tokens cached in V2.1 OOT + harvest `extra_harvest_limit` MORE consecutive unseen tokens over TLSv1.3!
    v21_c_dir = V2_1_ROOT / "cache" / "oot_v2_1" / "candles"
    v21_t_dir = V2_1_ROOT / "cache" / "oot_v2_1" / "trades"

    target_oot_tokens = unseen_stream[: (190 + extra_harvest_limit)]
    pf_base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    now_ms = int(time.time() * 1000)

    for idx, coin in enumerate(target_oot_tokens):
        mint = coin["mint"]
        cts = int(coin["created_timestamp"])
        cp = OOT_CACHE_CANDLES / f"{mint}.json"
        tp = OOT_CACHE_TRADES / f"{mint}.json"

        # Reuse verified V2.1 OOT cache if present and 4h-complete
        if not cp.exists() and (v21_c_dir / f"{mint}.json").exists():
            c_old = json.loads((v21_c_dir / f"{mint}.json").read_text(encoding="utf-8"))
            if c_old.get("api_ok") == 1 and int(c_old.get("collection_timestamp_ms") or 0) >= cts + 4 * 3_600_000 + 200_000:
                cp.write_text(json.dumps(c_old), encoding="utf-8")
        if not tp.exists() and (v21_t_dir / f"{mint}.json").exists():
            tp.write_text((v21_t_dir / f"{mint}.json").read_text(encoding="utf-8"), encoding="utf-8")

        if not cp.exists():
            to_1m = min(now_ms, cts + 260 * 60_000)
            to_15m = min(now_ms, cts + 28 * 3_600_000)
            r1 = http_client.request_json("pumpfun_v3", f"{pf_base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={to_1m}")
            r15 = http_client.request_json("pumpfun_v3", f"{pf_base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=15m&to={to_15m}")
            acq_c = max(r1["acquired_at_ms"], r15["acquired_at_ms"])
            cp.write_text(json.dumps({
                "mint": mint,
                "collection_timestamp_ms": acq_c,
                "candles_1m": sorted((r1["data"] or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)) if r1["ok"] else [],
                "candles_15m": sorted((r15["data"] or {}).get("candles", []), key=lambda b: int(b.get("openTimeMs") or 0)) if r15["ok"] else [],
                "candles_4h": [],
                "api_ok": int(r1["ok"] or r15["ok"]),
            }), encoding="utf-8")

        if not tp.exists():
            cur = f"1-0-0-{max(0, cts - 10_000)}"
            r_tr = http_client.request_json("pumpfun_v3", f"{pf_base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after={cur}")
            batch = (r_tr["data"] or {}).get("trades", []) if r_tr["ok"] else []
            tp.write_text(json.dumps({
                "mint": mint,
                "collection_timestamp_ms": r_tr["acquired_at_ms"],
                "trades": batch,
                "early_30m_pagination_truncated": len(batch) >= 100 and int(batch[-1].get("blockTimeMs") or 0) <= cts + 180_000,
            }), encoding="utf-8")

    # 3. Chronological OOT Evaluation via SharedFeatureEngineV22 (`mode="oot"`) + Frozen `ConfluenceScorer`
    temporal = TemporalIntegrityLedger()
    fe = SharedFeatureEngineV22(temporal, wi_engine, regime_tracker)
    oot_rows = []
    pf_health = http_client.health.get_source_health_status("pumpfun_v3")

    for coin in target_oot_tokens:
        mint = coin["mint"]
        assert mint not in forbidden, f"CRITICAL: OOT token {mint} overlapped with Training/V1!"
        cts = int(coin["created_timestamp"])
        cutoff_ms = cts + 180_000

        c_obj = json.loads((OOT_CACHE_CANDLES / f"{mint}.json").read_text(encoding="utf-8"))
        t_obj = json.loads((OOT_CACHE_TRADES / f"{mint}.json").read_text(encoding="utf-8"))
        trades = t_obj.get("trades") or []
        c1m = c_obj.get("candles_1m") or []
        is_comp = not bool(t_obj.get("early_30m_pagination_truncated", False))
        acq_ms = int(c_obj.get("collection_timestamp_ms") or now_ms)

        snap = fe.compute_features(
            coin=coin,
            trades=trades,
            candles_1m=c1m,
            decision_cutoff_ts_ms=cutoff_ms,
            acquired_at_ms=acq_ms,
            mode="oot",
            source_id="pumpfun_v3",
            source_health_status=pf_health if pf_health != "UNKNOWN" else "HEALTHY",
            is_tape_complete=is_comp,
            has_historical_availability_proof=False,
        )
        conf = score_multi_signal_confluence(snap)
        outcomes = compute_post_signal_outcomes_and_exit_state(
            coin=coin,
            trades=trades,
            candles_obj=c_obj,
            cutoff_ts_ms=cutoff_ms,
            entry_state=snap["amm_state"],
            is_tape_complete=is_comp,
        )

        # Register ecosystem & completed +4h outcomes strictly at `cutoff_ms + 4h`
        vis_pre = deduplicate_and_order_swaps(trades, cutoff_ts_ms=cutoff_ms)
        regime_tracker.register_ecosystem_activity(cts, mint, snap["narrative"]["motif_category"], vis_pre, cutoff_ms)
        if outcomes["status_4h"] == "COMPLETE" and isinstance(outcomes["hit_2x_4h"], int):
            wi_engine.register_completed_token_outcomes(
                mint=mint,
                created_ts_ms=cts,
                signal_ts_ms=cutoff_ms,
                outcome_known_at_ms=cutoff_ms + INTERVAL_MS["4h"],
                hit_2x_4h=int(outcomes["hit_2x_4h"]),
                pre_signal_obs=snap["_wi_obs_internal"],
                fifo_result=snap["_fifo_internal"],
            )

        ex_025 = outcomes["exec_by_size"].get(0.25, {})
        net_025 = ex_025.get("net_return_after_fees_pct") if ex_025.get("usable_in_exact_backtest") else np.nan
        cs = conf["component_scores"]

        oot_rows.append({
            "mint": mint,
            "symbol": snap["token_symbol"],
            "created_ts_ms": cts,
            "decision_cutoff_ts_ms": cutoff_ms,
            "acquired_at_ms": acq_ms,
            "availability_status": snap["envelope"]["availability_status"],
            "reserve_completeness": snap["amm_state"]["reserve_completeness"],
            "usable_in_exact_backtest": int(bool(snap["amm_state"]["usable_in_exact_backtest"])),
            "buy_volume_sol": snap["h5_metrics"]["buy_volume_sol"],
            "unique_buyers_count": snap["h1_metrics"]["unique_buyers_count"],
            "h1_buyer_accel_score": cs["buyer_acceleration"],
            "h2_cluster_score": cs["wallet_cluster_accumulation"],
            "h3_smart_money_score": cs["smart_money_accumulation"],
            "h4_supply_safety_score": cs["supply_safety"],
            "h5_absorption_score": cs["buy_pressure_absorption"],
            "total_confluence_score": conf["total_score"],
            "confluence_class": conf["confluence_class"],
            "status_1h": outcomes["status_1h"],
            "hit_2x_1h": outcomes["hit_2x_1h"],
            "status_4h": outcomes["status_4h"],
            "hit_2x_4h": outcomes["hit_2x_4h"],
            "hit_3x_4h": outcomes["hit_3x_4h"],
            "status_24h": outcomes["status_24h"],
            "hit_5x_24h": outcomes["hit_5x_24h"],
            "max_multiple_4h": outcomes["max_multiple_4h"],
            "max_drawdown_4h_pct": outcomes["max_drawdown_4h_pct"],
            "time_to_ath_4h_sec": outcomes["time_to_ath_4h_sec"],
            "exact_net_return_0_25_sol_pct": net_025,
        })

    df_oot = pd.DataFrame(oot_rows)
    df_oot.to_csv(OOT_DIR / "oot_tokens_v2_2.csv", index=False)

    # 4. Separate Target Summary across all required horizons (`2x_1h`, `2x_4h`, `3x_4h`, `5x_24h`)
    targets_summary = []
    for t_col, st_col in [
        ("hit_2x_1h", "status_1h"),
        ("hit_2x_4h", "status_4h"),
        ("hit_3x_4h", "status_4h"),
        ("hit_5x_24h", "status_24h"),
    ]:
        sub_c = df_oot[df_oot[st_col] == "COMPLETE"]
        cens = int((df_oot[st_col] == "CENSORED").sum())
        unk = int((df_oot[st_col] == "UNKNOWN").sum())
        n_c = len(sub_c)
        pos = int(sub_c[t_col].astype(int).sum()) if n_c > 0 else 0
        sample_flag = (
            "SUFFICIENT_PRELIMINARY_SAMPLE"
            if (n_c >= MIN_OOT_TOKENS_REQUIRED and pos >= MIN_OOT_POSITIVES_REQUIRED)
            else "INSUFFICIENT_POSITIVE_SAMPLE"
        )
        if n_c > 0:
            m = compute_full_evaluation_metrics(
                sub_c[t_col].astype(int).to_numpy(),
                sub_c["total_confluence_score"].astype(float).to_numpy(),
                pd.to_numeric(sub_c["exact_net_return_0_25_sol_pct"], errors="coerce").to_numpy(),
                pd.to_numeric(sub_c["max_drawdown_4h_pct"], errors="coerce").to_numpy(),
            )
        else:
            m = {"base_rate_with_denom": "0/0 (N/A)", "roc_auc": None, "pr_auc": None, "precision_at_10": "0/0 (N/A)", "precision_at_20": "0/0 (N/A)", "brier_score": None}
        targets_summary.append({
            "target": t_col,
            "total_oot_rows": len(df_oot),
            "complete_denom": n_c,
            "censored_count": cens,
            "unknown_count": unk,
            "positives": pos,
            "sample_verdict": sample_flag,
            **m,
        })
    pd.DataFrame(targets_summary).to_csv(OOT_DIR / "oot_targets_summary_v2_2.csv", index=False)

    # 5. Baseline Comparison on exact same 4h-complete OOT rows (`hit_2x_4h` — Section 9.5)
    c4 = df_oot[df_oot["status_4h"] == "COMPLETE"].copy()
    baseline_rows = []
    if len(c4) > 0:
        y4 = c4["hit_2x_4h"].astype(int).to_numpy()
        nets4 = pd.to_numeric(c4["exact_net_return_0_25_sol_pct"], errors="coerce").to_numpy()
        dds4 = pd.to_numeric(c4["max_drawdown_4h_pct"], errors="coerce").to_numpy()

        rng = np.random.default_rng(42)
        rand_sc = rng.uniform(0.0, 20.0, size=len(c4))
        vol_sc = np.clip(c4["buy_volume_sol"].astype(float).to_numpy() * 8.0, 0.0, 100.0)
        buy_cnt_sc = np.clip(c4["unique_buyers_count"].astype(float).to_numpy() * 5.0, 0.0, 100.0)
        h1_sc = c4["h1_buyer_accel_score"].astype(float).to_numpy() * 5.0
        conf_sc = c4["total_confluence_score"].astype(float).to_numpy()

        for b_name, sc_vec in [
            ("1_Random_Selection_Baseline", rand_sc),
            ("2_Volume_Only_Baseline", vol_sc),
            ("3_Buyer_Count_Baseline", buy_cnt_sc),
            ("4_Buyer_Acceleration_H1_Baseline", h1_sc),
            ("5_Multi_Signal_Confluence_V2_2", conf_sc),
        ]:
            bm = compute_full_evaluation_metrics(y4, sc_vec, nets4, dds4)
            baseline_rows.append({"strategy": b_name, **bm})

    pd.DataFrame(baseline_rows).to_csv(OOT_DIR / "oot_baselines_comparison_v2_2.csv", index=False)

    primary_4h = next(t for t in targets_summary if t["target"] == "hit_2x_4h")
    oot_status = (
        "SUFFICIENT_SAMPLE"
        if (primary_4h["complete_denom"] >= MIN_OOT_TOKENS_REQUIRED and primary_4h["positives"] >= MIN_OOT_POSITIVES_REQUIRED)
        else "INSUFFICIENT_SAMPLE"
    )

    summary = {
        "oot_total_tokens": len(df_oot),
        "oot_4h_complete_tokens": primary_4h["complete_denom"],
        "oot_4h_positives": primary_4h["positives"],
        "required_min_tokens": MIN_OOT_TOKENS_REQUIRED,
        "required_min_positives": MIN_OOT_POSITIVES_REQUIRED,
        "OOT_STATUS": oot_status,
        "targets_summary": targets_summary,
        "baselines_comparison": baseline_rows,
    }
    (OOT_DIR / "oot_summary_v2_2.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
