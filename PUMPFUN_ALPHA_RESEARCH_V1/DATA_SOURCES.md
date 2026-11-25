# DATA SOURCES — WERYFIKACJA ŹRÓDEŁ DANYCH I API

## 1. Dokładny Zakres Czasowy Badania
- **Data i godzina rozpoczęcia badania (UTC):** `2026-11-24T22:22:02+00:00`
- **Początek 30-dniowego okna badawczego (UTC):** `2026-10-25T22:22:02+00:00`
- **Koniec 30-dniowego okna badawczego (UTC):** `2026-11-24T22:22:02+00:00`
- **Strefa czasowa przechowywania danych:** `UTC`
- **Strefa czasowa prezentacji godzinowej:** `Europe/Warsaw` (`2026-10-25T23:22:02+01:00` → `2026-11-24T23:22:02+01:00`, CET `UTC+1`)

---

## 2. Przetestowane Endpointy i Rzeczywista Dostępność Danych

Przed rozpoczęciem pobierania wykonano automatyczny audyt dostępności publicznych API (`src/probe_sources.py`, `src/probe_deep.py`, `src/probe_v3_exact.py`, `src/probe_trades_schema.py`):

| Źródło / Endpoint | Status HTTP | Zakres i jakość danych | Wykorzystanie w projekcie |
| --- | --- | --- | --- |
| `frontend-api-v3.pump.fun/coins` | **200 OK** | Pełne metadane tokenów, `created_timestamp`, `creator`, `bonding_curve`, `raydium_pool`, `ath_market_cap`, `canonical_pool_liquidity_usd`, `mayhem_state`, `boost_mode`, `twitter`, `website`. Obsługuje filtry `sort`, `complete`, `searchTerm`, `creator`. | Budowa uniwersum **8,462** tokenów (Grupa A i Grupa B). |
| `frontend-api-v3.pump.fun/trades/{chainId}/{mint}` | **200 OK** | Milisekundowa historia transakcji (`ordinalKey`, `blockId`, `txIndex`, `blockTimeMs`, `side`, `trader.address`, `baseAmount`, `valueUsd`, `valueNative`, `venue`) z precyzyjnym kursorem czasowym `after=1-0-0-{ts}` od sekundy zero życia tokena! | Rekonstrukcja pierwszych kupujących, FOMO, bundli z tego samego bloku i zysków klastrów. |
| `frontend-api-v3.pump.fun/candles/{chainId}/{mint}` | **200 OK** | Świece OHLCV + liczba transakcji dla rozdzielczości `1s, 15s, 30s, 1m, 5m, 15m, 1h, 4h, 1d` z parametrem `to={ts}`. | Odtworzenie historii cen `1m`, `15m`, `4h` (pełne 33 dni) dla **493** tokenów kohorty. |
| `frontend-api-v3.pump.fun/coins-v2/user-created-coins/{creator}` | **200 OK** | Kompletna lista wszystkich wcześniejszych i późniejszych tokenów utworzonych przez portfel twórcy. | Analiza **689** twórców + pozyskanie nieobciążonej próby porażek z 30 dni. |
| `profile-api.pump.fun/balance/tokens/{wallet}` & `/summary/{wallet}` | **200 OK** | Bieżące salda SOL i tokenów SPL oraz `tokenPnL` / `portfolioPnL`. | Weryfikacja retencji podaży insiderów i portfeli Smart Money (**420** priorytetowych portfeli). |
| `api.dexscreener.com/tokens/v1/solana/{mints}` | **200 OK** | Płynność pul DEX w USD, adresy par, wolumen 24h, linki społecznościowe oraz aktywne `boosts`. | Wzbogacenie płynnościowe i społecznościowe (**372 / 493** aktywnych par). |
| `api.geckoterminal.com/api/v2/networks/solana/...` | **200 OK** | Pule `pump-fun`, `pumpswap`, `trending_pools`, `ohlcv`, `trades`. | Cross-walidacja pul po migracji i wykrywanie aktywnych runnerów. |
| `solana-rpc.publicnode.com` (`getSignaturesForAddress`, `getTransaction` v1) | **200 OK** | Pełne transakcje on-chain (Solana Tx v1 `jsonParsed`), instrukcje `SystemProgram.transfer` oraz współpodpisujący (`fee_payer`). Uwaga: metody indeksowane `getTokenLargestAccounts` wymagają płatnego tokenu (HTTP 403). | Śledzenie źródeł finansowania SOL i rozróżnianie gorących portfeli CEX od prywatnych operatorów. |
| `api.binance.com/api/v3/klines?symbol=SOLUSDT` | **200 OK** | Świece `1h` (**888** godzin) i `1d` (**44** dni) dla pary `SOL/USDT`. | Kontekst makroekonomiczny i reżimy zmienności Solany. |
| `frontend-api-v2.pump.fun` / `swap-api.pump.fun/v2` | **403 / 410** | Starsze wersje API wyłączone (`410 Gone` / `403`). | Zastąpione w 100% przez aktualne endpointy `frontend-api-v3.pump.fun`. |
| `reddit.com/*.json` / API X (historyczne) | **403 / Brak** | Reddit blokuje zapytania bez OAuth (`403`); X nie udostępnia publicznie historycznych stanów kont z chwili przed pumpem. | Zastąpione niemodyfikowalnymi metadanymi startowymi on-chain, danymi DexScreener, HN Algolia oraz Google News RSS (z jawnym oznaczeniem ograniczeń). |

---

## 3. Bezpieczeństwo i Etyka Badawcza
- Nie wykonano żadnych transakcji blockchainowych, nie podłączano portfela ani nie podpisywano żadnych operacji.
- Nie omijano żadnych blokad dostępu ani zabezpieczeń CAPTCHA/Cloudflare.
- W raportach, plikach CSV/XLSX oraz kodzie źródłowym nie zapisano żadnych kluczy API ani sekretów środowiskowych.
