"""
Exit timing (READ-ONLY): wejscie w N. minucie zycia tokena (domyslnie 10) -> jaki wynik przy zamknieciu
po 1, 2, 3, 5, 10, 15, 20, 30, 45, 60 min? Kiedy token jest "ubity" (cena <= 20% ceny wejscia)?

Zrodlo mintow: log sygnalow demona paper tradingu (wszystkie tokeny, ktore demon widzial na zywo),
filtrowany do tokenow utworzonych w ostatnich --hours godzin. Ceny ze swiec 1m pump.fun.

  python tools/exit_timing.py --signals /data/paper/signals_log.jsonl --hours 24 --n 400
"""
import argparse
import json
import random
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID  # noqa: E402
from data_sources.http_client import VerifiedHttpClient  # noqa: E402

COST = 0.03            # prowizja + poslizg na strone (zalozenie)
DEAD_LEVEL = 0.20      # "ubity" = cena <= 20% ceny wejscia (-80%)
EXITS = (1, 2, 3, 5, 10, 15, 20, 30, 45, 60)


def load_mints(path, hours):
    lim = time.time() * 1000 - hours * 3600_000
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = r.get("token_mint")
            cts = None
            if r.get("event_ts_ms") and r.get("token_age_seconds") is not None:
                cts = int(r["event_ts_ms"]) - int(float(r["token_age_seconds"]) * 1000)
            if m and m not in out:
                out[m] = int(cts) if cts else None
    return {m: c for m, c in out.items() if c is None or c >= lim}


def get(http, url):
    for a in range(5):
        time.sleep(0.25)
        r = http.request_json("pumpfun_v3", url)
        if r["ok"]:
            return r["data"]
        time.sleep(2 ** a)
    return None


def analyze(http, mint, created, entry_min, horizon_min):
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    if not created:
        d = get(http, f"{base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=1&after=1-0-0-0")
        tr = (d or {}).get("trades") or []
        if not tr:
            return {"mint": mint, "status": "NO_DATA"}
        created = int(tr[0]["blockTimeMs"])
    entry_ts = created + entry_min * 60_000
    end_ts = entry_ts + horizon_min * 60_000
    if end_ts > time.time() * 1000:
        return {"mint": mint, "status": "TOO_YOUNG"}
    d = get(http, f"{base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={end_ts + 60_000}")
    cs = sorted(((int(c["openTimeMs"]), float(c["close"]), float(c["low"]), float(c["high"])) for c in (d or {}).get("candles") or []
                 if float(c.get("close") or 0) > 0), key=lambda x: x[0])
    before = [c for c in cs if c[0] + 60_000 <= entry_ts]
    if not before or before[-1][0] + 60_000 < entry_ts - 60_000:
        return {"mint": mint, "status": "INACTIVE_AT_ENTRY", "created": created}  # brak handlu w minucie przed wejsciem
    entry = before[-1][1]
    after = [c for c in cs if c[0] + 60_000 > entry_ts and c[0] <= end_ts]

    def close_at(ts):
        p = [c[1] for c in cs if c[0] + 60_000 <= ts]
        return p[-1] if p else entry

    rets = {}
    for x in EXITS:
        if x <= horizon_min:
            px = close_at(entry_ts + x * 60_000)
            rets[x] = px / entry * (1 - COST) / (1 + COST) - 1
    dead_at = next((round((c[0] + 60_000 - entry_ts) / 60_000, 1) for c in after if c[2] <= DEAD_LEVEL * entry), None)
    last_trade = round((after[-1][0] - entry_ts) / 60_000 + 1, 1) if after else 0.0
    peak = max([c[3] for c in after], default=entry)
    peak_at = next((round((c[0] + 60_000 - entry_ts) / 60_000, 1) for c in after if c[3] == peak), 0.0)
    return {"mint": mint, "status": "OK", "created": created, "rets": rets, "dead_after_min": dead_at,
            "last_activity_min": last_trade, "peak_x": round(peak / entry, 3), "peak_after_min": peak_at}


def report(rows, entry_min, horizon_min):
    ok = [r for r in rows if r["status"] == "OK"]
    cnt = {}
    for r in rows:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    print(f"\ntokenow: {len(rows)}  {cnt}")
    if not ok:
        return
    print(f"WEJSCIE w {entry_min}. minucie (tylko tokeny z handlem w minucie przed wejsciem), koszt {COST:.0%}/strone\n")
    print(f"{'zamkniecie po':>14} {'zyskownych':>10} {'srednia':>8} {'mediana':>8} {'p75':>7}")
    best = None
    for x in EXITS:
        v = [r["rets"][x] for r in ok if x in r["rets"]]
        if not v:
            continue
        q = sorted(v)
        p75 = q[int(0.75 * (len(q) - 1))]
        m = st.mean(v)
        print(f"{str(x) + ' min':>14} {sum(a > 0 for a in v) / len(v):>10.0%} {m:>+8.1%} {st.median(v):>+8.1%} {p75:>+7.1%}")
        if best is None or m > best[1]:
            best = (x, m)
    dead = [r["dead_after_min"] for r in ok if r["dead_after_min"] is not None]
    print(f"\n'ubite' (cena <= {DEAD_LEVEL:.0%} ceny wejscia) w ciagu {horizon_min} min: {len(dead)}/{len(ok)} = {len(dead)/len(ok):.0%}")
    if dead:
        print(f"  czas do ubicia od wejscia: mediana {st.median(dead):.1f} min, srednia {st.mean(dead):.1f} min, "
              f"25% w ciagu {sorted(dead)[len(dead)//4]:.1f} min")
    act = [r["last_activity_min"] for r in ok]
    print(f"ostatnia aktywnosc (handel) po wejsciu: mediana {st.median(act):.1f} min; bez handlu po wejsciu: {sum(a == 0 for a in act)}")
    pk = [r["peak_after_min"] for r in ok if r["peak_x"] > 1.0]
    print(f"szczyt po wejsciu: {sum(r['peak_x'] > 1.0 for r in ok)}/{len(ok)} tokenow poszlo wyzej; "
          f"mediana czasu do szczytu {st.median(pk) if pk else 0:.1f} min; mediana wysokosci {st.median([r['peak_x'] for r in ok]):.2f}x")
    if best:
        print(f"\nnajlepsze stale zamkniecie wg sredniej: po {best[0]} min ({best[1]:+.1%}) - srednia ciagnieta przez nieliczne wygrane")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", default=str(ROOT / "paper_trading" / "signals_log.jsonl"))
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--entry-min", type=int, default=10)
    ap.add_argument("--horizon-min", type=int, default=60)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out")
    a = ap.parse_args()
    mints = list(load_mints(a.signals, a.hours).items())
    random.Random(a.seed).shuffle(mints)
    print(f"mintow w logu z ostatnich {a.hours} h: {len(mints)}; analizuje {min(a.n, len(mints))}")
    http = VerifiedHttpClient()
    rows = []
    for i, (m, c) in enumerate(mints[: a.n], 1):
        try:
            rows.append(analyze(http, m, c, a.entry_min, a.horizon_min))
        except Exception as e:  # noqa: BLE001
            rows.append({"mint": m, "status": f"ERROR {type(e).__name__}"})
        if i % 50 == 0:
            print(f"[{i}]", flush=True)
    report(rows, a.entry_min, a.horizon_min)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
