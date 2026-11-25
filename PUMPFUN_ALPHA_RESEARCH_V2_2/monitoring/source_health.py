"""
SECTION 4.3 (P0 — SOURCE HEALTH MONITORING):
Tracks API availability, latency, error rates, HTTP 429 rate-limit usage, TLS versions,
data completeness, time since last valid response, and computes `source_health_status`:
  - `HEALTHY`
  - `DEGRADED`
  - `UNAVAILABLE`
  - `UNKNOWN`
"""
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import MONITORING_DIR, DATA_SOURCES_REGISTRY


class SourceHealthMonitor:
    def __init__(self):
        self.stats = {}
        for src_id, spec in DATA_SOURCES_REGISTRY.items():
            self.stats[src_id] = {
                "source_id": src_id,
                "base_url": spec["base_url"],
                "data_type": spec["data_type"],
                "requests_total": 0,
                "success_count": 0,
                "error_count": 0,
                "rate_limit_429_count": 0,
                "http_5xx_count": 0,
                "timeout_count": 0,
                "tls_error_count": 0,
                "json_error_count": 0,
                "consecutive_failures": 0,
                "circuit_state": "CLOSED",
                "circuit_opened_at_sec": 0.0,
                "latencies_ms": [],
                "last_success_ts_ms": None,
                "last_error": "",
                "negotiated_tls_version": "NOT_QUERIED_YET",
                "tls_cert_verified": True,
            }

    def record_outcome(
        self,
        source_id: str,
        ok: bool,
        latency_ms: float,
        status_code: Optional[int] = None,
        error_kind: str = "",
        error_msg: str = "",
        tls_version: Optional[str] = None,
    ) -> None:
        if source_id not in self.stats:
            self.stats[source_id] = {
                "source_id": source_id, "base_url": "", "data_type": "custom",
                "requests_total": 0, "success_count": 0, "error_count": 0,
                "rate_limit_429_count": 0, "http_5xx_count": 0, "timeout_count": 0,
                "tls_error_count": 0, "json_error_count": 0, "consecutive_failures": 0,
                "circuit_state": "CLOSED", "circuit_opened_at_sec": 0.0,
                "latencies_ms": [], "last_success_ts_ms": None, "last_error": "",
                "negotiated_tls_version": "UNKNOWN", "tls_cert_verified": True,
            }
        rec = self.stats[source_id]
        rec["requests_total"] += 1
        rec["latencies_ms"].append(round(float(latency_ms), 2))
        if len(rec["latencies_ms"]) > 500:
            rec["latencies_ms"] = rec["latencies_ms"][-500:]
        if tls_version:
            rec["negotiated_tls_version"] = tls_version

        spec = DATA_SOURCES_REGISTRY.get(source_id, {"circuit_breaker_threshold": 5})
        cb_thresh = int(spec.get("circuit_breaker_threshold", 5))

        if ok:
            rec["success_count"] += 1
            rec["consecutive_failures"] = 0
            rec["circuit_state"] = "CLOSED"
            rec["last_success_ts_ms"] = int(time.time() * 1000)
        else:
            rec["error_count"] += 1
            rec["consecutive_failures"] += 1
            rec["last_error"] = f"{error_kind}:{status_code or ''}:{error_msg}"[:160]
            if status_code == 429 or error_kind == "HTTP_429":
                rec["rate_limit_429_count"] += 1
            elif status_code and 500 <= status_code <= 599:
                rec["http_5xx_count"] += 1
            elif error_kind == "TIMEOUT":
                rec["timeout_count"] += 1
            elif error_kind == "TLS_ERROR":
                rec["tls_error_count"] += 1
            elif error_kind == "JSON_ERROR":
                rec["json_error_count"] += 1

            if rec["consecutive_failures"] >= cb_thresh or error_kind == "TLS_ERROR":
                rec["circuit_state"] = "OPEN"
                rec["circuit_opened_at_sec"] = time.time()

    def is_circuit_open(self, source_id: str) -> bool:
        rec = self.stats.get(source_id)
        if not rec or rec["circuit_state"] != "OPEN":
            return False
        cooldown = float(DATA_SOURCES_REGISTRY.get(source_id, {}).get("circuit_breaker_cooldown_sec", 20.0))
        if (time.time() - rec["circuit_opened_at_sec"]) >= cooldown:
            rec["circuit_state"] = "HALF_OPEN"
            return False
        return True

    def get_source_health_status(self, source_id: str) -> str:
        rec = self.stats.get(source_id)
        if not rec or rec["requests_total"] == 0:
            return "UNKNOWN"
        if rec["circuit_state"] == "OPEN" or rec["tls_error_count"] > 0:
            return "UNAVAILABLE"
        avail = rec["success_count"] / max(1, rec["requests_total"])
        if avail < 0.50:
            return "UNAVAILABLE"
        if avail < 0.90 or rec["consecutive_failures"] >= 2 or rec["rate_limit_429_count"] > max(3, 0.15 * rec["requests_total"]):
            return "DEGRADED"
        return "HEALTHY"

    def summary_report(self) -> dict:
        now_ms = int(time.time() * 1000)
        out = {}
        for sid, rec in self.stats.items():
            lats = rec["latencies_ms"]
            avail = round(100.0 * rec["success_count"] / max(1, rec["requests_total"]), 2) if rec["requests_total"] > 0 else None
            since_ok_ms = (now_ms - rec["last_success_ts_ms"]) if rec["last_success_ts_ms"] else None
            out[sid] = {
                "source_id": sid,
                "base_url": rec["base_url"],
                "data_type": rec["data_type"],
                "source_health_status": self.get_source_health_status(sid),
                "circuit_state": rec["circuit_state"],
                "tls_cert_verified": rec["tls_cert_verified"],
                "negotiated_tls_version": rec["negotiated_tls_version"],
                "requests_total": rec["requests_total"],
                "success_count": rec["success_count"],
                "error_count": rec["error_count"],
                "availability_pct": avail,
                "rate_limit_429_count": rec["rate_limit_429_count"],
                "http_5xx_count": rec["http_5xx_count"],
                "timeout_count": rec["timeout_count"],
                "tls_error_count": rec["tls_error_count"],
                "json_error_count": rec["json_error_count"],
                "p50_latency_ms": round(float(np.percentile(lats, 50)), 1) if lats else None,
                "p95_latency_ms": round(float(np.percentile(lats, 95)), 1) if lats else None,
                "ms_since_last_success": since_ok_ms,
                "last_error": rec["last_error"],
            }
        return out

    def persist(self, path: Optional[Path] = None) -> Path:
        p = path or (MONITORING_DIR / "source_health_snapshot.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.summary_report(), indent=2), encoding="utf-8")
        return p
