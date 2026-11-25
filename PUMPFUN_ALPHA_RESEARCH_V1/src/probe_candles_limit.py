import urllib.request, urllib.error, json

cid = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
m = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"

for q in [
    "res=1h&limit=100",
    "res=1h&limit=500",
    "res=1h&limit=1000",
    "res=1d&limit=35",
    "res=1m&limit=300",
]:
    url = f"https://frontend-api-v3.pump.fun/candles/{cid}/{m}?{q}"
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10)
        d = json.loads(r.read().decode())
        c = d.get("candles", [])
        print(f"[200] {q} -> count={len(c)}, first_ts={c[0]['openTimeMs'] if c else None}, last_ts={c[-1]['openTimeMs'] if c else None}, keys={list(d.keys())}")
    except urllib.error.HTTPError as e:
        print(f"[{e.code}] {q} -> {e.read(250).decode()}")
