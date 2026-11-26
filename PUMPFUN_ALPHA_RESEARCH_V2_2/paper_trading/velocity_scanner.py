"""
Velocity scanner (READ-ONLY, tylko papier - zadnych prawdziwych transakcji).

Regula wejscia (sprawdzana raz, gdy token ma >= --window s):
  * >= --buyers unikalnych kupujacych w pierwszych --window s (bez tworcy),
  * tworca NIE sprzedal >= 90% swojego zakupu w pierwszych 20 s (wzorzec "kup w sekundzie 0, zrzuc po 3 s"),
  * tworca nie jest portfelem sledzonego operatora (operator_state.json z tools/operator_tracker.py).
Wejscie po aktualnej cenie w chwili wykrycia (nie po cenie z 60. sekundy).
Wyjscie: polowa przy 2x, reszta trailing stop 30% od szczytu albo po --max-hold s. Koszt 3% na strone.

Wyniki: velocity_events.jsonl (append-only) i velocity_summary.json (dla dashboardu /live.html).

  python paper_trading/velocity_scanner.py --dir /data/paper
"""
import argparse
import json
import os
import statistics as st
import sys
import time
from collections import OrderedDict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID  # noqa: E402
from data_sources.http_client import VerifiedHttpClient  # noqa: E402

COST = 0.03
DUMP_WINDOW_S = 20
DUMP_SHARE = 0.90
LATE_S = 180            # token sprawdzony pozniej niz window+LATE_S -> pomijamy (za pozno na wejscie)


def now_ms():
    return int(time.time() * 1000)


def price_of(t):
    try:
        return float(t.get("priceUsd") or 0)
    except (TypeError, ValueError):
        return 0.0


def base_amt(t):
    b = t.get("baseAmount") or {}
    try:
        return int(b.get("raw") or 0) / 10 ** int(b.get("decimals") or 6)
    except (TypeError, ValueError):
        return 0.0


def evaluate_rule(trades, created_ms, creator, window_s, buyers_needed, operator_wallets=()):
    """-> (passed: bool, reason: str, stats: dict). Uzywa tylko transakcji z pierwszych window_s sekund."""
    win = [t for t in trades if int(t["blockTimeMs"]) <= created_ms + window_s * 1000]
    addr = lambda t: (t.get("trader") or {}).get("address")  # noqa: E731
    buyers = {addr(t) for t in win if t.get("side") == "buy"} - {creator}
    cb = sum(base_amt(t) for t in win if addr(t) == creator and t.get("side") == "buy")
    cs = sum(base_amt(t) for t in win if addr(t) == creator and t.get("side") == "sell"
             and int(t["blockTimeMs"]) <= created_ms + DUMP_WINDOW_S * 1000)
    stats = {"buyers": len(buyers), "trades_in_window": len(win),
             "creator_sold_share_20s": round(cs / cb, 3) if cb else 0.0}
    if creator in set(operator_wallets):
        return False, "OPERATOR", stats
    if cb and cs >= DUMP_SHARE * cb:
        return False, "CREATOR_DUMP_20S", stats
    if len(buyers) < buyers_needed:
        return False, "FEW_BUYERS", stats
    return True, "PASS", stats


def step_position(pos, price, ts_ms, take_x, trail, max_hold_s):
    """Aktualizuje papierowa pozycje jedna cena. Zwraca liste zdarzen ('HALF' / 'EXIT')."""
    ev = []
    if price <= 0 or pos["status"] == "CLOSED":
        return ev
    pos["last"] = price
    pos["peak"] = max(pos["peak"], price)
    net = price / pos["entry"] * (1 - COST) / (1 + COST)
    if not pos["half"] and price >= take_x * pos["entry"]:
        pos["half"] = True
        pos["realized"] += 0.5 * net
        pos["left"] = 0.5
        ev.append("HALF")
    why = None
    if price <= pos["peak"] * (1 - trail):
        why = "TRAILING_STOP"
    elif ts_ms - pos["entry_ts"] >= max_hold_s * 1000:
        why = "MAX_HOLD"
    if why:
        pos["status"] = "CLOSED"
        pos["exit_reason"] = why
        pos["exit_ts"] = ts_ms
        pos["result"] = round(pos["realized"] + pos["left"] * net - 1, 4)
        ev.append("EXIT")
    return ev


class VelocityScanner:
    def __init__(self, storage_dir, http, buyers=40, window_s=60, max_hold_s=900, take_x=2.0, trail=0.30):
        self.dir = Path(storage_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "velocity_events.jsonl"
        self.summary_path = self.dir / "velocity_summary.json"
        self.op_state = self.dir / "operator_state.json"
        self.http = http
        self.base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
        self.buyers, self.window_s, self.max_hold_s, self.take_x, self.trail = buyers, window_s, max_hold_s, take_x, trail
        self.pending = OrderedDict()          # mint -> coin
        self.seen = OrderedDict()             # mint -> None (ograniczony)
        self.open = {}                        # mint -> pos
        self.closed = deque(maxlen=500)
        self.recent_checks = deque(maxlen=60)
        self.counts = {"scanned": 0, "PASS": 0, "FEW_BUYERS": 0, "CREATOR_DUMP_20S": 0, "OPERATOR": 0, "LATE": 0,
                       "NO_DATA": 0}
        self.started = now_ms()
        self.operator_wallets, self._op_loaded = set(), 0
        self._rehydrate()

    # ------------------------------------------------------------ persistence
    def _log(self, rec):
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _rehydrate(self):
        if not self.events_path.exists():
            return
        with open(self.events_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = r.get("event")
                if k == "COUNTS":
                    self.counts.update(r["counts"])
                    self.started = r.get("started", self.started)
                elif k == "ENTRY":
                    self.open[r["mint"]] = r["pos"]
                elif k in ("HALF", "EXIT") and r["mint"] in self.open:
                    self.open[r["mint"]] = r["pos"]
                    if k == "EXIT":
                        self.closed.append(self.open.pop(r["mint"]))
        for m in list(self.open) + [p["mint"] for p in self.closed]:
            self.seen[m] = None

    def _operator_wallets(self):
        if time.time() - self._op_loaded > 60 and self.op_state.exists():
            try:
                self.operator_wallets = set(json.loads(self.op_state.read_text(encoding="utf-8")).get("operator_wallets", []))
            except (OSError, json.JSONDecodeError):
                pass
            self._op_loaded = time.time()
        return self.operator_wallets

    # ------------------------------------------------------------ data
    def _get(self, url):
        time.sleep(0.15)
        r = self.http.request_json("pumpfun_v3", url)
        return r["data"] if r.get("ok") else None

    def trades_after(self, mint, after_ms, max_pages=5):
        out, after = [], max(0, after_ms)
        for _ in range(max_pages):
            d = self._get(f"{self.base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{after}")
            if d is None:
                return None if not out else out
            page = d.get("trades") or []
            out += page
            if len(page) < 100:
                break
            after = int(page[-1]["blockTimeMs"])
        return out

    # ------------------------------------------------------------ loop steps
    def poll_new(self):
        d = self._get(f"{self.base}/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true")
        for c in d if isinstance(d, list) else []:
            m = c.get("mint")
            if m and m not in self.seen:
                self.seen[m] = None
                self.pending[m] = c
        while len(self.seen) > 20000:
            self.seen.popitem(last=False)

    def evaluate_due(self):
        t = now_ms()
        for m, c in list(self.pending.items()):
            cts = int(c.get("created_timestamp") or 0)
            age = (t - cts) / 1000
            if age < self.window_s:
                continue
            del self.pending[m]
            self.counts["scanned"] += 1
            if age > self.window_s + LATE_S:
                self.counts["LATE"] += 1
                continue
            tr = self.trades_after(m, cts - 5000)
            if not tr:
                self.counts["NO_DATA"] += 1
                continue
            ok, reason, stats = evaluate_rule(tr, cts, c.get("creator"), self.window_s, self.buyers, self._operator_wallets())
            self.counts[reason] += 1
            chk = {"mint": m, "symbol": c.get("symbol"), "creator": c.get("creator"), "reason": reason,
                   "age_s": round(age), **stats}
            self.recent_checks.append(chk)
            if ok:
                px = [price_of(x) for x in tr if price_of(x) > 0]
                if not px:
                    continue
                last_ts = int(tr[-1]["blockTimeMs"])
                pos = {"mint": m, "symbol": c.get("symbol"), "creator": c.get("creator"), "created_ms": cts,
                       "entry_ts": t, "entry_age_s": round(age), "entry": px[-1], "peak": px[-1], "last": px[-1],
                       "half": False, "realized": 0.0, "left": 1.0, "status": "OPEN", "last_trade_ts": last_ts, **stats}
                self.open[m] = pos
                self._log({"event": "ENTRY", "ts": t, "mint": m, "pos": pos})
                print(f"[WEJSCIE papier] {c.get('symbol')} {stats['buyers']} kupujacych w {self.window_s}s "
                      f"https://pump.fun/coin/{m}", flush=True)

    def update_positions(self):
        for m, pos in list(self.open.items()):
            tr = self.trades_after(m, pos["last_trade_ts"], max_pages=3) or []
            events = []
            for x in tr:
                ts = int(x["blockTimeMs"])
                pos["last_trade_ts"] = max(pos["last_trade_ts"], ts)
                if ts < pos["entry_ts"]:
                    continue
                for e in step_position(pos, price_of(x), ts, self.take_x, self.trail, self.max_hold_s):
                    events.append(e)
                if pos["status"] == "CLOSED":
                    break
            if pos["status"] != "CLOSED" and now_ms() - pos["entry_ts"] >= self.max_hold_s * 1000:
                events += step_position(pos, pos["last"], now_ms(), self.take_x, self.trail, self.max_hold_s)
            for e in events:
                self._log({"event": e, "ts": now_ms(), "mint": m, "pos": pos})
            if pos["status"] == "CLOSED":
                self.closed.append(self.open.pop(m))
                print(f"[WYNIK papier] {pos['symbol']} {pos['result']:+.0%} ({pos['exit_reason']})", flush=True)

    def write_summary(self):
        res = [p["result"] for p in self.closed]
        summ = {
            "updated_at_ms": now_ms(), "started_ms": self.started,
            "rule": {"buyers": self.buyers, "window_s": self.window_s, "take_x": self.take_x, "trail": self.trail,
                     "max_hold_s": self.max_hold_s, "cost_per_side": COST},
            "counts": self.counts, "pending": len(self.pending),
            "closed_n": len(res),
            "win_rate": round(sum(r > 0 for r in res) / len(res), 3) if res else None,
            "avg_result": round(st.mean(res), 4) if res else None,
            "median_result": round(st.median(res), 4) if res else None,
            "sum_result_units": round(sum(res), 3) if res else 0,
            "open": [{**p, "x_now": round(p["last"] / p["entry"], 3), "x_peak": round(p["peak"] / p["entry"], 3)}
                     for p in self.open.values()],
            "closed": [{**p, "x_peak": round(p["peak"] / p["entry"], 3)} for p in list(self.closed)[-100:]][::-1],
            "recent_checks": list(self.recent_checks)[::-1],
        }
        tmp = self.summary_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(summ), encoding="utf-8")
        os.replace(tmp, self.summary_path)

    def run(self, interval=5.0):
        last_counts = 0
        while True:
            try:
                self.poll_new()
                self.evaluate_due()
                self.update_positions()
                self.write_summary()
                if time.time() - last_counts > 300:
                    self._log({"event": "COUNTS", "ts": now_ms(), "counts": self.counts, "started": self.started})
                    last_counts = time.time()
            except Exception as e:  # noqa: BLE001
                print(f"blad cyklu: {type(e).__name__}: {e}", flush=True)
            time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("V2_2_PAPER_DIR", str(ROOT / "paper_trading")))
    ap.add_argument("--buyers", type=int, default=40)
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--max-hold", type=int, default=900)
    ap.add_argument("--interval", type=float, default=5.0)
    a = ap.parse_args()
    sc = VelocityScanner(a.dir, VerifiedHttpClient(), buyers=a.buyers, window_s=a.window, max_hold_s=a.max_hold)
    print(f"Velocity scanner (papier): >= {a.buyers} kupujacych w {a.window}s, dir={a.dir}", flush=True)
    sc.run(a.interval)


if __name__ == "__main__":
    main()
