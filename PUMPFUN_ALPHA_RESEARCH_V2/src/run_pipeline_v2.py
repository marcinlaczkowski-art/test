"""
Master reproducible pipeline entrypoint for PUMPFUN ALPHA RESEARCH ENGINE V2.
Leaves V1 (`PUMPFUN_ALPHA_RESEARCH`) 100% untouched.
"""
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent
TESTS = SRC.parent / "tests"

STEPS = [
    (TESTS / "test_temporal_integrity_v2.py", "Unit Tests P0: Temporal Integrity & Anti-Leakage"),
    (TESTS / "test_wallet_fifo_and_backtest_v2.py", "Unit Tests P1/P0: FIFO PnL, 8-Cat Wallets & Event Backtest"),
    (SRC / "step0_freeze_v1.py", "Step 0: V1 SHA-256 Manifest & Freeze"),
    (SRC / "step1_build_chronological_dataset_v2.py", "Step 1: Chronological Outcome-Blind Dataset"),
    (SRC / "step2_paginated_wallet_rpc_v2.py", "Step 2: Multi-Page Solana RPC Forensics"),
    (SRC / "step3_core_pipeline_v2.py", "Step 3: Causal Signals, FIFO, Walk-Forward, Ablations & V2 Freeze"),
    (SRC / "step4_out_of_time_and_paper_trading_v2.py", "Step 4: Post-Freeze Unseen Data Test & Paper Trading"),
    (SRC / "step5_export_xlsx_dashboard_reports_v2.py", "Step 5: Reports, XLSX, Dashboard V2 & Data Manifest"),
]

def main():
    for path, label in STEPS:
        print(f"=== {label} ({path.name}) ===")
        rc = subprocess.call([sys.executable, str(path)])
        if rc != 0:
            sys.exit(rc)
    print("=== PUMPFUN ALPHA V2 PIPELINE COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
