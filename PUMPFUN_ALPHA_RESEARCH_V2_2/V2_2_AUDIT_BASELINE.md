# V2_2_AUDIT_BASELINE — AUDYT BAZOWY REPOZYTORIUM PRZED IMPLEMENTACJĄ V2.2

- **Repozytorium:** `https://github.com/marcinlaczkowski-art/test`
- **Gałąź bazowa:** `main` (commit `0f9b274`)
- **Gałąź robocza:** `feature/v2.2` (lokalna — bez publikacji do czasu wyraźnego potwierdzenia właściciela)
- **Zabezpieczony manifest SHA-256:** `PUMPFUN_ALPHA_RESEARCH_V2_2/data/MANIFEST_V1_V2_V2_1_SHA256.json`
  - `PUMPFUN_ALPHA_RESEARCH_V1`: `1 578` plików (`50` kluczowych raportów/kodów/CSV zhashowanych SHA-256)
  - `PUMPFUN_ALPHA_RESEARCH_V2`: `1 352` pliki (`39` kluczowych plików zhashowanych SHA-256)
  - `PUMPFUN_ALPHA_RESEARCH_V2_1`: `516` plików (`42` kluczowe pliki zhashowane SHA-256)

---

## 1. Przegląd zastanej architektury (V1 → V2 → V2.1)

| Wersja | Główna charakterystyka | Kluczowe ograniczenia wykryte w audycie Etapu Zero |
|---|---|---|
| **V1** (`PUMPFUN_ALPHA_RESEARCH_V1/`) | Pierwszy eksploracyjny silnik badawczy (`493` tokeny w głębokiej kohorcie z `8 462` uniwersum). | Selekcja tokenów zależna od przyszłego ATH/kapitalizacji (survivorship bias), brak rozdzielenia horyzontów cenzurowanych, brak walidacji FIFO i rezerw krzywej. |
| **V2** (`PUMPFUN_ALPHA_RESEARCH_V2/`) | Przebudowa na chronologiczny zbiór `650` tokenów i wielohoryzontowe etykiety (`1h / 4h / 24h`). | Przeciek zamknięcia świecy 1h SOL w środku godziny, pusty tracker historii w OOT/Paper, wymuszanie `is_ticker_first_mover = 1`, niska kompletność OOT (`21/100`), limit `3` transakcji RPC na portfel, błędy sumy podaży `>100%`. |
| **V2.1** (`PUMPFUN_ALPHA_RESEARCH_V2_1/`) | Wprowadzenie `UnifiedFeatureEngine`, naprawa świec SOL, walidacja podaży `<=100%`, kolejka FIFO, 3-okresowy Walk-Forward (`4h` embargo) i `190` tokenów OOT. | **Nadal występują krytyczne luki produkcyjne i badawcze dla V2.2:** sztuczne cofanie czasu `min(acquired_at_ms, signal_ts_ms)`, wyłączona weryfikacja certyfikatów TLS (`ssl.CERT_NONE` / `ssl=False`), brak 6-czasowego modelu zdarzeń, mieszanie estymowanych rezerw AMM po migracji z dokładną rekonstrukcją w backteście, nadpisywanie pojedynczego CSV w Paper Tradingu zamiast niezmiennego dziennika zmian, brak grafu powtarzalności grup portfeli (`wallet_cluster_track_record`) oraz za mała próba OOT (`190 < 1000` tokenów i `2 < 30` pozytywnych przypadków). |

---

## 2. Szczegółowy rejestr wykrytych problemów w kodzie bazowym (Dowody i Plan Naprawy)

### A. LIVE TIMING I DATA INTEGRITY (Priorytet P0 — Krytyczny)

#### Problem A1: Sztuczne cofanie czasu pozyskania danych (`min(acquired_at_ms, signal_ts_ms)`)
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/feature_engine.py`, metoda `UnifiedFeatureEngine.compute_snapshot`, linie `183–184`.
- **Dowód w kodzie:**
  ```python
  acq_ms = int(acquired_at_ms) if acquired_at_ms is not None else int(signal_ts_ms)
  acq_ms = min(acq_ms, int(signal_ts_ms))
  ```
- **Poziom ryzyka:** **CRITICAL (P0)** — jeżeli dane zostały faktycznie pobrane z API po czasie sygnału (`acquired_at_ms > signal_ts_ms`), funkcja po cichu przycina `acquired_at_ms` w dół do `signal_ts_ms`, maskując opóźnione pobranie danych lub odtwarzanie z przeszłości jako sygnał w czasie rzeczywistym.
- **Proponowana poprawka w V2.2:** Całkowite usunięcie `min(...)`. Wprowadzenie 6-polowego rekordu czasu (`event_ts_ms`, `source_published_at_ms`, `acquired_at_ms`, `feature_computed_at_ms`, `signal_generated_at_ms`, `alert_emitted_at_ms`). Narzucenie twardego warunku `acquired_at_ms <= signal_generated_at_ms`; naruszenie odrzuca sygnał ze statusem `INVALID_TEMPORAL_ORDER`. Dla danych historycznych bez znanego czasu publikacji ustawiany jest jawny status `HISTORICAL_AVAILABILITY_UNKNOWN`.
- **Test potwierdzający naprawę:** `test_p0_01_zero_clamped_timestamps` oraz `test_temporal_01_acquired_after_signal_rejected` w `PUMPFUN_ALPHA_RESEARCH_V2_2/tests/`.

#### Problem A2: Wsteczne ustawianie czasu sygnału w skanerze Paper Trading (`sig_ts = min(eval_ts, cts + 180_000)`)
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/paper_trader_v2_1.py`, funkcja `run_paper_trading_scan_v2_1`, linie `122–123` oraz `140–143`.
- **Dowód w kodzie:**
  ```python
  eval_ts = int(time.time() * 1000)
  sig_ts = min(eval_ts, cts + 180_000) if (eval_ts - cts) >= 180_000 else eval_ts
  ...
  snap = engine.compute_snapshot(..., signal_ts_ms=sig_ts, acquired_at_ms=sig_ts)
  ```
- **Poziom ryzyka:** **CRITICAL (P0)** — dla tokena odkrytego po 10 minutach życia (`age = 600s`) skaner cofał `signal_ts_ms` oraz `acquired_at_ms` do `cts + 180_000` (3. minuty życia), zapisując historyczną cenę z 3. minuty jako cenę alertu live!
- **Proponowana poprawka w V2.2:** W trybie live/paper `signal_generated_at_ms` oraz `alert_emitted_at_ms` pochodzą wyłącznie z rzeczywistego zegara systemowego po zakończeniu obliczeń (`acquired_at_ms <= feature_computed_at_ms <= signal_generated_at_ms <= alert_emitted_at_ms`). Tokeny wykryte po przekroczeniu maksymalnego okna wczesnej obserwacji (`token_age_seconds > max_live_discovery_age_sec`) otrzymują flagę `LATE_DISCOVERY` i są wyłączane ze standardowej statystyki sygnałów live.
- **Test potwierdzający naprawę:** `test_p0_04_zero_historical_alert_timestamps` oraz `test_temporal_09_late_discovery_flagged`.

---

### B. TLS, API I NIEZAWODNOŚĆ ŹRÓDEŁ DANYCH (Priorytet P0 — Krytyczny)

#### Problem B1: Wyłączona weryfikacja certyfikatów TLS (`CERT_NONE` oraz `ssl=False`)
- **Plik i funkcja:**
  1. `PUMPFUN_ALPHA_RESEARCH_V2_1/src/paper_trader_v2_1.py`, funkcja `_sync_http_get` (linie `50–52`: `ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE`) oraz `run_paper_trading_scan_v2_1` (linia `86`: `aiohttp.TCPConnector(limit=8, ssl=False, force_close=True)`).
  2. `PUMPFUN_ALPHA_RESEARCH_V2_1/src/step1_deep_wallet_rpc_v2_1.py`, funkcja `main` (linia `271`: `aiohttp.TCPConnector(limit=10, ssl=False, force_close=True)`).
- **Dowód:** Sonda bazowa `tls_probe_baseline_v2_2.json` wykazała, że wszystkie 6 używanych hostów (`frontend-api-v3.pump.fun`, `profile-api.pump.fun`, `solana-rpc.publicnode.com`, `api.mainnet-beta.solana.com`, `api.binance.com`, `api.dexscreener.com`) poprawnie obsługuje **TLSv1.3** z pełną walidacją łańcucha X.509 (`CERT_REQUIRED`). Wyłączenie SSL w V2.1 było błędem implementacyjnym narażającym na MITM i ukryte błędy warstwy transportowej.
- **Poziom ryzyka:** **CRITICAL (P0)**.
- **Proponowana poprawka w V2.2:** Nowy moduł `data_sources/http_client.py` wymuszający `ssl.create_default_context()` z `verify_mode = ssl.CERT_REQUIRED`, `check_hostname = True` i `minimum_version = ssl.TLSVersion.TLSv1_2` (statyczna asercja i test skanujący kod V2.2 pod kątem zakazanych wzorców `CERT_NONE`, `verify=False`, `ssl=False`). Dodanie osobnych timeoutów `(connect_timeout, read_timeout)`, exponential backoff z losowym jitterem, obsługi `429`/`5xx` (bez retry dla `400/404`), circuit breakera oraz monitoringu `source_health_status` (`HEALTHY`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`).
- **Test potwierdzający naprawę:** `test_p0_06_zero_disabled_tls_validation` oraz `test_p0_07_http_429_5xx_circuit_breaker`.

---

### C. FEATURE PARITY I OBSŁUGA BRAKÓW (Priorytet P0/P1 — Wysoki)

#### Problem C1: Brak formalnego rejestru metadanych cech i rozdziału potencjału narracji od realnej aktywności social
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/feature_engine.py`, linie `67–79` oraz `449–450`.
- **Dowód:** Cechy w V2.1 nie posiadały jawnej deklaracji `lookback`, `required_inputs` i rozdziału `narrative_potential` vs `observed_social_traction` vs `historical_social_activity` (`UNKNOWN` dla historycznego X/Telegram).
- **Poziom ryzyka:** **HIGH (P1)**.
- **Proponowana poprawka w V2.2:** Wspólny moduł `feature_engine/feature_engine.py` używany przez `training`, `validation`, `oot`, `paper_trading` i `live`, wyposażony w pełny rejestr specyfikacji każdej cechy (`FEATURE_DEFINITIONS_V2_2`), obsługę kontekstu reżimu rynkowego SOL i ekosystemu pump.fun oraz rygorystyczne oznaczanie `UNKNOWN` dla brakujących danych historycznych social media.
- **Test potwierdzający naprawę:** `test_p0_14_shared_features_parity_all_modes` oraz `test_p0_15_incomplete_data_protection`.

---

### D. HISTORYCZNA REKONSTRUKCJA AMM I WYKONANIA (Priorytet P0 — Wysoki)

#### Problem D1: Łączenie estymowanych rezerw po migracji (`ESTIMATED_AMM_RESERVES`) z dokładną rekonstrukcją w głównym backteście
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/execution_and_backtest_v2_1.py`, funkcja `simulate_amm_position_execution`, linie `288–296`.
- **Dowód w kodzie:**
  ```python
  else:
      r_sol_out = max(85.0, math.sqrt(85.0 * 206_900_000.0 * exit_mid_sol))
      r_tok_out = r_sol_out / exit_mid_sol
      res_src_out = "ESTIMATED_AMM_RESERVES"
  ```
  Rekordy te trafiały bezpośrednio do średnich i median głównego backtestu obok dokładnych rezerw krzywej, a rekonstrukcja nie śledziła sekwencyjnie stanu rezerw przed i po każdej transakcji wg `(blockId, txIndex, eventIndex)`.
- **Poziom ryzyka:** **HIGH (P0)**.
- **Proponowana poprawka w V2.2:** Nowy moduł `amm_reconstruction/amm_reconstructor.py`:
  1. Sekwencyjna rekonstrukcja stanu rezerw na krzywej bonding curve transakcja-po-transakcji wg `(blockId, txIndex, legIndex, eventIndex)` z walidacją ciągłości taśmy (`early_30m_pagination_truncated == False`) i wykrywaniem dokładnego timestampu migracji.
  2. Rozdzielenie: `BONDING_CURVE_EXACT`, `MIGRATED_AMM_RECONSTRUCTED`, `RESERVE_RECONSTRUCTION_INCOMPLETE` oraz `MIGRATION_STATE_UNKNOWN`.
  3. Rekordy `RESERVE_RECONSTRUCTION_INCOMPLETE` są **wyłączane z dokładnego backtestu** (raportowane wyłącznie w osobnej tabeli estymacyjnej), a każdy wynik zawiera `execution_confidence` oraz pełną dekompozycję cen i kosztów (`mid_price`, `spot_reference_price`, `executable_buy_price`, `executable_sell_price`, `price_impact_pct`, `slippage_pct`, `protocol_fee_sol`, `network_fee_sol`, `priority_fee_sol`) dla `0.1, 0.25, 0.5, 1.0, 2.0 SOL`.
- **Test potwierdzający naprawę:** `test_p0_11_amm_exact_reconstruction` oraz `test_p0_12_separate_exact_from_estimated_reserves`.

---

### E. WALLET INTELLIGENCE 2.0 I POWTARZALNOŚĆ GRUP (Priorytet P1 — Wysoki)

#### Problem E1: Limit 25 parsowanych transakcji dla aktywnych portfeli oraz brak `wallet_cluster_track_record`
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/step1_deep_wallet_rpc_v2_1.py` (linia `40`: `MAX_PARSE_TX_PER_WALLET = 25`) oraz `wallet_supply_fifo_v2_1.py` (linie `248–350`).
- **Dowód:** W V2.1 relacje klastrowe były klasyfikowane per-token, ale nie istniał przyczynowy rejestr `wallet_cluster_track_record`, który mierzyłby **przed sygnałem**, na ilu wcześniejszych tokenach dana grupa portfeli akumulowała przed wzrostem, jaki miała historyczny wynik FIFO, średni czas utrzymania pozycji (`average_holding_time`) i czy sprzedawała przed innymi uczestnikami.
- **Poziom ryzyka:** **HIGH (P1)**.
- **Proponowana poprawka w V2.2:** Moduł `wallet_intelligence/wallet_intel_v2_2.py`:
  1. Pełna paginacja dostępnych sygnatur i transakcji z jawnymi polami `history_coverage_start`, `history_coverage_end`, `history_completeness`, `INSUFFICIENT_HISTORY`, `funding_sources`, `funding_graph`, `average_holding_time` oraz rozdzieleniem `realized_pnl`, `unrealized_pnl`, `estimated_pnl` i `unknown_pnl`.
  2. Graf krawędzi 8 relacji (`DIRECT_FUNDING`, `SHARED_FUNDER`, `REPEATED_TRANSFER`, `COMMON_COUNTERPARTY`, `SAME_SLOT_BUY`, `REPEATED_CO_BUYING`, `CREATOR_LINK`, `UNKNOWN_RELATION`) z polami `source_wallet`, `target_wallet`, `first_seen`, `last_seen`, `evidence_count`, `confidence`, `evidence_ids` oraz separacją klastrów na `CONFIRMED`, `PROBABLE`, `WEAK`, `UNKNOWN` (wykluczając giełdy/custody jako insiderów i nie traktując `SAME_SLOT_BUY` jako dowodu kontroli).
  3. Przyczynowy `wallet_cluster_track_record` wyliczany ściśle dla `outcome_known_at_ms <= signal_generated_at_ms`.
- **Test potwierdzający naprawę:** Testy akceptacyjne `16–22` (`test_wi_16` .. `test_wi_22`).

---

### F. OOT (SKALA PRÓBY) ORAZ PAPER TRADING 30 DNI (Priorytet P0/P1 — Wysoki)

#### Problem F1: Zbyt mała próba OOT w V2.1 (`190` tokenów, `2` pozytywne przypadki `2x_4h`)
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/OUT_OF_TIME_V2_1.csv` (`190` wierszy).
- **Dowód:** Próba `190` tokenów i `2` pozytywnych przypadków nie spełnia minimalnego progu V2.2 (`>= 1000` tokenów OOT oraz `>= 30` pozytywnych przypadków dla głównego targetu).
- **Poziom ryzyka:** **HIGH (P1)**.
- **Proponowana poprawka w V2.2:** Rozbudowa chronologicznego, zamrożonego zbioru OOT w `PUMPFUN_ALPHA_RESEARCH_V2_2/oot/` (pobranie z weryfikowanym TLS rozszerzonego strumienia chronologicznych emisji `>= 1 000` tokenów tam, gdzie publiczne API pozwala, z pełnymi mianownikami typu `2/10 = 20.0%`, Brier score, kalibracją, expectancy i CI; a jeżeli liczba pozytywnych przypadków głównego targetu pozostanie `< 30` lub nie upłynęło 30 dni obserwacji live, bezwzględne ustawienie `INSUFFICIENT_POSITIVE_SAMPLE` / `OOT_STATUS = INSUFFICIENT_SAMPLE` i `EDGE_STATUS = NOT_ESTABLISHED`).
- **Test potwierdzający naprawę:** Testy akceptacyjne `23–28`.

#### Problem F2: Nadpisywanie pojedynczego pliku CSV w Paper Tradingu zamiast niezmiennego dziennika pozycji i rejestru przerw 30-dniowych
- **Plik i funkcja:** `PUMPFUN_ALPHA_RESEARCH_V2_1/src/paper_trader_v2_1.py` (linia `203`: `df.to_csv(out_csv, index=False)`).
- **Dowód:** Każde uruchomienie nadpisywało `paper_alerts_v2_1.csv`, brakowało append-only historii przejść stanów (`OPEN`, `CLOSED_TP`, `CLOSED_SL`, `CLOSED_TRAILING`, `CLOSED_TIME`, `CENSORED`, `NO_EXECUTABLE_ENTRY`, `DATA_INVALID`), brakowało walidacji `entry_price > 0` przed otwarciem pozycji oraz rejestru uptime/downtime dla 30-dniowego cyklu.
- **Poziom ryzyka:** **CRITICAL (P0)**.
- **Proponowana poprawka w V2.2:** Przebudowa `paper_trading/` na architekturę **append-only JSONL + wersjonowane tabele stanów**:
  1. Niezmienny dziennik sygnałów (`signals_log.jsonl`), dziennik zdarzeń pozycji (`position_events_log.jsonl` — zero nadpisywania wcześniejszych wpisów!), dziennik dostępności systemu (`uptime_sessions_log.jsonl`) oraz cykliczny runner 30-dniowy z aktualizacją `15m / 1h / 4h / 24h`, MFE/MAE oraz obsługą `TP`, `SL`, `Trailing Stop` i `Time Stop`.
  2. Ponieważ od startu V2.2 w dniu `2026-11-25` upłynęło `< 30` dni rzeczywistego działania ciągłego, status końcowy zgodnie z Sekcją 16 musi wynosić jawnie `PAPER_TRADING_STATUS = IN_PROGRESS` (bez symulowania fikcyjnych 30 dni z przeszłości!).
- **Test potwierdzający naprawę:** Testy akceptacyjne `4, 5, 8, 9, 10, 13`.

---

## 3. Decyzja po Etapie Zero
Audyt bazowy został zakończony i zapisany przed rozpoczęciem implementacji. Przechodzimy do realizacji etapowej na gałęzi `feature/v2.2` w katalogu `PUMPFUN_ALPHA_RESEARCH_V2_2/` bez modyfikowania jakiegokolwiek pliku w V1, V2 ani V2.1.
