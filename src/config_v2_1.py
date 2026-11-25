"""
Configuration for PUMPFUN ALPHA RESEARCH V2.1 (Targeted Fixes).
Leaves V1 and V2 100% untouched.
"""
from pathlib import Path

V1_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH")
V2_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH_V2")
V2_1_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH_V2_1")

SRC_DIR = V2_1_DIR / "src"
TESTS_DIR = V2_1_DIR / "tests"
CACHE_DIR = V2_1_DIR / "cache"
SNAPSHOTS_DIR = CACHE_DIR / "snapshots"
CHECKPOINTS_DIR = CACHE_DIR / "checkpoints"
WALLETS_V2_1_DIR = CACHE_DIR / "wallets_v2_1"
OOT_V2_1_DIR = CACHE_DIR / "oot_v2_1"
FROZEN_BASELINES_DIR = CACHE_DIR / "frozen_baselines"
LOGS_DIR = V2_1_DIR / "logs"
DASHBOARD_DIR = V2_1_DIR / "dashboard"
PAPER_DIR = V2_1_DIR / "paper_trading"

for d in [
    V2_1_DIR, SRC_DIR, TESTS_DIR, CACHE_DIR, SNAPSHOTS_DIR,
    CHECKPOINTS_DIR, WALLETS_V2_1_DIR, OOT_V2_1_DIR, FROZEN_BASELINES_DIR,
    LOGS_DIR, DASHBOARD_DIR, PAPER_DIR
]:
    d.mkdir(parents=True, exist_ok=True)

SOLANA_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
PUMPFUN_V3_BASE = "https://frontend-api-v3.pump.fun"
PUMPFUN_PROFILE_BASE = "https://profile-api.pump.fun"
SOLANA_RPC_URL = "https://solana-rpc.publicnode.com"
BINANCE_BASE = "https://api.binance.com/api/v3"

# Pump.fun canonical bonding curve virtual reserves at genesis (1B standard supply)
PUMPFUN_INIT_VIRTUAL_SOL = 30.0
PUMPFUN_INIT_VIRTUAL_TOKENS = 1_073_000_000.0
PUMPFUN_INIT_K = PUMPFUN_INIT_VIRTUAL_SOL * PUMPFUN_INIT_VIRTUAL_TOKENS  # 3.219e10
PUMPFUN_REAL_CURVE_TOKENS = 793_100_000.0

INTERVAL_MS = {
    "1s": 1_000,
    "15s": 15_000,
    "30s": 30_000,
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

CONFIRMED_TECHNICAL_ADDRESSES = {
    "11111111111111111111111111111111": "System_Program_Or_Burn",
    "1nc1nerator11111111111111111111111111111111": "Incinerator_Burn",
    "So11111111111111111111111111111111111111112": "Wrapped_SOL_Mint",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "SPL_Token_Program",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "SPL_Token_2022_Program",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated_Token_Program",
    "ComputeBudget111111111111111111111111111111": "Compute_Budget_Program",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "PumpFun_Bonding_Curve_Program",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "PumpSwap_AMM_Program",
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg": "PumpFun_Migration_Authority",
    "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM": "PumpFun_Fee_Vault",
    "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1": "PumpFun_Event_Authority",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium_AMM_v4",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": "Raydium_Authority_v4",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "Raydium_CPMM",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter_Aggregator_v6",
}
