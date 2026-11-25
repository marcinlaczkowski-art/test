import urllib.request
import urllib.error
import json
import ssl
from datetime import datetime, timezone, timedelta

now_utc = datetime.now(timezone.utc)
start_utc = now_utc - timedelta(days=30)
print(f"PROBE TIME UTC: {now_utc.isoformat()}")
print(f"WINDOW START UTC: {start_utc.isoformat()}")

ENDPOINTS = [
    ("pumpfun_frontend_v3_coins", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true", "GET", None),
    ("pumpfun_frontend_v3_mcap", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=market_cap&order=DESC&includeNsfw=true", "GET", None),
    ("pumpfun_frontend_v2_coins", "https://frontend-api-v2.pump.fun/coins?offset=0&limit=5&sort=created_timestamp&order=DESC", "GET", None),
    ("pumpfun_frontend_v1_coins", "https://frontend-api.pump.fun/coins?offset=0&limit=5&sort=created_timestamp&order=DESC", "GET", None),
    ("pumpfun_advanced_api", "https://advanced-api-v2.pump.fun/coins/list?sortBy=creationTime", "GET", None),
    ("dexscreener_search_pump", "https://api.dexscreener.com/latest/dex/search?q=pump", "GET", None),
    ("dexscreener_token_profiles", "https://api.dexscreener.com/token-profiles/latest/v1", "GET", None),
    ("dexscreener_token_boosts", "https://api.dexscreener.com/token-boosts/top/v1", "GET", None),
    ("geckoterminal_solana_trending", "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools", "GET", None),
    ("geckoterminal_solana_new", "https://api.geckoterminal.com/api/v2/networks/solana/new_pools", "GET", None),
    ("geckoterminal_pumpswap_pools", "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pumpswap/pools?page=1", "GET", None),
    ("geckoterminal_pumpfun_pools", "https://api.geckoterminal.com/api/v2/networks/solana/dexes?page=1", "GET", None),
    ("solana_rpc_mainnet", "https://api.mainnet-beta.solana.com", "POST", {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}),
    ("ankr_solana_rpc", "https://rpc.ankr.com/solana", "POST", {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}),
    ("publicnode_solana_rpc", "https://solana-rpc.publicnode.com", "POST", {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}),
    ("reddit_pumpfun", "https://www.reddit.com/r/pumpfun/new.json?limit=5", "GET", None),
    ("binance_solusdt_klines", "https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1d&limit=31", "GET", None),
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

results = {}
for name, url, method, payload in ENDPOINTS:
    try:
        data = json.dumps(payload).encode("utf-8") if payload else None
        req_headers = dict(headers)
        if payload:
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read(2000).decode("utf-8", errors="replace")
            print(f"[OK {resp.status}] {name}: {body[:180].replace(chr(10), ' ')}")
            results[name] = {"status": resp.status, "sample": body[:500]}
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="replace") if e.fp else ""
        print(f"[HTTP {e.code}] {name}: {body[:140].replace(chr(10), ' ')}")
        results[name] = {"status": e.code, "error": body[:300]}
    except Exception as e:
        print(f"[ERR] {name}: {type(e).__name__}: {e}")
        results[name] = {"status": "ERR", "error": str(e)}

with open(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH\probe_results.json", "w", encoding="utf-8") as f:
    json.dump({"probe_utc": now_utc.isoformat(), "window_start_utc": start_utc.isoformat(), "endpoints": results}, f, indent=2)
