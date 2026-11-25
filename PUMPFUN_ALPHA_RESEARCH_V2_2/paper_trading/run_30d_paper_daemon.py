"""
Continuous 30-Day Real-Time Paper Trading Daemon (`paper_trading/run_30d_paper_daemon.py`).
Polls live Pump.fun & Binance endpoints over strict TLSv1.3 (`CERT_REQUIRED`), logs all uptime/downtime
intervals to `uptime_sessions_log.jsonl`, never executes real blockchain transactions, and stops
automatically once >=30 continuous/cumulative days are collected (or runs `--once` for a single cycle).
"""
import sys
import time
from pathlib import Path

V22_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V22_ROOT))

from data_sources.http_client import VerifiedHttpClient
from data_integrity.temporal_ledger import TemporalIntegrityLedger
from wallet_intelligence.wallet_intel_v2_2 import WalletIntelligenceEngineV22
from feature_engine.feature_engine import CausalMarketRegimeTracker
from paper_trading.paper_engine_v2_2 import PaperTradingEngineV22


def main():
    once = "--once" in sys.argv
    interval_sec = 60.0
    http = VerifiedHttpClient()
    engine = PaperTradingEngineV22(
        http_client=http,
        temporal_ledger=TemporalIntegrityLedger(),
        wallet_engine=WalletIntelligenceEngineV22(),
        regime_tracker=CausalMarketRegimeTracker(),
    )
    print(f"Starting V2.2 Read-Only Paper Trading Engine (mode={'single-cycle' if once else '30-day-daemon'})...")
    while True:
        summary = engine.run_live_scan_cycle(max_tokens=20)
        http.health.persist()
        print(
            f"[Paper V2.2] status={summary['PAPER_TRADING_STATUS']} | "
            f"days={summary['actual_elapsed_days_collected']}/30 | "
            f"candidates={summary['total_detected_candidates']} | "
            f"opened={summary['paper_positions_opened_total']} | "
            f"active={summary['paper_positions_currently_open']}"
        )
        if once or summary["PAPER_TRADING_STATUS"] == "COMPLETED":
            break
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()
