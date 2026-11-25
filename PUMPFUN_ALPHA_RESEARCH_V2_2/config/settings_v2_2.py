"""
Centralized Configuration for PUMPFUN ALPHA RESEARCH V2.2.
Strictly read-only with respect to V1, V2, and V2.1 directories.
Zero private keys, zero wallet signing, zero real trading.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
V1_ROOT = REPO_ROOT / "PUMPFUN_ALPHA_RESEARCH_V1"
V2_ROOT = REPO_ROOT / "PUMPFUN_ALPHA_RESEARCH_V2"
V2_1_ROOT = REPO_ROOT / "PUMPFUN_ALPHA_RESEARCH_V2_1"
V2_2_ROOT = REPO_ROOT / "PUMPFUN_ALPHA_RESEARCH_V2_2"

CONFIG_DIR = V2_2_ROOT / "config"
DATA_SOURCES_DIR = V2_2_ROOT / "data_sources"
DATA_INTEGRITY_DIR = V2_2_ROOT / "data_integrity"
FEATURE_ENGINE_DIR = V2_2_ROOT / "feature_engine"
WALLET_INTEL_DIR = V2_2_ROOT / "wallet_intelligence"
AMM_DIR = V2_2_ROOT / "amm_reconstruction"
HYPOTHESIS_DIR = V2_2_ROOT / "hypothesis_engine"
SCORING_DIR = V2_2_ROOT / "scoring"
BACKTESTING_DIR = V2_2_ROOT / "backtesting"
OOT_DIR = V2_2_ROOT / "oot"
# Paper-trading state (append-only logs) can live outside the code tree, e.g. a Docker volume.
PAPER_DIR = Path(os.environ["V2_2_PAPER_DIR"]) if os.environ.get("V2_2_PAPER_DIR") else V2_2_ROOT / "paper_trading"
MONITORING_DIR = V2_2_ROOT / "monitoring"
DASHBOARD_DIR = V2_2_ROOT / "dashboard"
TESTS_DIR = V2_2_ROOT / "tests"
REPORTS_DIR = V2_2_ROOT / "reports"
DATA_DIR = V2_2_ROOT / "data"

for _d in [
    CONFIG_DIR, DATA_SOURCES_DIR, DATA_INTEGRITY_DIR, FEATURE_ENGINE_DIR,
    WALLET_INTEL_DIR, AMM_DIR, HYPOTHESIS_DIR, SCORING_DIR, BACKTESTING_DIR,
    OOT_DIR, PAPER_DIR, MONITORING_DIR, DASHBOARD_DIR, TESTS_DIR, REPORTS_DIR, DATA_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)

DATA_VERSION = "v2.2.0"
SOLANA_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# Verified HTTPS Data Sources Specification (Section 4)
DATA_SOURCES_REGISTRY = {
    "pumpfun_v3": {
        "base_url": "https://frontend-api-v3.pump.fun",
        "host": "frontend-api-v3.pump.fun",
        "data_type": "New token launches, OHLCV candles (1m/15m/4h), paginated swap tape, creator coins",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 8.0,
        "max_concurrency": 3,
        "rate_limit_rps": 3.0,
        "max_retries": 3,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_cooldown_sec": 20.0,
    },
    "pumpfun_profile": {
        "base_url": "https://profile-api.pump.fun",
        "host": "profile-api.pump.fun",
        "data_type": "Wallet profile metadata and token balances",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 7.0,
        "max_concurrency": 3,
        "rate_limit_rps": 3.0,
        "max_retries": 2,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_cooldown_sec": 20.0,
    },
    "solana_rpc_publicnode": {
        "base_url": "https://solana-rpc.publicnode.com",
        "host": "solana-rpc.publicnode.com",
        "data_type": "Solana JSON-RPC (getSignaturesForAddress, getTransaction jsonParsed)",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 9.0,
        "max_concurrency": 4,
        "rate_limit_rps": 5.0,
        "max_retries": 3,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_cooldown_sec": 20.0,
    },
    "solana_rpc_mainnet_official": {
        "base_url": "https://api.mainnet-beta.solana.com",
        "host": "api.mainnet-beta.solana.com",
        "data_type": "Fallback Solana JSON-RPC (verified mainnet-beta endpoint)",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 9.0,
        "max_concurrency": 2,
        "rate_limit_rps": 2.0,
        "max_retries": 2,
        "circuit_breaker_threshold": 4,
        "circuit_breaker_cooldown_sec": 30.0,
    },
    "binance_spot": {
        "base_url": "https://api.binance.com",
        "host": "api.binance.com",
        "data_type": "SOLUSDT closed OHLCV klines (1h/15m) for SOL market regime & volatility",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 7.0,
        "max_concurrency": 3,
        "rate_limit_rps": 5.0,
        "max_retries": 3,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_cooldown_sec": 20.0,
    },
    "dexscreener_api": {
        "base_url": "https://api.dexscreener.com",
        "host": "api.dexscreener.com",
        "data_type": "Secondary DEX pair verification for migrated tokens (non-equivalent fallback)",
        "connect_timeout_sec": 4.0,
        "read_timeout_sec": 7.0,
        "max_concurrency": 2,
        "rate_limit_rps": 3.0,
        "max_retries": 2,
        "circuit_breaker_threshold": 4,
        "circuit_breaker_cooldown_sec": 25.0,
    },
}

# Canonical Pump.fun Bonding Curve Genesis Parameters (1,000,000,000 supply)
PUMPFUN_INIT_VIRTUAL_SOL = 30.0
PUMPFUN_INIT_VIRTUAL_TOKENS = 1_073_000_000.0
PUMPFUN_INIT_K = PUMPFUN_INIT_VIRTUAL_SOL * PUMPFUN_INIT_VIRTUAL_TOKENS  # 3.219e10
PUMPFUN_INIT_REAL_TOKEN_RESERVES = 793_100_000.0
PUMPFUN_GRADUATION_REAL_SOL = 85.0

# Execution & Cost Parameters (Section 5.3)
POSITION_SIZES_SOL = [0.1, 0.25, 0.5, 1.0, 2.0]
PUMPFUN_PROTOCOL_FEE_RATE = 0.0100   # 1.00% bonding-curve protocol fee
AMM_SWAP_FEE_RATE = 0.0030           # 0.30% post-migration AMM LP/protocol fee
SOLANA_BASE_NETWORK_FEE_SOL = 0.000005
SOLANA_PRIORITY_FEE_SOL = 0.000495   # Realistic competitive priority fee per swap leg

# Live Scanner & Paper Trading Thresholds (Sections 3.3 & 10)
MAX_LIVE_DISCOVERY_AGE_SEC = 300.0   # Tokens first discovered >300s old are marked LATE_DISCOVERY
PAPER_DEFAULT_SIZE_SOL = 0.25
PAPER_TP_MULT = 2.20                 # +120% take profit
PAPER_SL_MULT = 0.60                 # -40% stop loss
PAPER_TRAILING_ACTIVATE_MULT = 1.50  # Activate trailing stop once >=1.5x reached
PAPER_TRAILING_DRAWDOWN = 0.25       # Exit on -25% pullback from post-activation peak
PAPER_TIME_STOP_SEC = 4 * 3600       # 4-hour maximum hold
MIN_PAPER_DURATION_DAYS = 30         # Minimum 30 days required for PAPER_TRADING_STATUS = COMPLETED
MIN_OOT_TOKENS_REQUIRED = 1000       # Minimum 1,000 OOT tokens (Section 9.2)
MIN_OOT_POSITIVES_REQUIRED = 30      # Minimum 30 positive events on primary target (Section 9.2)

INTERVAL_MS = {
    "1s": 1_000,
    "15s": 15_000,
    "30s": 30_000,
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "24h": 86_400_000,
}

# System / Technical / Burn / Program Addresses (Excluded from human supply denominator, documented!)
SYSTEM_AND_POOL_ADDRESSES = {
    "11111111111111111111111111111111": "Solana_System_Or_Burn",
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

# Known Major Solana CEX / Custody Hot Wallets (NEVER classified as shared private insider!)
KNOWN_CEX_CUSTODY_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance_Hot_Wallet_2",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance_Hot_Wallet_3",
    "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S": "Binance_Hot_Wallet_1",
    "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS": "Coinbase_Hot_Wallet_1",
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE": "Coinbase_Hot_Wallet_2",
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHs5ACWjtW2": "Bybit_Hot_Wallet",
    "5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmcD": "OKX_Hot_Wallet",
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "MEXC_Hot_Wallet",
    "G2YxRa6wt1qePMwfJzdXZG62ej4qaTC7YURzuh2Lwd3t": "Kraken_Hot_Wallet",
}
