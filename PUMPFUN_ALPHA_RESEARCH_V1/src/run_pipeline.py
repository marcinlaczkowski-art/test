"""
Master reproducible pipeline entrypoint for PUMPFUN ALPHA RESEARCH ENGINE.
Supports automatic resume from disk checkpoints in `cache/`.
Usage:
    python src/run_pipeline.py
"""
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent

STEPS = [
    "step1_acquire_tokens.py",
    "step2_candles_and_trades.py",
    "step3_onchain_and_wallets.py",
    "enrich_rpc_funding.py",
    "step4_analytics_pipeline.py",
    "step5_signals_backtest_hypotheses.py",
    "step6_export_xlsx_and_dashboard.py",
    "step7_generate_reports.py",
]

def main():
    for script in STEPS:
        print(f"=== Running {script} ===")
        ret = subprocess.call([sys.executable, str(SRC / script)])
        if ret != 0:
            sys.exit(ret)
    print("=== PUMPFUN ALPHA RESEARCH PIPELINE COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
