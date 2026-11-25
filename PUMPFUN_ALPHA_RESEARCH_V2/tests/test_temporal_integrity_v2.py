"""
Unit Tests for P0 Temporal Integrity, Anti-Leakage Guarantees, Right-Censoring,
and `label_available_at < signal_timestamp` Enforcement.
"""
import sys
import math
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from temporal_integrity_v2 import (
    candle_close_time_ms,
    filter_closed_candles_before,
    filter_candles_strictly_inside_horizon,
    get_causal_entry_price,
    compute_fixed_horizon_labels,
    CausalHistoryTracker,
)

class TestTemporalIntegrityV2(unittest.TestCase):
    def test_unclosed_candle_never_leaks_into_entry_price(self):
        # Token created at t=1_000_000. Signal at t=1_060_000 (+60s).
        # Trade at +20s had price $0.000010.
        # A 1m candle opened at 1_020_000 (closes at 1_080_000 > signal_ts!) spiked to $0.000099 at +75s!
        trades = [{"blockTimeMs": 1_020_000, "priceUsd": "0.000010", "valueUsd": "50.0"}]
        candles_1m = [
            {"openTimeMs": 960_000, "open": "0.000003", "high": "0.000005", "low": "0.000003", "close": "0.000005", "volumeUsd": "30"},
            {"openTimeMs": 1_020_000, "open": "0.000010", "high": "0.000099", "low": "0.000010", "close": "0.000099", "volumeUsd": "5000"},
        ]
        res = get_causal_entry_price(trades, candles_1m, created_ts_ms=1_000_000, signal_ts_ms=1_060_000, sol_price_usd=70.0)
        # MUST NOT see 0.000099 from the unclosed candle! Must use 0.000010 at t=1_020_000!
        self.assertAlmostEqual(res["entry_price_usd"], 0.000010, places=9)
        self.assertLessEqual(res["price_timestamp_ms"], 1_060_000)

    def test_4h_candle_never_leaks_beyond_1h_horizon(self):
        # Signal at t=0. 1h horizon ends at 3_600_000.
        # A 4h candle opened at t=0 (closes at 14_400_000) pumped 20x in hour 3, while 1m candles in hour 1 stayed flat!
        c_1m = [{"openTimeMs": 60_000, "open": "0.001", "high": "0.0011", "low": "0.0009", "close": "0.001", "volumeUsd": "100", "trades": 5}]
        c_4h = [{"openTimeMs": 0, "open": "0.001", "high": "0.025", "low": "0.0009", "close": "0.020", "volumeUsd": "50000", "trades": 200}]
        labels = compute_fixed_horizon_labels(
            signal_ts_ms=0,
            entry_price_usd=0.001,
            entry_liq_usd=5000.0,
            sol_price_usd=70.0,
            collection_ts_ms=20_000_000,
            api_ok=1,
            trades=[],
            candles_1m=c_1m,
            candles_15m=[],
            candles_4h=c_4h,
        )
        self.assertEqual(labels["status_1h"], "complete")
        self.assertEqual(labels["hit_2x_1h"], 0, "4h candle leaked into 1h label!")
        self.assertEqual(labels["status_4h"], "complete")
        self.assertEqual(labels["hit_5x_4h"], 1, "4h horizon should legitimately see the closed 4h bar!")

    def test_right_censoring_marks_nan_not_zero(self):
        # Collection happened 2 hours after signal -> 1h is complete, 4h and 24h MUST be censored (NaN, not 0)!
        labels = compute_fixed_horizon_labels(
            signal_ts_ms=1_000_000,
            entry_price_usd=0.001,
            entry_liq_usd=5000.0,
            sol_price_usd=70.0,
            collection_ts_ms=1_000_000 + 2 * 3_600_000,
            api_ok=1,
            trades=[],
            candles_1m=[],
            candles_15m=[],
            candles_4h=[],
        )
        self.assertEqual(labels["status_1h"], "complete")
        self.assertEqual(labels["hit_2x_1h"], 0)
        self.assertEqual(labels["status_4h"], "censored")
        self.assertTrue(np.isnan(labels["hit_2x_4h"]))
        self.assertEqual(labels["status_24h"], "censored")
        self.assertTrue(np.isnan(labels["hit_2x_24h"]))

    def test_label_available_at_blocks_premature_creator_and_wallet_leakage(self):
        tracker = CausalHistoryTracker()
        # Creator launched Token A at t=1000, which pumped 10x at t=50_000, evaluated on 4h horizon (label_available_at = 1000 + 14_400_000 = 14_401_000).
        tracker.register_creator_token("CreatorX", created_ts_ms=1000, label_available_at_ms=14_401_000, is_winner=1)
        tracker.register_wallet_entry("Whale1", entry_ts_ms=1500, label_available_at_ms=14_401_500, is_winner=1)
        tracker.register_wallet_entry("Whale1", entry_ts_ms=2000, label_available_at_ms=14_402_000, is_winner=1)

        # Token B launches 30 minutes later at t=1_801_000 (BEFORE Token A's 4h label_available_at!).
        c_early = tracker.get_creator_stats_at("CreatorX", signal_ts_ms=1_801_000)
        self.assertEqual(c_early["creator_prior_launches_count"], 1)
        self.assertEqual(c_early["creator_evaluated_prior_count"], 0)
        self.assertEqual(c_early["creator_prior_win_rate"], 0.0, "Premature creator win rate leaked before label_available_at!")

        w_early = tracker.get_smart_wallets_count_at(["Whale1"], signal_ts_ms=1_801_000, min_eval_entries=2)
        self.assertEqual(w_early["causal_smart_wallets_in"], 0, "Premature smart wallet win leaked before label_available_at!")

        # Token C launches at t=15_000_000 (AFTER label_available_at!). Now the wins are causally available!
        c_late = tracker.get_creator_stats_at("CreatorX", signal_ts_ms=15_000_000)
        self.assertEqual(c_late["creator_evaluated_prior_count"], 1)
        self.assertEqual(c_late["creator_prior_win_rate"], 1.0)
        self.assertLessEqual(c_late["max_history_ts_used"], 15_000_000)

        w_late = tracker.get_smart_wallets_count_at(["Whale1"], signal_ts_ms=15_000_000, min_eval_entries=2)
        self.assertEqual(w_late["causal_smart_wallets_in"], 1)
        self.assertLessEqual(w_late["max_wallet_history_ts_used"], 15_000_000)

if __name__ == "__main__":
    unittest.main()
