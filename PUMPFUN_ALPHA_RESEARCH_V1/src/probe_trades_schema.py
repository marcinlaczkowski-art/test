import urllib.request, json

cid = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
m = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
m2 = "28AFQT6w7hr4DbvYs1mEQNRWRrWNHFMFW7qHDgtapump"

def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://pump.fun"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

r = get(f"https://frontend-api-v3.pump.fun/trades/{cid}/{m2}?limit=3")
print("RESPONSE KEYS:", list(r.keys()))
print("PAGINATION/META:", {k: v for k, v in r.items() if k != "trades"})
print("TRADE 0:", json.dumps(r["trades"][0], indent=2))

for q in [
    "limit=5&order=ASC",
    "limit=5&sortOrder=ASC",
    "limit=200",
    f"limit=5&cursor={r['trades'][-1]['ordinalKey']}",
    f"limit=5&before={r['trades'][-1]['ordinalKey']}",
    f"limit=5&after=0",
    "limit=5&createdTs=0",
]:
    try:
        d = get(f"https://frontend-api-v3.pump.fun/trades/{cid}/{m2}?{q}")
        ts = [t["blockTimeMs"] for t in d.get("trades", [])]
        print("[OK]", q, "count:", len(ts), "ts_first_last:", (ts[0], ts[-1]) if ts else None, "meta:", {k: v for k, v in d.items() if k != "trades"})
    except urllib.error.HTTPError as e:
        print("[HTTP]", q, e.code, e.read(200).decode())
    except Exception as e:
        print("[ERR]", q, e)

for path in [
    f"candles/{cid}/{m2}?interval=1m&limit=5",
    f"bars/{cid}/{m2}?resolution=1&limit=5",
    f"ohlcv/{cid}/{m2}?interval=1m&limit=5",
    f"holders/solana/{m2}",
    f"coins/holders/{m2}",
    f"coins?mints={m},{m2}",
]:
    try:
        d = get(f"https://frontend-api-v3.pump.fun/{path}")
        print("[PATH OK]", path, str(d)[:250])
    except urllib.error.HTTPError as e:
        print("[PATH HTTP]", path, e.code, e.read(160).decode())
