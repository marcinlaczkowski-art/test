"""Velocity rule (buyers in window, creator dump, operator) and paper exit logic (half at 2x, trailing, max hold)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paper_trading.velocity_scanner import evaluate_rule, step_position  # noqa: E402

C0 = 1_000_000


def tr(addr, side, sec, amt=1000.0, price=1.0):
    return {"blockTimeMs": C0 + int(sec * 1000), "side": side, "trader": {"address": addr},
            "baseAmount": {"raw": str(int(amt * 1e6)), "decimals": 6}, "priceUsd": str(price)}


def test_rule_counts_unique_buyers_in_window_only():
    trades = [tr("DEV", "buy", 0)] + [tr(f"B{i}", "buy", 1 + i) for i in range(45)]
    ok, why, st = evaluate_rule(trades, C0, "DEV", 60, 40)
    assert ok and why == "PASS" and st["buyers"] == 45
    late = [tr("DEV", "buy", 0)] + [tr(f"B{i}", "buy", 61 + i) for i in range(45)]
    assert evaluate_rule(late, C0, "DEV", 60, 40)[1] == "FEW_BUYERS"


def test_rule_rejects_creator_dump_and_operator():
    trades = [tr("DEV", "buy", 0, 1000), tr("DEV", "sell", 3, 950)] + [tr(f"B{i}", "buy", 1 + i) for i in range(45)]
    assert evaluate_rule(trades, C0, "DEV", 60, 40)[1] == "CREATOR_DUMP_20S"
    ok_trades = [tr("DEV", "buy", 0)] + [tr(f"B{i}", "buy", 1 + i) for i in range(45)]
    assert evaluate_rule(ok_trades, C0, "DEV", 60, 40, operator_wallets={"DEV"})[1] == "OPERATOR"


def _pos():
    return {"entry": 1.0, "peak": 1.0, "last": 1.0, "half": False, "realized": 0.0, "left": 1.0,
            "status": "OPEN", "entry_ts": 0}


def test_half_at_2x_then_trailing_stop():
    p = _pos()
    assert step_position(p, 2.1, 1000, 2.0, 0.3, 900) == ["HALF"]
    assert step_position(p, 3.0, 2000, 2.0, 0.3, 900) == []
    assert step_position(p, 2.0, 3000, 2.0, 0.3, 900) == ["EXIT"]   # 2.0 <= 3.0 * 0.7
    k = 0.97 / 1.03
    assert abs(p["result"] - (0.5 * 2.1 * k + 0.5 * 2.0 * k - 1)) < 1e-3 and p["exit_reason"] == "TRAILING_STOP"


def test_max_hold_exit():
    p = _pos()
    assert step_position(p, 1.1, 900_000, 2.0, 0.3, 900) == ["EXIT"] and p["exit_reason"] == "MAX_HOLD"
