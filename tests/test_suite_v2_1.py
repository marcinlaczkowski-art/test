"""
AUTOMATED 12-CATEGORY VERIFICATION & PARITY SUITE (`tests/test_suite_v2_1.py` — Sections 2, 3, 11):
Executes all 12 mandatory methodological, anti-leakage, parity, supply, FIFO, execution, split-disjointness,
and censorship checks on both adversarial synthetic cases AND real generated V2.1 artifacts on disk.
Saves full machine-verifiable results to `logs/test_suite_v2_1_results.json`.
"""
import copy
import json
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

SRC_PATH = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_PATH))

from config_v2_1 import (
    V1_DIR, V2_DIR, V2_1_DIR, CHECKPOINTS_DIR, LOGS_DIR,
    INTERVAL_MS, PUMPFUN_INIT_K,
)
from state_trackers_v2_1 import UnifiedStateBundle
from feature_engine import (
    UnifiedFeatureEngine,
    FeatureLeakageError,
    ALL_MODEL_FEATURES_V2_1,
    validate_snapshot_no_leakage,
)
from wallet_supply_fifo_v2_1 import reconstruct_supply_and_fifo_v2_1
from execution_and_backtest_v2_1 import (
    compute_multi_horizon_labels_and_path,
    simulate_amm_position_execution,
)


def make_base_fixture():
    cts = 1_764_000_000_000  # Exact hour boundary (e.g. 12:00:00.000 UTC)
    coin = {
        "mint": "TestMint11111111111111111111111111111111pump",
        "symbol": "TSTPMP",
        "name": "Test Pump Token",
        "description": "unit test token",
        "creator": "Creator111111111111111111111111111111111111",
        "created_timestamp": cts,
        "total_supply": 1_000_000_000_000_000,
        "base_decimals": 6,
        "bonding_curve": "Curve11111111111111111111111111111111111111",
        "twitter": "https://x.com/testpump/status/12345",
    }
    trades = [
        {
            "txId": "tx_buy_1", "legIndex": 0, "eventIndex": 0,
            "blockTimeMs": cts + 10_000, "blockId": 100, "txIndex": 1,
            "side": "buy", "trader": {"address": "BuyerA1111111111111111111111111111111111111"},
            "pool": {"address": "Curve11111111111111111111111111111111111111"},
            "venue": "pump", "valueUsd": 70.0, "valueNative": 1.0,
            "priceUsd": 0.0000021, "priceQuote": 3.0e-8, "quotePriceUsd": 70.0,
            "baseAmount": {"raw": str(33_000_000 * 10**6), "decimals": 6},
        },
        {
            "txId": "tx_buy_2", "legIndex": 0, "eventIndex": 0,
            "blockTimeMs": cts + 110_000, "blockId": 350, "txIndex": 4,
            "side": "buy", "trader": {"address": "BuyerB1111111111111111111111111111111111111"},
            "pool": {"address": "Curve11111111111111111111111111111111111111"},
            "venue": "pump", "valueUsd": 140.0, "valueNative": 2.0,
            "priceUsd": 0.0000023, "priceQuote": 3.28e-8, "quotePriceUsd": 70.0,
            "baseAmount": {"raw": str(61_000_000 * 10**6), "decimals": 6},
        },
    ]
    candles_1m = [
        {"openTimeMs": cts, "open": 0.0000020, "high": 0.0000022, "low": 0.0000020, "close": 0.0000021, "volume": 70.0},
        {"openTimeMs": cts + 60_000, "open": 0.0000021, "high": 0.0000024, "low": 0.0000021, "close": 0.0000023, "volume": 140.0},
    ]
    state = UnifiedStateBundle()
    # Ingest 26 closed hourly SOL bars BEFORE cts (`cts - 26h` .. `cts - 1h`, closing up to `cts`), plus an UNCLOSED bar `[cts, cts+1h)` with fake $999 close!
    klines = []
    for h in range(26, 0, -1):
        ot = cts - h * 3_600_000
        klines.append([ot, "68.0", "71.0", "67.5", "70.0", "1000", ot + 3_599_999, "70000"])
    # Current unclosed bar `[cts, cts + 3_600_000)` that spikes to $999.0 at end of hour!
    klines.append([cts, "70.0", "999.0", "69.0", "999.0", "50000", cts + 3_599_999, "9999999"])
    state.market.ingest_binance_klines(klines, interval="1h")
    return cts, coin, trades, candles_1m, state


def test_01_no_unclosed_candles() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    engine = UnifiedFeatureEngine()
    sig_ts = cts + 150_000  # 2m30s: candle at `cts + 120_000` (closes at `cts + 180_000`) is UNCLOSED!

    snap_clean = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)
    candles_with_unclosed = candles_1m + [
        {"openTimeMs": cts + 120_000, "open": 0.0000023, "high": 0.99, "low": 0.0000023, "close": 0.88, "volume": 999999.0}
    ]
    snap_adv = engine.compute_snapshot(coin, trades, candles_with_unclosed, sig_ts, state)
    assert snap_clean["entry_price_usd"] == snap_adv["entry_price_usd"], "Unclosed 1m candle leaked into entry_price_usd!"
    assert snap_clean["model_vector"] == snap_adv["model_vector"], "Unclosed 1m candle leaked into model_vector!"

    # Also verify `validate_snapshot_no_leakage` blocks any forged feature with future timestamp
    bad_snap = copy.deepcopy(snap_clean)
    bad_snap["features"]["vol_to_mcap_ratio"]["feature_available_at_ms"] = sig_ts + 1
    blocked = False
    try:
        validate_snapshot_no_leakage(bad_snap)
    except FeatureLeakageError:
        blocked = True
    assert blocked, "FeatureLeakageError failed to block future feature_available_at_ms!"
    return {"passed": True, "details": "Unclosed 1m candle [120s..180s) ignored at T=150s; FeatureLeakageError blocked +1ms violation."}


def test_02_no_future_volume() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    engine = UnifiedFeatureEngine()
    sig_ts = cts + 180_000
    snap_clean = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)

    future_trades = trades + [
        {
            "txId": "tx_future_whale", "legIndex": 0, "eventIndex": 0,
            "blockTimeMs": sig_ts + 1, "blockId": 500, "txIndex": 0,
            "side": "buy", "trader": {"address": "FutureWhale11111111111111111111111111111111"},
            "pool": {"address": "Curve11111111111111111111111111111111111111"},
            "venue": "pump", "valueUsd": 500_000.0, "valueNative": 7000.0,
            "priceUsd": 0.05, "priceQuote": 7.0e-4, "quotePriceUsd": 70.0,
            "baseAmount": {"raw": str(200_000_000 * 10**6), "decimals": 6},
        }
    ]
    snap_fut = engine.compute_snapshot(coin, future_trades, candles_1m, sig_ts, state)
    assert snap_clean["buy_volume_usd"] == snap_fut["buy_volume_usd"]
    assert snap_clean["model_vector"] == snap_fut["model_vector"]
    return {"passed": True, "details": f"Injected $500k trade at signal_ts+1ms completely ignored (buy_vol={snap_fut['buy_volume_usd']})."}


def test_03_no_future_sol_mid_hour() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    # Test mid-hour timestamps: +1s (12:00:01), +15m (12:15:00), +30m (12:30:00), +59m59s (12:59:59)
    # Remember bar `[cts, cts+3600s)` has fake close `$999.0`! None of these mid-hour queries may see `$999.0`!
    offsets_sec = [1, 900, 1800, 3599]
    for off_s in offsets_sec:
        q = state.market.query_sol_at(cts + off_s * 1000, onchain_spot_tick=None)
        assert q["sol_price_usd"] == 70.0, f"Mid-hour SOL leak at +{off_s}s: got {q['sol_price_usd']} instead of 70.0!"
        assert q["last_closed_bar_close_ts_ms"] == cts
        assert q["sol_ret_available_at_ms"] <= cts + off_s * 1000

    # Only at exact hour close `cts + 3_600_000` (13:00:00.000) does the `[12:00, 13:00)` bar close!
    q_after_close = state.market.query_sol_at(cts + 3_600_000, onchain_spot_tick=None)
    assert q_after_close["sol_price_usd"] == 999.0
    return {"passed": True, "details": "Verified 0% SOL kline close leak at +1s, +15m, +30m, +59m59s; bar unlocked strictly at +3600s."}


def test_04_no_future_creator_outcomes() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    cr = coin["creator"]
    # Prior coin created 20m before `cts`, whose 4h outcome only finalizes at `cts - 20m + 4h` (> `cts + 3m`)!
    prior_cts = cts - 20 * 60_000
    state.creators.register_event(
        creator=cr,
        mint="PriorMint1111111111111111111111111111111pump",
        created_ts_ms=prior_cts,
        label_available_at_ms=prior_cts + 4 * 3_600_000,
        is_win=1,
        outcome_status="complete",
    )
    engine = UnifiedFeatureEngine()
    sig_ts = cts + 180_000
    snap = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)
    assert snap["features"]["creator_win_rate_num"]["value"] == "unknown", "Future creator win leaked before 4h horizon finished!"
    assert snap["model_vector"]["creator_history_known_flag"] == 0.0
    assert snap["features"]["creator_prior_launches_log"]["value"] == 1  # Launch existence at -20m IS known, outcome is NOT!

    # Query after 4h outcome is known (`prior_cts + 4h + 1s`)
    q_later = state.creators.query_at(cr, coin["mint"], prior_cts + 4 * 3_600_000 + 1000)
    assert q_later["status"] == "ok" and q_later["win_rate"] == 1.0
    return {"passed": True, "details": "Creator launch at -20m showed win_rate='unknown' at T=+3m and unlocked only after +4h."}


def test_05_no_future_wallet_history_and_social() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    buyer_a = "BuyerA1111111111111111111111111111111111111"
    sig_ts = cts + 180_000
    # Register 2 wins for BuyerA that finalize AFTER `sig_ts` (`sig_ts + 10_000`)
    state.wallets.register_wallet_token_outcome(buyer_a, "Old1", cts - 5_000_000, sig_ts + 10_000, 1, 1.5, True)
    state.wallets.register_wallet_token_outcome(buyer_a, "Old2", cts - 4_000_000, sig_ts + 20_000, 1, 2.0, True)

    engine = UnifiedFeatureEngine()
    snap = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)
    assert snap["model_vector"]["smart_wallets_count_num"] == 0.0, "Future wallet win leaked before label_available_at_ms!"

    # Also test blocking future social timestamp injection via `validate_snapshot_no_leakage`
    bad_soc = copy.deepcopy(snap)
    bad_soc["features"]["has_launch_social_links"]["event_timestamp_ms"] = sig_ts + 500
    caught = False
    try:
        validate_snapshot_no_leakage(bad_soc)
    except FeatureLeakageError:
        caught = True
    assert caught, "Future social event_timestamp_ms was not blocked!"
    return {"passed": True, "details": "Future wallet outcomes (+10s/+20s) excluded at signal_ts; future social event blocked."}


def test_06_training_oot_paper_live_parity() -> dict:
    ds = json.loads((V2_DIR / "cache" / "raw" / "v2_chronological_dataset.json").read_text(encoding="utf-8"))["tokens"][:25]
    state_ckpt = UnifiedStateBundle.load_checkpoint(CHECKPOINTS_DIR / "state_post_wf_v2_1.json")
    engine = UnifiedFeatureEngine()

    max_abs_diff = 0.0
    checked_vectors = 0
    for c in ds:
        m = c["mint"]
        cts = int(c["created_timestamp"])
        sig_ts = cts + 180_000
        c1m = json.loads((V2_DIR / "cache" / "candles" / f"{m}.json").read_text(encoding="utf-8")).get("candles_1m", [])
        tr = json.loads((V2_DIR / "cache" / "trades" / f"{m}.json").read_text(encoding="utf-8")).get("trades", [])

        st_asof = UnifiedStateBundle.load_checkpoint(CHECKPOINTS_DIR / "state_post_wf_v2_1.json", as_of_ts_ms=sig_ts)
        snaps = [
            engine.compute_snapshot(c, tr, c1m, sig_ts, st_asof, mode=md, acquired_at_ms=sig_ts)
            for md in ("training", "validation", "oot", "paper_trading", "live")
        ]
        base_vec = snaps[0]["model_vector"]
        for sn in snaps[1:]:
            for col in ALL_MODEL_FEATURES_V2_1:
                diff = abs(float(base_vec[col]) - float(sn["model_vector"][col]))
                max_abs_diff = max(max_abs_diff, diff)
                assert diff == 0.0, f"Parity mismatch on {col}: {base_vec[col]} vs {sn['model_vector'][col]}"
            assert sn["entry_price_usd"] == snaps[0]["entry_price_usd"]
        checked_vectors += 1

    # Also verify empty ticker tracker NEVER forces `is_ticker_first_mover = 1`!
    cts0, coin0, tr0, c1m0, empty_st = make_base_fixture()
    sn_empty = engine.compute_snapshot(coin0, tr0, c1m0, cts0 + 180_000, empty_st, mode="live")
    assert sn_empty["features"]["ticker_first_mover_num"]["value"] == "insufficient_history"
    assert sn_empty["model_vector"]["ticker_first_mover_num"] == 0.0
    assert sn_empty["model_vector"]["ticker_history_known_flag"] == 0.0

    return {
        "passed": True,
        "tokens_verified": checked_vectors,
        "modes_verified": ["training", "validation", "oot", "paper_trading", "live"],
        "max_abs_feature_diff": max_abs_diff,
        "details": f"100.0% exact bit-for-bit parity (max_diff={max_abs_diff}) across all 5 modes on {checked_vectors} tokens; empty ticker history returns 'insufficient_history' (never forced to 1).",
    }


def test_07_no_double_counting_wallets_or_trades() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    engine = UnifiedFeatureEngine()
    sig_ts = cts + 180_000
    snap_1x = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)
    tripled_trades = trades + copy.deepcopy(trades) + copy.deepcopy(trades)
    snap_3x = engine.compute_snapshot(coin, tripled_trades, candles_1m, sig_ts, state)

    assert snap_1x["buy_volume_usd"] == snap_3x["buy_volume_usd"]
    assert snap_1x["model_vector"]["unique_buyers_cum"] == snap_3x["model_vector"]["unique_buyers_cum"]

    sf_1x = reconstruct_supply_and_fifo_v2_1(coin, trades, [], {}, 3.28e-8, 70.0, sig_ts, True)
    sf_3x = reconstruct_supply_and_fifo_v2_1(coin, tripled_trades, [], {}, 3.28e-8, 70.0, sig_ts, True)
    assert sf_1x["supply"] == sf_3x["supply"]
    assert sf_1x["wallets_pnl"] == sf_3x["wallets_pnl"]
    return {"passed": True, "details": "3x duplicated swap tape yielded identical buyer counts, volume, supply, and FIFO PnL."}


def test_08_supply_concentration_validation() -> dict:
    # 1. Adversarial >100% holder balance anomaly (e.g., off-swap transfer + secondary DEX buy = 110% of supply)
    cts, coin, trades, _, _ = make_base_fixture()
    anom_trades = trades + [
        {
            "txId": "tx_anom_1", "legIndex": 0, "eventIndex": 0,
            "blockTimeMs": cts + 120_000, "blockId": 400, "txIndex": 1,
            "side": "buy", "trader": {"address": "WhaleAnom1111111111111111111111111111111111"},
            "pool": {"address": "UnindexedPool111111111111111111111111111111"},
            "venue": "raydium", "valueUsd": 50000.0, "valueNative": 700.0,
            "priceUsd": 0.00005, "priceQuote": 7e-7, "quotePriceUsd": 70.0,
            "baseAmount": {"raw": str(960_000_000 * 10**6), "decimals": 6},
        }
    ]
    res = reconstruct_supply_and_fifo_v2_1(coin, anom_trades, [], {}, 7e-7, 70.0, cts + 180_000, True)
    assert res["supply"]["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION"
    assert res["supply"]["usable_in_model"] == 0
    assert res["supply"]["top5_holders_pct"] is None

    # 2. Check all 650 rows in real `SUPPLY_CONCENTRATION_V2_1.csv`
    df_sup = pd.read_csv(V2_1_DIR / "SUPPLY_CONCENTRATION_V2_1.csv")
    valid_df = df_sup[df_sup["usable_in_model"] == 1]
    max_sum_pct = float(valid_df["raw_reconstructed_holder_sum_pct"].max())
    max_top20_pct = float(valid_df["top20_holders_pct"].max())
    assert max_sum_pct <= 100.01, f"Valid supply row exceeded 100%: {max_sum_pct}%"
    assert max_top20_pct <= 100.01, f"Top20 exceeded 100%: {max_top20_pct}%"
    inv_cnt = int((df_sup["supply_status"] == "INVALID_SUPPLY_RECONSTRUCTION").sum())
    return {
        "passed": True,
        "valid_tokens_count": int(len(valid_df)),
        "invalid_blocked_count": inv_cnt,
        "max_valid_holder_sum_pct": round(max_sum_pct, 4),
        "details": f"Synthetic 105.4% anomaly blocked as INVALID_SUPPLY_RECONSTRUCTION; all {len(valid_df)} valid cohort tokens <= 100% (max={max_sum_pct:.2f}%, blocked={inv_cnt}).",
    }


def test_09_fifo_realized_pnl_validation() -> dict:
    cts, coin, _, _, _ = make_base_fixture()
    w1 = "TraderFIFO111111111111111111111111111111111"
    w2 = "SellerNoBuy11111111111111111111111111111111"
    fifo_trades = [
        # Lot 1: buy 100 tokens for 1.0 SOL (+ 0.00015 fee = 1.00015 SOL -> 0.0100015/tok)
        {"txId": "f1", "legIndex": 0, "eventIndex": 0, "blockTimeMs": cts + 5000, "blockId": 10, "txIndex": 1,
         "side": "buy", "trader": {"address": w1}, "pool": {"address": coin["bonding_curve"]},
         "valueNative": 1.0, "valueUsd": 70.0, "priceUsd": 0.7, "baseAmount": {"raw": str(100 * 10**6), "decimals": 6}},
        # Lot 2: buy 100 tokens for 3.0 SOL (+ 0.00015 fee = 3.00015 SOL -> 0.0300015/tok)
        {"txId": "f2", "legIndex": 0, "eventIndex": 0, "blockTimeMs": cts + 10000, "blockId": 20, "txIndex": 1,
         "side": "buy", "trader": {"address": w1}, "pool": {"address": coin["bonding_curve"]},
         "valueNative": 3.0, "valueUsd": 210.0, "priceUsd": 2.1, "baseAmount": {"raw": str(100 * 10**6), "decimals": 6}},
        # Sell 150 tokens for 7.5 SOL (- 0.00015 fee = 7.49985 SOL -> 0.049999/tok)
        # FIFO cost of 150 tokens = 100 * 0.0100015 + 50 * 0.0300015 = 1.00015 + 1.500075 = 2.500225 SOL
        # Expected realized PnL = 7.49985 - 2.500225 = +4.999625 SOL! Remaining 50 tokens @ 0.0300015 = 1.500075 SOL cost!
        {"txId": "f3", "legIndex": 0, "eventIndex": 0, "blockTimeMs": cts + 20000, "blockId": 30, "txIndex": 1,
         "side": "sell", "trader": {"address": w1}, "pool": {"address": coin["bonding_curve"]},
         "valueNative": 7.5, "valueUsd": 525.0, "priceUsd": 3.5, "baseAmount": {"raw": str(150 * 10**6), "decimals": 6}},
        # w2 sells 50 tokens WITHOUT any recorded buy -> must be UNKNOWN_COST_BASIS!
        {"txId": "f4", "legIndex": 0, "eventIndex": 0, "blockTimeMs": cts + 25000, "blockId": 35, "txIndex": 1,
         "side": "sell", "trader": {"address": w2}, "pool": {"address": coin["bonding_curve"]},
         "valueNative": 2.5, "valueUsd": 175.0, "priceUsd": 3.5, "baseAmount": {"raw": str(50 * 10**6), "decimals": 6}},
    ]
    out = reconstruct_supply_and_fifo_v2_1(coin, fifo_trades, [], {}, 0.05, 70.0, cts + 60_000, True, tx_fee_sol=0.00015)
    p1 = out["wallets_pnl"][w1]
    p2 = out["wallets_pnl"][w2]
    assert abs(p1["fifo_realized_pnl_sol"] - 4.999625) < 1e-5, f"FIFO math error: {p1['fifo_realized_pnl_sol']}"
    assert abs(p1["remaining_tokens"] - 50.0) < 1e-4
    assert p1["cost_basis_status"] == "FIFO_VERIFIED"
    assert p2["cost_basis_status"] == "UNKNOWN_COST_BASIS" and p2["fifo_realized_pnl_sol"] is None
    return {"passed": True, "details": "Exact 2-lot FIFO realized PnL (+4.999625 SOL) & remaining cost basis verified; unmatched sell flagged UNKNOWN_COST_BASIS."}


def test_10_amm_fees_and_price_impact() -> dict:
    cts, coin, trades, candles_1m, state = make_base_fixture()
    engine = UnifiedFeatureEngine()
    sig_ts = cts + 180_000
    snap = engine.compute_snapshot(coin, trades, candles_1m, sig_ts, state)
    fake_lbl = {"status_4h": "complete", "_exec_path_4h": [(sig_ts + 600_000, 2.6, 0.95, 2.5, "pump")]}

    sizes = [0.1, 0.25, 0.5, 1.0, 2.0]
    res_by_s = [simulate_amm_position_execution(snap, fake_lbl, s) for s in sizes]
    for i in range(len(sizes) - 1):
        assert res_by_s[i]["entry_price_impact_pct"] < res_by_s[i + 1]["entry_price_impact_pct"], "Entry impact not strictly increasing with SOL size!"
        assert res_by_s[i]["net_return_after_fees_pct"] > res_by_s[i + 1]["net_return_after_fees_pct"], "Net return did not degrade with larger size slippage!"
    for r in res_by_s:
        assert r["net_return_after_fees_pct"] < r["executable_return_pct"] <= r["mid_price_return_pct"]

    return {
        "passed": True,
        "sample_2_5x_tp_net_returns_by_sol_size": {str(s): r["net_return_after_fees_pct"] for s, r in zip(sizes, res_by_s)},
        "details": "Constant-product curve impact monotonic across [0.1, 0.25, 0.5, 1.0, 2.0] SOL; net < executable <= mid-price verified.",
    }


def test_11_zero_token_split_leakage() -> dict:
    df_wf = pd.read_csv(V2_1_DIR / "WALK_FORWARD_V2_1.csv")
    assert (df_wf["zero_token_overlap_verified"] == 1).all()
    assert (df_wf["embargo_hours"] >= 4.0).all()

    df_tm = pd.read_csv(V2_1_DIR / "TOKEN_METRICS_V2_1.csv")
    df_oot = pd.read_csv(V2_1_DIR / "OUT_OF_TIME_V2_1.csv")
    train_mints = set(df_tm["mint"].astype(str))
    oot_mints = set(df_oot["mint"].astype(str))
    overlap_tr_oot = len(train_mints & oot_mints)
    assert overlap_tr_oot == 0, f"CRITICAL: {overlap_tr_oot} tokens overlapped between WF/Train and OOT!"

    v1_bt = pd.read_csv(V1_DIR / "BACKTEST_RESULTS.csv", usecols=["mint"])
    overlap_v1_oot = len(set(v1_bt["mint"].astype(str)) & oot_mints)
    assert overlap_v1_oot == 0, f"CRITICAL: {overlap_v1_oot} tokens overlapped between V1 deep cohort and OOT!"
    return {
        "passed": True,
        "wf_folds_verified": len(df_wf),
        "train_oot_overlap": overlap_tr_oot,
        "v1_oot_overlap": overlap_v1_oot,
        "details": f"0 overlapping mints across all {len(df_wf)} Walk-Forward folds (>=4h embargo), V2/V2.1 650-cohort, V1 deep cohort, and {len(oot_mints)} unseen OOT tokens.",
    }


def test_12_censored_observations_handling() -> dict:
    cts, coin, trades, candles_1m, _ = make_base_fixture()
    sig_ts = cts + 180_000
    # Simulate collection timestamp occurring 90 minutes after `sig_ts` -> 1h is complete, 4h & 24h MUST be `"censored"` (NOT 0!)
    c_obj = {
        "collection_timestamp_ms": sig_ts + 90 * 60_000,
        "candles_1m": candles_1m,
        "candles_15m": [],
        "candles_4h": [],
        "api_ok": 1,
    }
    lbl = compute_multi_horizon_labels_and_path(coin, trades, c_obj, sig_ts, 0.0000023, 3.28e-8, 70.0)
    assert lbl["status_1h"] == "complete" and lbl["hit_2x_1h"] == 0
    assert lbl["status_4h"] == "censored" and lbl["hit_2x_4h"] == "censored"
    assert lbl["status_24h"] == "censored" and lbl["hit_2x_24h"] == "censored"

    # Also verify real `OUT_OF_TIME_V2_1.csv` preserves `"censored"` strings on unelapsed 24h rows!
    df_oot = pd.read_csv(V2_1_DIR / "OUT_OF_TIME_V2_1.csv")
    cens_24h = int((df_oot["status_24h"] == "censored").sum())
    assert cens_24h > 0, "Expected unelapsed 24h OOT rows to be marked 'censored'!"
    return {
        "passed": True,
        "oot_24h_censored_rows_verified": cens_24h,
        "details": f"Unelapsed horizons strictly labeled 'censored' (never coerced to 0); verified on synthetic +90m cutoff and {cens_24h} OOT 24h rows.",
    }


def run_all_tests():
    t0 = time.time()
    tests = [
        ("01_no_unclosed_candles", test_01_no_unclosed_candles),
        ("02_no_future_volume", test_02_no_future_volume),
        ("03_no_future_sol_mid_hour", test_03_no_future_sol_mid_hour),
        ("04_no_future_creator_outcomes", test_04_no_future_creator_outcomes),
        ("05_no_future_wallet_history_and_social", test_05_no_future_wallet_history_and_social),
        ("06_training_oot_paper_live_parity", test_06_training_oot_paper_live_parity),
        ("07_no_double_counting_wallets_or_trades", test_07_no_double_counting_wallets_or_trades),
        ("08_supply_concentration_validation", test_08_supply_concentration_validation),
        ("09_fifo_realized_pnl_validation", test_09_fifo_realized_pnl_validation),
        ("10_amm_fees_and_price_impact", test_10_amm_fees_and_price_impact),
        ("11_zero_token_split_leakage", test_11_zero_token_split_leakage),
        ("12_censored_observations_handling", test_12_censored_observations_handling),
    ]
    results = []
    for name, fn in tests:
        res = fn()
        results.append({"test_id": name, **res})
        print(f"[PASS] {name}: {res['details']}")

    summary = {
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r["passed"]),
        "failed_tests": sum(1 for r in results if not r["passed"]),
        "runtime_sec": round(time.time() - t0, 3),
        "results": results,
    }
    out_p = LOGS_DIR / "test_suite_v2_1_results.json"
    out_p.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nALL {summary['passed_tests']}/{summary['total_tests']} V2.1 VERIFICATION TESTS PASSED in {summary['runtime_sec']}s -> {out_p}")


if __name__ == "__main__":
    run_all_tests()
