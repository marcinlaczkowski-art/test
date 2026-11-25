"""
Unit Tests for P1 FIFO Cost-Basis PnL, 8-Category Wallet Classification,
Event-Driven Execution Simulator (Stop-Loss Priority & Liquidity Collapse),
and Embargoed Token-Disjoint Walk-Forward Splits.
"""
import sys
import unittest
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from wallet_insider_fifo_v2 import compute_fifo_pnl_for_token, classify_token_wallet_relationships_v2
from event_backtest_and_walkforward_v2 import simulate_event_driven_position, build_embargoed_walkforward_splits

class TestWalletFifoAndBacktestV2(unittest.TestCase):
    def test_fifo_cost_basis_and_unmatched_inventory_separation(self):
        # Wallet W1 buys 1000 tokens for 1.0 SOL, then buys 1000 tokens for 3.0 SOL.
        # Next sells 1500 tokens for 4.5 SOL (3.0 SOL/1000).
        # Under FIFO: cost of 1500 sold = 1000*(1.0/1000) + 500*(3.0/1000) = 2.5 SOL (plus fees).
        # Remaining 500 tokens have cost basis = 1.5 SOL!
        # Wallet W2 sells 500 tokens WITHOUT any recorded buy -> MUST NOT count as realized profit; must go to unattributed_sell_proceeds_sol!
        trades = [
            {"blockTimeMs": 1000, "trader": {"address": "W1"}, "side": "buy", "baseAmount": {"raw": "1000000000", "decimals": 6}, "valueNative": "1.0", "valueUsd": "70.0", "quotePriceUsd": "70.0"},
            {"blockTimeMs": 2000, "trader": {"address": "W1"}, "side": "buy", "baseAmount": {"raw": "1000000000", "decimals": 6}, "valueNative": "3.0", "valueUsd": "210.0", "quotePriceUsd": "70.0"},
            {"blockTimeMs": 3000, "trader": {"address": "W1"}, "side": "sell", "baseAmount": {"raw": "1500000000", "decimals": 6}, "valueNative": "4.5", "valueUsd": "315.0", "quotePriceUsd": "70.0"},
            {"blockTimeMs": 4000, "trader": {"address": "W2"}, "side": "sell", "baseAmount": {"raw": "500000000", "decimals": 6}, "valueNative": "2.0", "valueUsd": "140.0", "quotePriceUsd": "70.0"},
        ]
        res = compute_fifo_pnl_for_token(trades, [], 1_000_000_000.0, mark_price_usd=0.28, sol_price_usd=70.0, technical_addrs=set(), is_tape_complete=True, tx_fee_sol_est=0.0)
        w1 = res["wallets"]["W1"]
        w2 = res["wallets"]["W2"]
        self.assertAlmostEqual(w1["fifo_realized_pnl_sol"], 4.5 - 2.5, places=4)
        self.assertAlmostEqual(w1["remaining_fifo_tokens"], 500.0, places=2)
        self.assertAlmostEqual(w1["remaining_cost_basis_sol"], 1.5, places=4)
        self.assertEqual(w1["pnl_completeness"], "EXACT_FIFO_VERIFIED")

        # W2 had 0 FIFO lots -> realized FIFO PnL MUST be 0.0, and 2.0 SOL goes to unattributed!
        self.assertAlmostEqual(w2["fifo_realized_pnl_sol"], 0.0, places=5)
        self.assertAlmostEqual(w2["unattributed_sell_proceeds_sol"], 2.0, places=4)
        self.assertEqual(w2["pnl_completeness"], "PARTIAL_UNMATCHED_INVENTORY")

    def test_same_slot_co_buyers_not_marked_proven_insider_control(self):
        trades = [
            {"blockId": 500, "txIndex": 10, "side": "buy", "trader": {"address": "A"}},
            {"blockId": 500, "txIndex": 45, "side": "buy", "trader": {"address": "B"}},
        ]
        w_map = {"A": {"remaining_fifo_tokens": 1000.0}, "B": {"remaining_fifo_tokens": 1000.0}}
        rows, summ = classify_token_wallet_relationships_v2("Mint1", "CreatorZ", trades, {}, {}, {}, {}, w_map, 1_000_000.0)
        co_row = next(r for r in rows if r["category"] == "1_Same_slot_co_buyers")
        self.assertEqual(co_row["proven_shared_control"], 0)
        self.assertEqual(summ["verified_onchain_insider_supply_pct"], 0.0)

    def test_event_backtest_stop_loss_priority_and_illiquidity_rejection(self):
        # Low liquidity (<$1200) must reject fill rather than hallucinating chart profit!
        no_fill = simulate_event_driven_position(0, 0.001, entry_liq_usd=500.0, sol_price_usd=70.0, trades=[], candles_1m=[], candles_15m=[])
        self.assertEqual(no_fill["execution_status"], "NO_FILL_INSUFFICIENT_LIQUIDITY")

        # Candle where BOTH low hits -50% stop-loss AND high hits +200% TP1 -> conservative engine MUST trigger STOP_LOSS!
        c_1m = [{"openTimeMs": 60_000, "open": "0.001", "high": "0.003", "low": "0.0004", "close": "0.002", "volumeUsd": "500"}]
        sim = simulate_event_driven_position(0, 0.001, entry_liq_usd=10_000.0, sol_price_usd=70.0, trades=[], candles_1m=c_1m, candles_15m=[])
        self.assertEqual(sim["exit_reason"], "STOP_LOSS")
        self.assertLess(sim["net_return_pct"], -35.0)

    def test_walkforward_splits_enforce_token_disjointness_and_embargo(self):
        rows = []
        for i in range(120):
            cts = i * 20_000_000  # spaced by >5.5h so 4h embargo is cleanly satisfied
            rows.append({"mint": f"M_{i}", "created_timestamp_ms": cts, "signal_timestamp_ms": cts + 300_000})
        df = pd.DataFrame(rows)
        splits = build_embargoed_walkforward_splits(df, embargo_ms=14_400_000, n_test_folds=3)
        self.assertGreaterEqual(len(splits), 2)
        for sp in splits:
            self.assertEqual(len(sp["train_mints"] & sp["test_mints"]), 0)
            self.assertEqual(len(sp["val_mints"] & sp["test_mints"]), 0)
            self.assertGreaterEqual(sp["actual_embargo_minutes"], 240.0)

if __name__ == "__main__":
    unittest.main()
