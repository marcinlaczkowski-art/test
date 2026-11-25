"""Live wallet history feeds H3 causally (+4h), survives restart, and is pruned by retention."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paper_trading.wallet_history_v2_2 import WalletHistoryRecorder, FOUR_H_MS  # noqa: E402
from wallet_intelligence.wallet_intel_v2_2 import WalletIntelligenceEngineV22  # noqa: E402


class FakeHttp:
    def __init__(self, high):
        self.high = high
        self.calls = 0

    def request_json(self, source_id, url, **kw):
        self.calls += 1
        t0 = int(url.split("to=")[1]) - 2 * 3600_000
        return {"ok": True, "data": {"candles": [{"openTimeMs": t0, "high": str(self.high)}]}}


def _snap(mint, cutoff, wallets):
    fifo = {w: {"first_buy_ts_ms": cutoff - 30_000, "pnl_classification": "REALIZED_FIFO_VERIFIED",
                "realized_pnl_sol": 0.05, "unrealized_pnl_sol": 0.0, "average_holding_time_sec": 20.0} for w in wallets}
    return {"token_mint": mint, "created_timestamp_ms": cutoff - 60_000, "envelope": {"temporal_status": "VALID"},
            "_fifo_internal": {"wallets_fifo": fifo}, "_wi_obs_internal": {"active_clusters": []}}


def _swap(w, ts, i):
    return {"txId": f"tx{i}", "legIndex": 0, "eventIndex": 0, "blockTimeMs": ts, "blockId": 100 + i, "txIndex": i,
            "side": "buy", "venue": "pump", "trader": {"address": w}, "pool": {"address": "P"},
            "valueNative": 0.5, "baseAmount": {"raw": "10000000", "decimals": 6}, "priceUsd": "0.00001"}


def test_live_wallet_history_unlocks_h3_after_4h_and_survives_restart():
    d = Path(tempfile.mkdtemp())
    now = int(time.time() * 1000)
    base = now - 6 * 3600_000
    wallets = ["SMART", "B2", "B3"]
    eng = WalletIntelligenceEngineV22()
    rec = WalletHistoryRecorder(d, eng, http=FakeHttp(high=0.00005))  # 5x ref price -> hit_2x_4h = 1
    for k in range(3):
        cut = base + k * 60_000
        trades = [_swap(w, cut - 30_000, j) for j, w in enumerate(wallets)]
        assert rec.record_observation(_snap(f"M{k}", cut, wallets), trades, cut)
    assert not rec.record_observation(_snap("M0", base, wallets), [], base)  # first observation only

    probe_cut = base + 10 * 60_000
    new_coin = {"mint": "NEW", "created_timestamp": probe_cut - 60_000}
    sw = [_swap("SMART", probe_cut - 20_000, 9)]
    # Before outcomes are known nothing qualifies (no look-ahead)
    assert eng.observe_token_pre_signal(new_coin, sw, probe_cut)["qualified_smart_wallets"] == []

    assert rec.resolve_due(now_ms=base + FOUR_H_MS + 3 * 60_000) == 3
    late_cut = base + FOUR_H_MS + 5 * 60_000
    obs = eng.observe_token_pre_signal({"mint": "NEW2", "created_timestamp": late_cut - 60_000},
                                       [_swap("SMART", late_cut - 20_000, 9)], late_cut)
    assert [q["wallet"] for q in obs["qualified_smart_wallets"]] == ["SMART"]
    # A query cutoff before outcome_known_at still sees nothing
    assert eng.observe_token_pre_signal(new_coin, sw, probe_cut)["qualified_smart_wallets"] == []

    # Restart: fresh engine rehydrated from append-only logs, no new HTTP calls
    eng2 = WalletIntelligenceEngineV22()
    http2 = FakeHttp(high=0.0)
    rec2 = WalletHistoryRecorder(d, eng2, http=http2)
    assert rec2.stats["rehydrated_outcomes"] == 3 and not rec2.pending and http2.calls == 0
    obs2 = eng2.observe_token_pre_signal({"mint": "NEW3", "created_timestamp": late_cut - 60_000},
                                         [_swap("SMART", late_cut - 20_000, 9)], late_cut)
    assert len(obs2["qualified_smart_wallets"]) == 1

    # Retention prune drops old history
    rec2.prune(now_ms=now + 10 * 86_400_000)
    assert not eng2.wallet_token_outcomes and not eng2.pair_cobuys


def test_no_hit_when_price_never_doubles_and_skips_thin_tokens():
    d = Path(tempfile.mkdtemp())
    now = int(time.time() * 1000)
    cut = now - 5 * 3600_000
    eng = WalletIntelligenceEngineV22()
    rec = WalletHistoryRecorder(d, eng, http=FakeHttp(high=0.000015))  # 1.5x -> 0
    assert not rec.record_observation(_snap("THIN", cut, ["A", "B"]), [_swap("A", cut - 1, 1)], cut)  # <3 buyers
    assert rec.record_observation(_snap("T", cut, ["A", "B", "C"]), [_swap("A", cut - 1, 1)], cut)
    assert rec.resolve_due(now_ms=now) == 1
    assert all(r["hit_2x_4h"] == 0 for rs in eng.wallet_token_outcomes.values() for r in rs)
