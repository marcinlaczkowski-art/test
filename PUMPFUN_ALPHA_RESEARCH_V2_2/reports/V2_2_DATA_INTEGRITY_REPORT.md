# V2_2_DATA_INTEGRITY_REPORT — INTEGRALNOŚĆ CZASOWA I DANYCH (6 ZNACZNIKÓW CZASU)

## 1. Metodologia
W `data_integrity/temporal_ledger.py` wdrożono strukturę `SixTimestampEnvelope` rozdzielającą sześć niezależnych znaczników czasu:
1. `event_ts_ms` — czas bloku/zdarzenia na blockchainie Solana,
2. `source_published_at_ms` — czas publikacji przez źródło (`"UNKNOWN"` jeśli API go nie udostępnia),
3. `acquired_at_ms` — rzeczywisty zegar odebrania odpowiedzi przez nasz system,
4. `feature_computed_at_ms` — czas wyliczenia wektora cech,
5. `signal_generated_at_ms` — czas wygenerowania oceny sygnału,
6. `alert_emitted_at_ms` — czas wysłania alertu / otwarcia pozycji paper.

Całkowicie usunięto logikę `min(acquired_at_ms, signal_ts_ms)` obecną w V2.1 (potwierdzone statycznym skanem drzewa AST w `Test_01_zero_clamped_timestamps`).

## 2. Źródła danych i Liczba obserwacji
- Zweryfikowano `650` rekordów historycznych (`availability_status = "HISTORICAL_AVAILABILITY_UNKNOWN"`, co uniemożliwia traktowanie archiwum jako dowodu czasu alertu live), `270` rekordów OOT oraz `20` rekordów live (`availability_status = "REALTIME_VERIFIED"`).

## 3. Braki i Odrzucenia
- Tokeny wykryte na żywo po upływie `> 300s` od startu są oznaczane jako `LATE_DISCOVERY` i zapisywane osobno w `paper_trading/late_discoveries_log.jsonl`.
- Wszystkie odrzucone próby naruszenia porządku czasowego (`INVALID_TEMPORAL_ORDER`) oraz duplikaty (`DUPLICATE_SIGNAL_REJECTED`) są dopisywane do `data/temporal_violations_log.jsonl`.

## 4. Wyniki, Ograniczenia, Dowody i Status
- Wszystkie 10 scenariuszy temporalnych z Sekcji 3.4 oraz Testy P0 `01–05, 08, 14, 15` zakończone wynikiem **`PASS`** (`0` zaakceptowanych przypadków temporal leakage).
- **Ograniczenie:** Publiczne endpointy REST Pump.fun nie zwracają osobnego nagłówka `source_published_at_ms` indeksatora — pole to jest uczciwie oznaczane jako `"UNKNOWN"`.
- **Status:** `DATA_VALIDATED` (`PASS`).
