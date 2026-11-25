"""
SECTION 4 (P0 — STRICT TLS, RETRIES, EXPONENTIAL BACKOFF, JITTER & CIRCUIT BREAKER):
- STRICTLY ENFORCES X.509 certificate & hostname validation (`ssl.CERT_REQUIRED`, `check_hostname = True`,
  `TLSv1.2+` minimum). ZERO `verify=False`, ZERO `CERT_NONE`, ZERO `ssl=False`!
- Separate `connect_timeout` and `read_timeout` on every socket connection.
- Retries ONLY transient failures (`HTTP 429`, `500`, `502`, `503`, `504`, socket timeout, connection reset)
  with exponential backoff + random jitter. NEVER retries permanent errors (`400`, `401`, `403`, `404`) or TLS errors!
- Integrates with `SourceHealthMonitor` and enforces per-source concurrency semaphores, circuit breakers,
  and non-equivalent fallback tagging (`is_fallback_source`, `semantic_equivalence`).
"""
import hashlib
import http.client
import json
import random
import socket
import ssl
import threading
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional, Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import DATA_SOURCES_REGISTRY
from monitoring.source_health import SourceHealthMonitor

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
    "Connection": "close",
}

TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


def build_verified_tls_context() -> ssl.SSLContext:
    """Builds a strict TLS 1.2+ context with mandatory certificate and hostname verification."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise RuntimeError("CRITICAL SECURITY ERROR: TLS verification must be CERT_REQUIRED with check_hostname=True")
    return ctx


class VerifiedHttpClient:
    def __init__(self, health_monitor: Optional[SourceHealthMonitor] = None, transport_override=None):
        self.tls_context = build_verified_tls_context()
        self.health = health_monitor or SourceHealthMonitor()
        self._semaphores = {
            sid: threading.Semaphore(int(spec.get("max_concurrency", 3)))
            for sid, spec in DATA_SOURCES_REGISTRY.items()
        }
        self._dedup_cache: dict[str, tuple[float, dict]] = {}
        self._transport_override = transport_override  # Used strictly by unit tests to inject 429/500/SSL/Timeout faults

    def _execute_single_https(
        self,
        url: str,
        method: str,
        body_bytes: Optional[bytes],
        headers: dict,
        connect_timeout: float,
        read_timeout: float,
    ) -> tuple[int, bytes, str]:
        if self._transport_override is not None:
            return self._transport_override(url, method, body_bytes, headers, connect_timeout, read_timeout)

        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise ssl.SSLError(f"Only HTTPS scheme allowed, got: {parsed.scheme}")
        host = parsed.hostname
        port = parsed.port or 443
        path_q = parsed.path or "/"
        if parsed.query:
            path_q += "?" + parsed.query

        # Step 1: Explicit TCP connect with `connect_timeout`
        raw_sock = socket.create_connection((host, port), timeout=connect_timeout)
        try:
            # Step 2: Strict TLS handshake (`CERT_REQUIRED` + `server_hostname=host`)
            tls_sock = self.tls_context.wrap_socket(raw_sock, server_hostname=host)
            tls_ver = tls_sock.version() or "TLSv1.2+"
            # Step 3: Explicit socket read timeout (`read_timeout`)
            tls_sock.settimeout(read_timeout)

            conn = http.client.HTTPSConnection(host, port=port, timeout=read_timeout, context=self.tls_context)
            conn.sock = tls_sock
            conn.request(method, path_q, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            status = resp.status
            conn.close()
            return status, payload, tls_ver
        except Exception:
            try:
                raw_sock.close()
            except Exception:
                pass
            raise

    def request_json(
        self,
        source_id: str,
        url: str,
        method: str = "GET",
        json_body: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        dedup_ttl_sec: float = 0.0,
    ) -> dict:
        """
        Executes a verified HTTPS request and returns a rich provenance result:
        `{ok, data, status_code, acquired_at_ms, latency_ms, source_id, source_health_status, error_kind, error_message, is_fallback}`
        """
        spec = DATA_SOURCES_REGISTRY.get(source_id, {
            "connect_timeout_sec": 4.0,
            "read_timeout_sec": 8.0,
            "max_retries": 3,
        })
        if self.health.is_circuit_open(source_id):
            return {
                "ok": False,
                "data": None,
                "status_code": None,
                "acquired_at_ms": int(time.time() * 1000),
                "latency_ms": 0.0,
                "source_id": source_id,
                "source_health_status": self.health.get_source_health_status(source_id),
                "error_kind": "CIRCUIT_OPEN",
                "error_message": f"Circuit breaker OPEN for {source_id}",
                "is_fallback": False,
                "semantic_equivalence": "EXACT",
            }

        body_bytes = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        dedup_key = hashlib.sha256(f"{method}:{url}:{body_bytes or b''}".encode("utf-8")).hexdigest()
        if dedup_ttl_sec > 0 and dedup_key in self._dedup_cache:
            ts_cached, cached_resp = self._dedup_cache[dedup_key]
            if (time.time() - ts_cached) <= dedup_ttl_sec:
                return dict(cached_resp, deduplicated_hit=True)

        hdrs = dict(DEFAULT_HEADERS)
        if json_body is not None:
            hdrs["Content-Type"] = "application/json"
        if extra_headers:
            hdrs.update(extra_headers)

        conn_to = float(spec.get("connect_timeout_sec", 4.0))
        read_to = float(spec.get("read_timeout_sec", 8.0))
        max_retries = int(spec.get("max_retries", 3))
        sem = self._semaphores.setdefault(source_id, threading.Semaphore(3))

        last_err_kind = "UNKNOWN_ERROR"
        last_err_msg = ""
        last_status = None

        for attempt in range(max_retries + 1):
            t0 = time.time()
            with sem:
                try:
                    status, raw_bytes, tls_ver = self._execute_single_https(
                        url=url,
                        method=method,
                        body_bytes=body_bytes,
                        headers=hdrs,
                        connect_timeout=conn_to,
                        read_timeout=read_to,
                    )
                    acq_ms = int(time.time() * 1000)
                    lat_ms = round((time.time() - t0) * 1000.0, 2)
                    last_status = status

                    if status == 200:
                        try:
                            parsed_json = json.loads(raw_bytes.decode("utf-8"))
                        except Exception as je:
                            self.health.record_outcome(source_id, False, lat_ms, status, "JSON_ERROR", str(je), tls_ver)
                            return {
                                "ok": False, "data": None, "status_code": status,
                                "acquired_at_ms": acq_ms, "latency_ms": lat_ms,
                                "source_id": source_id,
                                "source_health_status": self.health.get_source_health_status(source_id),
                                "error_kind": "JSON_ERROR", "error_message": str(je),
                                "is_fallback": False, "semantic_equivalence": "EXACT",
                            }

                        self.health.record_outcome(source_id, True, lat_ms, 200, "", "", tls_ver)
                        out = {
                            "ok": True,
                            "data": parsed_json,
                            "status_code": 200,
                            "acquired_at_ms": acq_ms,
                            "latency_ms": lat_ms,
                            "source_id": source_id,
                            "source_health_status": self.health.get_source_health_status(source_id),
                            "tls_version": tls_ver,
                            "error_kind": "",
                            "error_message": "",
                            "is_fallback": False,
                            "semantic_equivalence": "EXACT",
                        }
                        if dedup_ttl_sec > 0:
                            self._dedup_cache[dedup_key] = (time.time(), out)
                        return out

                    # Non-200 HTTP response
                    err_k = "HTTP_429" if status == 429 else (f"HTTP_{status}")
                    self.health.record_outcome(source_id, False, lat_ms, status, err_k, f"HTTP {status}", tls_ver)
                    last_err_kind = err_k
                    last_err_msg = f"HTTP status {status}"

                    # Permanent client errors (400, 401, 403, 404) MUST NOT be retried!
                    if status not in TRANSIENT_HTTP_CODES:
                        break

                except ssl.SSLError as se:
                    lat_ms = round((time.time() - t0) * 1000.0, 2)
                    self.health.record_outcome(source_id, False, lat_ms, None, "TLS_ERROR", str(se))
                    # NEVER bypass or retry TLS certificate errors!
                    return {
                        "ok": False, "data": None, "status_code": None,
                        "acquired_at_ms": int(time.time() * 1000), "latency_ms": lat_ms,
                        "source_id": source_id,
                        "source_health_status": self.health.get_source_health_status(source_id),
                        "error_kind": "TLS_ERROR", "error_message": str(se),
                        "is_fallback": False, "semantic_equivalence": "EXACT",
                    }
                except (socket.timeout, TimeoutError) as te:
                    lat_ms = round((time.time() - t0) * 1000.0, 2)
                    self.health.record_outcome(source_id, False, lat_ms, None, "TIMEOUT", str(te))
                    last_err_kind = "TIMEOUT"
                    last_err_msg = str(te)
                except OSError as oe:
                    lat_ms = round((time.time() - t0) * 1000.0, 2)
                    self.health.record_outcome(source_id, False, lat_ms, None, "CONNECTION_ERROR", str(oe))
                    last_err_kind = "CONNECTION_ERROR"
                    last_err_msg = str(oe)

            if attempt < max_retries and not self.health.is_circuit_open(source_id):
                # Exponential backoff + random jitter
                base = 0.8 if last_status == 429 else 0.4
                sleep_s = min(6.0, base * (2 ** attempt) + random.uniform(0.05, 0.30))
                time.sleep(sleep_s)
            else:
                break

        return {
            "ok": False,
            "data": None,
            "status_code": last_status,
            "acquired_at_ms": int(time.time() * 1000),
            "latency_ms": 0.0,
            "source_id": source_id,
            "source_health_status": self.health.get_source_health_status(source_id),
            "error_kind": last_err_kind,
            "error_message": last_err_msg,
            "is_fallback": False,
            "semantic_equivalence": "EXACT",
        }

    def solana_rpc_call(self, method: str, params: list, allow_fallback: bool = True) -> dict:
        """
        Calls verified primary Solana RPC (`solana_rpc_publicnode`), falling back to verified
        `solana_rpc_mainnet_official` ONLY on outage while explicitly recording fallback provenance.
        """
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        res = self.request_json(
            source_id="solana_rpc_publicnode",
            url=DATA_SOURCES_REGISTRY["solana_rpc_publicnode"]["base_url"],
            method="POST",
            json_body=payload,
        )
        if res["ok"] and isinstance(res["data"], dict) and "result" in res["data"] and res["data"]["result"] is not None:
            return res

        if allow_fallback:
            fb = self.request_json(
                source_id="solana_rpc_mainnet_official",
                url=DATA_SOURCES_REGISTRY["solana_rpc_mainnet_official"]["base_url"],
                method="POST",
                json_body=payload,
            )
            fb["is_fallback"] = True
            # Note: Solana JSON-RPC standard method returns identical schema, though archival pruning depth may differ
            fb["semantic_equivalence"] = "PARTIAL_ARCHIVAL_DEPTH_MAY_DIFFER"
            return fb

        return res
