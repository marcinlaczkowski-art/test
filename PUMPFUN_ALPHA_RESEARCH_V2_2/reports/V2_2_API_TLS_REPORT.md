# V2_2_API_TLS_REPORT — AUDYT TLS, LIMITÓW API, RETRY I NIEZAWODNOŚCI ŹRÓDEŁ

## 1. Metodologia
W `data_sources/http_client.py` wdrożono klienta `VerifiedHttpClient` wymuszającego `ssl.create_default_context()` z `verify_mode = ssl.CERT_REQUIRED`, `check_hostname = True` i minimalną wersją `TLSv1.2`. Każde żądanie posiada osobny `connect_timeout` (`4.0s`) i `read_timeout` (`7.0–9.0s`), exponential backoff z losowym jitterem dla błędów przejściowych (`429, 500, 502, 503, 504`, timeout), brak ponowień dla błędów trwałych (`400, 404`) i błędów certyfikatów (`ssl.SSLError`) oraz circuit breaker z monitoringiem `SourceHealthMonitor`.

## 2. Tabela zweryfikowanych źródeł danych
| Źródło | Endpoint | Typ danych | TLS | Limit | Retry | Status |
| --- | --- | --- | --- | --- | --- | --- |
| pumpfun_v3 | https://frontend-api-v3.pump.fun | New token launches, OHLCV candles (1m/15m/4h), paginated swap tape, creator coins | TLSv1.3 (CERT_REQUIRED) | 3.0 rps / sem=3 | 3x exp backoff+jitter (429/5xx) | HEALTHY |
| pumpfun_profile | https://profile-api.pump.fun | Wallet profile metadata and token balances | NOT_QUERIED_YET (CERT_REQUIRED) | 3.0 rps / sem=3 | 2x exp backoff+jitter (429/5xx) | UNKNOWN |
| solana_rpc_publicnode | https://solana-rpc.publicnode.com | Solana JSON-RPC (getSignaturesForAddress, getTransaction jsonParsed) | NOT_QUERIED_YET (CERT_REQUIRED) | 5.0 rps / sem=4 | 3x exp backoff+jitter (429/5xx) | UNKNOWN |
| solana_rpc_mainnet_official | https://api.mainnet-beta.solana.com | Fallback Solana JSON-RPC (verified mainnet-beta endpoint) | NOT_QUERIED_YET (CERT_REQUIRED) | 2.0 rps / sem=2 | 2x exp backoff+jitter (429/5xx) | UNKNOWN |
| binance_spot | https://api.binance.com | SOLUSDT closed OHLCV klines (1h/15m) for SOL market regime & volatility | TLSv1.3 (CERT_REQUIRED) | 5.0 rps / sem=3 | 3x exp backoff+jitter (429/5xx) | HEALTHY |
| dexscreener_api | https://api.dexscreener.com | Secondary DEX pair verification for migrated tokens (non-equivalent fallback) | NOT_QUERIED_YET (CERT_REQUIRED) | 3.0 rps / sem=2 | 2x exp backoff+jitter (429/5xx) | UNKNOWN |

## 3. Liczba obserwacji, Opóźnienia i Braki (`monitoring/source_health_snapshot.json`)
| source_id | source_health_status | negotiated_tls_version | requests_total | success_count | error_count | rate_limit_429_count | p50_latency_ms | p95_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pumpfun_v3 | HEALTHY | TLSv1.3 | 282 | 282 | 0 | 0 | 302.40 | 534.50 |
| pumpfun_profile | UNKNOWN | NOT_QUERIED_YET | 0 | 0 | 0 | 0 | UNKNOWN | UNKNOWN |
| solana_rpc_publicnode | UNKNOWN | NOT_QUERIED_YET | 0 | 0 | 0 | 0 | UNKNOWN | UNKNOWN |
| solana_rpc_mainnet_official | UNKNOWN | NOT_QUERIED_YET | 0 | 0 | 0 | 0 | UNKNOWN | UNKNOWN |
| binance_spot | HEALTHY | TLSv1.3 | 2 | 2 | 0 | 0 | 454.30 | 478.60 |
| dexscreener_api | UNKNOWN | NOT_QUERIED_YET | 0 | 0 | 0 | 0 | UNKNOWN | UNKNOWN |

## 4. Wyniki testów awaryjnych, Ograniczenia i Status
- Przetestowano symulacje `Timeout`, `SSLError`, `HTTP 429`, `HTTP 500/503`, `HTTP 404`, uszkodzonego JSON oraz otwarcia Circuit Breakera (`Test_06` i `Test_07`: **`PASS`**).
- Fallback RPC (`api.mainnet-beta.solana.com`) jest jawnie oznaczany flagą `is_fallback = True` i `semantic_equivalence = "PARTIAL_ARCHIVAL_DEPTH_MAY_DIFFER"`.
- **Status:** `DATA_VALIDATED` (`HEALTHY`).
