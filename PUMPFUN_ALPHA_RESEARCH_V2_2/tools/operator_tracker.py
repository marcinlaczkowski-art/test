"""
Operator tracker (READ-ONLY, bez prawdziwych transakcji).

Sledzi lancuch jednorazowych portfeli operatora (portfel -> nowy coin -> przelew calego salda na kolejny portfel)
i daje znac:
  * NOWY COIN    - gdy aktualny portfel operatora kupi/utworzy nowy token,
  * WCHODZIMY    - gdy token ma >= --buyers unikalnych kupujacych (bez portfeli operatora),
  * WYNIK        - papierowa pozycja: polowa przy 2x, reszta trailing stop 30% albo wyjscie po --max-hold s.

Alerty: konsola + alerts_operator.jsonl; opcjonalnie Telegram (zmienne TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID).
Stan (aktualne portfele lancucha) zapisywany w operator_state.json, wiec po restarcie sledzenie trwa dalej.

  python tools/operator_tracker.py --seed 3ZGMeoPo8V2UHt1AKfZUPRV7JDQUwAkVFdmaFFq2BiE1
  python tools/operator_tracker.py            # wznawia z operator_state.json
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID  # noqa: E402
from data_sources.http_client import VerifiedHttpClient  # noqa: E402

DEFAULT_RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
MIN_HOP_SOL = 3.0          # przelew >= tylu SOL z portfela operatora = przejscie na kolejny portfel
HEAD_TTL_S = 30 * 60       # brak aktywnosci calego lancucha tak dlugo -> ostrzezenie
COLLECTOR_TX = 40          # portfel z >= tyloma tx to nie jednorazowka, tylko portfel zbiorczy operatora
SUCCESSOR_GRACE_S = 120    # portfel z nastepca sledzimy jeszcze tyle sekund od jego ostatniej transakcji
WATCH_MAX_S = 15 * 60      # jak dlugo po starcie czekamy na prog kupujacych
COST = 0.03                # prowizja + poslizg na strone (zalozenie papierowe)
TRAIL = 0.30
TAKE_X = 2.0
WSOL = "So11111111111111111111111111111111111111112"


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


# ---------------------------------------------------------------- Solana RPC
class Rpc:
    def __init__(self, url):
        self.url = url

    def call(self, method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        for a in range(5):
            try:
                req = urllib.request.Request(self.url, body, {"Content-Type": "application/json", "User-Agent": "research-client"})
                r = json.load(urllib.request.urlopen(req, timeout=20))
                if "result" in r:
                    return r["result"]
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.5 * 2 ** a)
        return None

    def new_signatures(self, wallet, until=None):
        p = {"limit": 50}
        if until:
            p["until"] = until
        return self.call("getSignaturesForAddress", [wallet, p]) or []

    def tx(self, sig):
        return self.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])


def parse_tx(tx, wallet):
    """-> (hops: [(dest, sol)], mints_bought: [mint]) dla transakcji portfela operatora."""
    if not tx or (tx.get("meta") or {}).get("err"):
        return [], []
    hops = []
    for ins in tx["transaction"]["message"]["instructions"]:
        p = ins.get("parsed")
        if isinstance(p, dict) and p.get("type") == "transfer" and "lamports" in p.get("info", {}):
            info = p["info"]
            if info.get("source") == wallet and info["lamports"] / 1e9 >= MIN_HOP_SOL:
                hops.append((info["destination"], info["lamports"] / 1e9))
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    mints = []
    if keys and keys[0] == wallet:
        bal = {}
        for b in tx["meta"].get("postTokenBalances") or []:
            if b.get("owner") == wallet:
                bal[b["mint"]] = bal.get(b["mint"], 0.0) + float(b["uiTokenAmount"]["uiAmount"] or 0)
        for b in tx["meta"].get("preTokenBalances") or []:
            if b.get("owner") == wallet:
                bal[b["mint"]] = bal.get(b["mint"], 0.0) - float(b["uiTokenAmount"]["uiAmount"] or 0)
        mints = [m for m, v in bal.items() if v > 0 and m != WSOL]
    return hops, mints


# ---------------------------------------------------------------- alerts
class Alerts:
    def __init__(self, path):
        self.path = path
        self.tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
        self.recent = []
        if Path(path).exists():  # historia alertow po restarcie
            for line in Path(path).read_text(encoding="utf-8").splitlines()[-100:]:
                try:
                    self.recent.insert(0, json.loads(line))
                except json.JSONDecodeError:
                    pass

    def send(self, kind, text, **data):
        log(f"[{kind}] {text}")
        self.recent = ([{"ts": int(time.time() * 1000), "kind": kind, "text": text, **data}] + self.recent)[:100]
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time() * 1000), "kind": kind, "text": text, **data}) + "\n")
        if self.tg_token and self.tg_chat:
            try:
                q = urllib.parse.urlencode({"chat_id": self.tg_chat, "text": f"[{kind}] {text}",
                                            "disable_web_page_preview": "true"}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{self.tg_token}/sendMessage", q, timeout=10)
            except Exception as e:  # noqa: BLE001
                log(f"telegram blad: {e}")


# ---------------------------------------------------------------- tracker
class Tracker:
    def __init__(self, state_path, alerts, rpc, http, buyers_needed, max_hold_s):
        self.state_path = state_path
        self.alerts, self.rpc, self.http = alerts, rpc, http
        self.buyers_needed, self.max_hold_s = buyers_needed, max_hold_s
        self.base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
        self.st = {"heads": {}, "operator_wallets": [], "tokens": {}}
        if state_path.exists():
            self.st = json.loads(state_path.read_text(encoding="utf-8"))

    def save(self):
        self.state_path.write_text(json.dumps(self.st, indent=1), encoding="utf-8")
        # podsumowanie dla dashboardu /live.html
        toks = [{"mint": m, **t} for m, t in self.st["tokens"].items() if t["status"] != "OLD"]
        toks.sort(key=lambda t: -(t.get("seen_ts") or 0))
        done = [t["result"] for t in toks if t.get("status") == "DONE"]
        summ = {"updated_at_ms": int(time.time() * 1000), "buyers_needed": self.buyers_needed,
                "heads": [{"wallet": w, **h} for w, h in self.st["heads"].items()],
                "operator_wallets_n": len(self.st["operator_wallets"]),
                "tokens": toks[:200], "closed_n": len(done),
                "avg_result": round(sum(done) / len(done), 4) if done else None,
                "win_rate": round(sum(r > 0 for r in done) / len(done), 3) if done else None,
                "alerts": self.alerts.recent[:50]}
        p = self.state_path.parent / "operator_summary.json"
        p.with_suffix(".tmp").write_text(json.dumps(summ), encoding="utf-8")
        os.replace(p.with_suffix(".tmp"), p)

    def add_head(self, wallet, parent=None):
        if wallet in self.st["heads"]:
            return
        sigs = self.rpc.new_signatures(wallet)
        if len(sigs) >= COLLECTOR_TX:
            # Portfel zbiorczy: nie przetwarzamy historii, tylko czekamy na nowe przelewy (start nowego lancucha).
            self.st["heads"][wallet] = {"last_sig": sigs[0]["signature"], "last_activity": time.time(),
                                        "parent": parent, "successor": None, "collector": True}
            self.alerts.send("ZBIORCZY", f"lancuch trafil do portfela zbiorczego {wallet} - czekam na nowy lancuch",
                             wallet=wallet)
            return
        # przy dodaniu: przetwarzamy cala (krotka) historie nowego portfela, zeby nie przegapic coina
        self.st["heads"][wallet] = {"last_sig": None, "last_activity": time.time(), "parent": parent,
                                    "successor": None}
        if wallet not in self.st["operator_wallets"]:
            self.st["operator_wallets"].append(wallet)
        log(f"sledze portfel {wallet} (tx w historii: {len(sigs)})")

    def poll_heads(self):
        for w, h in list(self.st["heads"].items()):
            sigs = self.rpc.new_signatures(w, h["last_sig"])
            if sigs:
                h["last_sig"] = sigs[0]["signature"]
                h["last_activity"] = sigs[0].get("blockTime") or time.time()
            # Nadrabianie: gdy wszystkie nowe transakcje sa stare, szukamy tylko przejscia (od najnowszej) i pomijamy reszte.
            catch_up = bool(sigs) and time.time() - (sigs[0].get("blockTime") or time.time()) > WATCH_MAX_S
            order = sigs if catch_up else list(reversed(sigs))
            for s in order:
                hops, mints = parse_tx(self.rpc.tx(s["signature"]), w)
                time.sleep(0.2)
                if catch_up and not hops:
                    continue
                for m in mints:
                    self.new_token(m, w, s.get("blockTime") or time.time())
                for dest, sol in hops:
                    if dest not in self.st["heads"]:
                        h["successor"] = dest
                        log(f"przejscie {w[:6]}.. -> {dest[:6]}.. ({sol:.1f} SOL)")
                        self.add_head(dest, parent=w)
                if catch_up and hops:
                    break
            if h.get("successor") and not h.get("collector") and time.time() - h["last_activity"] > SUCCESSOR_GRACE_S:
                del self.st["heads"][w]
        burners = [h for h in self.st["heads"].values() if not h.get("collector")]
        if burners and all(time.time() - h["last_activity"] > HEAD_TTL_S for h in burners):
            log("UWAGA: zaden portfel operatora nie byl aktywny od 30 min - mogl zmienic lancuch")

    def new_token(self, mint, wallet, ts):
        if mint in self.st["tokens"]:
            return
        if time.time() - ts > WATCH_MAX_S:  # stary coin z historii portfela - tylko zapis, bez alertu
            self.st["tokens"][mint] = {"wallet": wallet, "seen_ts": ts, "status": "OLD"}
            return
        self.st["tokens"][mint] = {"wallet": wallet, "seen_ts": ts, "status": "WATCH"}
        self.alerts.send("NOWY COIN", f"operator {wallet[:6]}.. kupil {mint}  https://pump.fun/coin/{mint}  "
                         f"- czekam na {self.buyers_needed} kupujacych", mint=mint, wallet=wallet)

    def trades(self, mint):
        out, after = [], 0
        for _ in range(10):
            r = self.http.request_json("pumpfun_v3", f"{self.base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{after}")
            page = (r.get("data") or {}).get("trades") or [] if r.get("ok") else []
            out += page
            if len(page) < 100:
                break
            after = int(page[-1]["blockTimeMs"])
            time.sleep(0.25)
        return out

    @staticmethod
    def price(t):
        try:
            return float(t.get("priceUsd") or 0)
        except (TypeError, ValueError):
            return 0.0

    def poll_tokens(self):
        op = set(self.st["operator_wallets"])
        now = time.time()
        for mint, t in self.st["tokens"].items():
            if t["status"] not in ("WATCH", "IN", "HALF"):
                continue
            tr = self.trades(mint)
            if not tr:
                continue
            px = [self.price(x) for x in tr if self.price(x) > 0]
            last = px[-1] if px else 0
            if t["status"] == "WATCH":
                buyers = {(x.get("trader") or {}).get("address") for x in tr if x.get("side") == "buy"} - op
                t0 = int(tr[0]["blockTimeMs"]) / 1000
                t["buyers"] = len(buyers)
                if now - t0 > WATCH_MAX_S:
                    t["status"] = "SKIP"
                    log(f"{mint[:8]}.. pominiety: {len(buyers)} kupujacych, minelo {WATCH_MAX_S // 60} min")
                elif len(buyers) >= self.buyers_needed and last > 0:
                    t.update(status="IN", entry=last, peak=last, entry_ts=now, realized=0.0, left=1.0)
                    self.alerts.send("WCHODZIMY", f"{mint}: {len(buyers)} kupujacych po {now - t0:.0f}s, "
                                     f"cena {last:.3g} USD (papierowo)  https://pump.fun/coin/{mint}", mint=mint)
                continue
            # papierowa pozycja
            t["peak"] = max(t["peak"], last)
            net = last / t["entry"] * (1 - COST) / (1 + COST)
            if t["status"] == "IN" and last >= TAKE_X * t["entry"]:
                t["realized"] += 0.5 * net
                t["left"] = 0.5
                t["status"] = "HALF"
                self.alerts.send("POLOWA", f"{mint[:8]}.. 2x - sprzedaj polowe (papierowo)", mint=mint)
            if last <= t["peak"] * (1 - TRAIL) or now - t["entry_ts"] >= self.max_hold_s:
                res = t["realized"] + t["left"] * net - 1
                t.update(status="DONE", result=round(res, 4))
                why = "trailing stop" if last <= t["peak"] * (1 - TRAIL) else f"limit {self.max_hold_s}s"
                done = [x["result"] for x in self.st["tokens"].values() if x.get("status") == "DONE"]
                self.alerts.send("WYNIK", f"{mint[:8]}.. wyjscie ({why}): {res:+.0%}; szczyt {t['peak'] / t['entry']:.1f}x; "
                                 f"lacznie {len(done)} pozycji, srednio {sum(done) / len(done):+.0%}", mint=mint, result=res)
            time.sleep(0.25)

    def run(self, interval):
        while True:
            try:
                self.poll_heads()
                self.poll_tokens()
                self.save()
            except Exception as e:  # noqa: BLE001
                log(f"blad cyklu: {type(e).__name__}: {e}")
            time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", nargs="*", default=[], help="portfel(e) operatora, od ktorych zaczac")
    ap.add_argument("--buyers", type=int, default=40)
    ap.add_argument("--max-hold", type=int, default=300, help="maks. czas papierowej pozycji (s)")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--dir", default=os.environ.get("V2_2_PAPER_DIR", str(ROOT / "paper_trading")))
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    a = ap.parse_args()
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    tr = Tracker(d / "operator_state.json", Alerts(d / "alerts_operator.jsonl"), Rpc(a.rpc), VerifiedHttpClient(),
                 a.buyers, a.max_hold)
    for w in a.seed:
        tr.add_head(w)
    if not tr.st["heads"]:
        sys.exit("brak portfeli do sledzenia: podaj --seed")
    log(f"start: sledze {len(tr.st['heads'])} portfel(e), prog {a.buyers} kupujacych, RPC {a.rpc}")
    tr.run(a.interval)


if __name__ == "__main__":
    main()
