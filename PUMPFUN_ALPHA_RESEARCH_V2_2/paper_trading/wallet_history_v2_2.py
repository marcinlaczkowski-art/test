"""
Live wallet-history feed for H2/H3 in paper trading (READ-ONLY, no transactions).

Without this, the paper daemon starts an empty `WalletIntelligenceEngineV22` and never calls
`register_completed_token_outcomes`, so H2 (wallet groups) and H3 (smart money) can never score.

What it does (same semantics as the OOT engine):
  1. On the FIRST live evaluation of a mint, store a compact observation at the decision cutoff:
     early buyers' FIFO state, active clusters, reference price (USD of the last trade <= cutoff).
  2. Once `cutoff + 4h` has passed in real time, fetch 1m candles and compute `hit_2x_4h`
     (max high in (cutoff, cutoff+4h] >= 2x reference price), append the outcome, and register it with
     `outcome_known_at_ms = cutoff + 4h`. The scorer only reads outcomes with
     `outcome_known_at_ms <= query cutoff`, so there is no look-ahead.
  3. Everything is append-only JSONL under the paper dir, so history survives restarts (rehydrated on start).
  4. Memory is bounded: only the newest `max_tracked_tokens` resolved tokens (and nothing older than
     `retention_days`) are kept in the engine (~18 MB per 1k tokens measured), pruned hourly and on rehydrate.
"""
import json
import time
from collections import deque
from pathlib import Path
from typing import Optional

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID, INTERVAL_MS

FOUR_H_MS = INTERVAL_MS["4h"]
FIFO_FIELDS = ("first_buy_ts_ms", "pnl_classification", "realized_pnl_sol", "unrealized_pnl_sol", "average_holding_time_sec")


class WalletHistoryRecorder:
    def __init__(
        self,
        storage_dir: Path,
        wallet_engine,
        http=None,
        retention_days: float = 2.0,
        max_tracked_tokens: int = 10_000,
        min_early_buyers: int = 3,
        max_resolve_per_cycle: int = 25,
        abandon_after_ms: int = 4 * 3600_000,
        prune_every_sec: float = 3600.0,
    ):
        self.wallets = wallet_engine
        self.http = http
        self.retention_ms = int(retention_days * 86_400_000)
        self.min_early_buyers = min_early_buyers
        self.max_tracked_tokens = max_tracked_tokens
        self.registered = deque()  # (signal_ts_ms, mint) of tokens whose history is in the engine
        self.max_resolve_per_cycle = max_resolve_per_cycle
        self.abandon_after_ms = abandon_after_ms
        self.prune_every_sec = prune_every_sec
        self._last_prune = 0.0
        self.obs_log = Path(storage_dir) / "wallet_obs_log.jsonl"
        self.outcomes_log = Path(storage_dir) / "wallet_outcomes_log.jsonl"
        self.pending: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.stats = {"observed": 0, "resolved": 0, "abandoned": 0, "rehydrated_outcomes": 0}
        self._rehydrate()

    # ------------------------------------------------------------------ io
    @staticmethod
    def _append(path: Path, rec: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def _stream(path: Path):
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a torn last line after a crash must not kill the daemon

    def _rehydrate(self) -> None:
        now = int(time.time() * 1000)
        horizon = now - self.retention_ms - FOUR_H_MS
        outcomes = {r["mint"]: r for r in self._stream(self.outcomes_log)}
        resolved = deque(maxlen=self.max_tracked_tokens)
        for obs in self._stream(self.obs_log):
            mint = obs["mint"]
            if obs["signal_ts_ms"] < horizon:
                continue
            self.seen.add(mint)
            out = outcomes.get(mint)
            if out is None:
                self.pending[mint] = obs
            elif out.get("hit_2x_4h") in (0, 1):
                resolved.append((obs, out["hit_2x_4h"]))
        for obs, hit in resolved:
            self._register(obs, hit)
            self.stats["rehydrated_outcomes"] += 1

    # ------------------------------------------------------------- record
    def record_observation(self, snap: dict, trades: list, cutoff_ts_ms: int) -> bool:
        """Call once per live evaluation; only the first valid observation of a mint is stored."""
        mint = str(snap.get("token_mint") or "")
        env = snap.get("envelope") or {}
        if not mint or mint in self.seen or env.get("temporal_status") != "VALID":
            return False
        fifo = (snap.get("_fifo_internal") or {}).get("wallets_fifo") or {}
        early = {
            w: {k: wf.get(k) for k in FIFO_FIELDS}
            for w, wf in fifo.items()
            if wf.get("first_buy_ts_ms") is not None and wf["first_buy_ts_ms"] <= cutoff_ts_ms
        }
        if len(early) < self.min_early_buyers:
            return False
        early = dict(sorted(early.items(), key=lambda kv: kv[1]["first_buy_ts_ms"])[:20])
        ref = 0.0
        for t in trades or []:
            if int(t.get("blockTimeMs") or 0) <= cutoff_ts_ms:
                try:
                    ref = float(t.get("priceUsd") or 0) or ref
                except (TypeError, ValueError):
                    pass
        if ref <= 0:
            return False
        clusters = [
            {"cluster_id": c["cluster_id"], "wallets": list(c.get("wallets") or []), "first_buy_ts_ms": c["first_buy_ts_ms"]}
            for c in ((snap.get("_wi_obs_internal") or {}).get("active_clusters") or [])
        ]
        obs = {
            "mint": mint,
            "created_ts_ms": int(snap.get("created_timestamp_ms") or 0),
            "signal_ts_ms": int(cutoff_ts_ms),
            "ref_price_usd": ref,
            "early_fifo": early,
            "clusters": clusters,
        }
        self._append(self.obs_log, obs)
        self.seen.add(mint)
        self.pending[mint] = obs
        self.stats["observed"] += 1
        return True

    # ------------------------------------------------------------ resolve
    def _fetch_max_high(self, mint: str, start_ms: int, end_ms: int) -> Optional[float]:
        base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
        r = self.http.request_json("pumpfun_v3", f"{base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={end_ms + 60_000}")
        if not r.get("ok"):
            return None
        highs = [
            float(c.get("high") or 0)
            for c in ((r.get("data") or {}).get("candles") or [])
            if start_ms < int(c.get("openTimeMs") or 0) + 60_000 and int(c.get("openTimeMs") or 0) <= end_ms
        ]
        return max(highs) if highs else 0.0

    def resolve_due(self, now_ms: Optional[int] = None) -> int:
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        due = sorted((o for o in self.pending.values() if now_ms >= o["signal_ts_ms"] + FOUR_H_MS),
                     key=lambda o: o["signal_ts_ms"])[: self.max_resolve_per_cycle]
        done = 0
        for obs in due:
            known_at = obs["signal_ts_ms"] + FOUR_H_MS
            mx = self._fetch_max_high(obs["mint"], obs["signal_ts_ms"], known_at) if self.http else None
            if mx is None:
                if now_ms > known_at + self.abandon_after_ms:
                    self._append(self.outcomes_log, {"mint": obs["mint"], "hit_2x_4h": None, "reason": "SOURCE_UNAVAILABLE",
                                                     "outcome_known_at_ms": known_at, "resolved_at_ms": now_ms})
                    self.pending.pop(obs["mint"], None)
                    self.stats["abandoned"] += 1
                continue
            hit = int(mx >= 2.0 * obs["ref_price_usd"])
            self._append(self.outcomes_log, {"mint": obs["mint"], "hit_2x_4h": hit, "max_high_usd": mx,
                                             "outcome_known_at_ms": known_at, "resolved_at_ms": now_ms})
            self._register(obs, hit)
            self.pending.pop(obs["mint"], None)
            self.stats["resolved"] += 1
            done += 1
        if time.time() - self._last_prune >= self.prune_every_sec:
            self.prune(now_ms)
        return done

    def _register(self, obs: dict, hit: int) -> None:
        self.wallets.register_completed_token_outcomes(
            mint=obs["mint"],
            created_ts_ms=obs["created_ts_ms"],
            signal_ts_ms=obs["signal_ts_ms"],
            outcome_known_at_ms=obs["signal_ts_ms"] + FOUR_H_MS,
            hit_2x_4h=hit,
            pre_signal_obs={"active_clusters": obs["clusters"]},
            fifo_result={"wallets_fifo": obs["early_fifo"]},
        )
        self.registered.append((obs["signal_ts_ms"], obs["mint"]))

    # -------------------------------------------------------------- prune
    def prune(self, now_ms: Optional[int] = None) -> None:
        """Bound memory: drop engine history older than the retention window."""
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        lim = now_ms - self.retention_ms
        while self.registered and (self.registered[0][0] < lim or len(self.registered) > self.max_tracked_tokens):
            lim = max(lim, self.registered.popleft()[0] + 1)
        w = self.wallets
        for d, key in ((w.wallet_token_outcomes, "outcome_known_at_ms"), (w.cluster_token_outcomes, "outcome_known_at_ms")):
            for k in list(d.keys()):
                kept = [r for r in d[k] if r[key] >= lim]
                if kept:
                    d[k] = kept
                else:
                    del d[k]
        for k in list(w.pair_cobuys.keys()):
            kept = [e for e in w.pair_cobuys[k] if e[0] >= lim]
            if kept:
                w.pair_cobuys[k] = kept
            else:
                del w.pair_cobuys[k]
        for k in list(w.edges.keys()):
            e = w.edges[k]
            if e.get("relationship_type") in ("DIRECT_FUNDING",):
                continue  # static RPC graph, not live-derived
            if int(e.get("last_seen") or 0) < lim:
                del w.edges[k]
        if len(self.seen) > 500_000:  # hard cap; mints older than retention cannot reappear as new launches
            self.seen = set(self.pending)
        self._last_prune = time.time()
