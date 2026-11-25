"""
Global configuration, timestamps, and paths for PUMPFUN ALPHA RESEARCH ENGINE.
"""
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH")
SRC_DIR = BASE_DIR / "src"
CACHE_DIR = BASE_DIR / "cache"
RAW_DIR = CACHE_DIR / "raw"
TRADES_CACHE_DIR = CACHE_DIR / "trades"
CANDLES_CACHE_DIR = CACHE_DIR / "candles"
CREATORS_CACHE_DIR = CACHE_DIR / "creators"
RPC_CACHE_DIR = CACHE_DIR / "rpc"
HOLDINGS_CACHE_DIR = CACHE_DIR / "holdings"
LOGS_DIR = BASE_DIR / "logs"
DASHBOARD_DIR = BASE_DIR / "dashboard"

for d in [BASE_DIR, SRC_DIR, CACHE_DIR, RAW_DIR, TRADES_CACHE_DIR, CANDLES_CACHE_DIR, CREATORS_CACHE_DIR, RPC_CACHE_DIR, HOLDINGS_CACHE_DIR, LOGS_DIR, DASHBOARD_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Fixed exact research window recorded at project start:
# Local start: 2026-11-24T23:22:02+01:00 (Europe/Warsaw, CET)
# UTC start:   2026-11-24T22:22:02+00:00
RESEARCH_END_UTC = datetime(2026, 11, 24, 22, 22, 2, tzinfo=timezone.utc)
RESEARCH_START_UTC = datetime(2026, 10, 25, 22, 22, 2, tzinfo=timezone.utc)

WINDOW_START_MS = int(RESEARCH_START_UTC.timestamp() * 1000)  # 1792966922000
WINDOW_END_MS = int(RESEARCH_END_UTC.timestamp() * 1000)      # 1795558922000

SOLANA_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
PUMPFUN_V3_BASE = "https://frontend-api-v3.pump.fun"
PUMPFUN_PROFILE_BASE = "https://profile-api.pump.fun"
DEXSCREENER_BASE = "https://api.dexscreener.com"
GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
SOLANA_RPC_URL = "https://solana-rpc.publicnode.com"
BINANCE_BASE = "https://api.binance.com/api/v3"

# Known system / technical addresses on Solana & pump.fun (never treat as human/insider holders)
TECHNICAL_ADDRESSES = {
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "ComputeBudget111111111111111111111111111111",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",   # Pump.fun Bonding Curve Program
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",   # PumpSwap AMM Program
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",  # Pump.fun Migration Account
    "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",  # Pump.fun Fee Account
    "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1",  # Pump.fun Event Authority
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium Authority v4
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter v6
}
