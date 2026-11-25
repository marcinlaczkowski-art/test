# DATA QUALITY REPORT V2.1 — JAKOŚĆ, KOMPLETNOŚĆ I CENZUROWANIE DANYCH

## 1. Chronologiczne uniwersum badawcze i zbiór Out-of-Time (OOT)
- **Zbiór główny (Walk-Forward / Trening / Walidacja / Test):** `650` chronologicznych emisji tokenów (`TOKEN_METRICS_V2_1.csv`, `2 600` wielohoryzontowych snapshotów w `EARLY_SIGNALS_V2_1.csv` dla `60s, 180s, 300s, 900s`), wybranych całkowicie ślepo względem przyszłego ATH, kapitalizacji i migracji.
- **Zbiór Out-of-Time (`OUT_OF_TIME_V2_1.csv`):** `190` **całkowicie niewidzianych wcześniej** chronologicznych emisji (`0` wspólnych mintów z V1 i V2):
  - `190` kolejnych emisji chronologicznych po punkcie odcięcia zbioru V2 (`>10h` od startu — pełne pokrycie horyzontów `1h` i `4h`),
  - `0` świeżych porannych emisji z `2026-11-25` (`~75–110 min` od startu — pełny horyzont `1h`, natomiast `4h` i `24h` jawnie oznaczone jako `"censored"`).

## 2. Poprawa kompletności OOT względem V2 i tabela 9 celów predykcyjnych
W V2 przez agresywne limity zapytań (`HTTP 429`) kompletność OOT wynosiła zaledwie `21 / 100` (`21%`). W V2.1 dzięki kontrolowanej współbieżności (`Semaphore(3)` + retry/backoff + `asyncio.wait_for`) kompletność dla wszystkich upłyniętych horyzontów wzrosła do **`100.0%` dla 1h (`190` tokenów)** oraz **`100.0%` dla 4h (`190` tokenów)**.

| target | total_oot_tokens | complete_count | censored_count | unknown_count | completeness_of_elapsed_pct | positives | negatives | base_rate | statistical_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hit_2x_1h | 190 | 190 | 0 | 0 | 100.00 | 2 | 188 | 0.0105 | INCONCLUSIVE_LOW_POSITIVES |
| hit_3x_1h | 190 | 190 | 0 | 0 | 100.00 | 2 | 188 | 0.0105 | INCONCLUSIVE_LOW_POSITIVES |
| hit_2x_4h | 190 | 190 | 0 | 0 | 100.00 | 2 | 188 | 0.0105 | INCONCLUSIVE_LOW_POSITIVES |
| hit_3x_4h | 190 | 190 | 0 | 0 | 100.00 | 2 | 188 | 0.0105 | INCONCLUSIVE_LOW_POSITIVES |
| hit_5x_4h | 190 | 190 | 0 | 0 | 100.00 | 1 | 189 | 0.0053 | INCONCLUSIVE_LOW_POSITIVES |
| hit_2x_24h | 190 | 0 | 190 | 0 | N/A | 0 | 0 | N/A | INCONCLUSIVE_CENSORED_HORIZON |
| hit_3x_24h | 190 | 0 | 190 | 0 | N/A | 0 | 0 | N/A | INCONCLUSIVE_CENSORED_HORIZON |
| hit_5x_24h | 190 | 0 | 190 | 0 | N/A | 0 | 0 | N/A | INCONCLUSIVE_CENSORED_HORIZON |
| hit_10x_24h | 190 | 0 | 190 | 0 | N/A | 0 | 0 | N/A | INCONCLUSIVE_CENSORED_HORIZON |

## 3. Zasady higieny braków danych
- Żadna obserwacja `"censored"` ani `"unknown"` **nigdy nie została zamieniona na `0` (porażkę)**.
- Tokeny z `0` transakcji po starcie zweryfikowane kompletnym odczytem API mają rzeczywisty mnożnik `1.0x` (`complete`), natomiast błędy sieciowe lub nieupłynięte okna czasowe są bezwzględnie odfiltrowywane z mianownika metryk binarnych.
