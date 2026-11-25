# V2_2_PAPER_TRADING_REPORT — RAPORT SYSTEMU PAPER TRADING V2.2 (MINIMUM 30 DNI)

## 1. Metodologia i Bezpieczeństwo
Silnik `paper_trading/paper_engine_v2_2.py` oraz demon `paper_trading/run_30d_paper_daemon.py`:
- Działają wyłącznie na nowych danych napływających w czasie rzeczywistym po TLSv1.3 (`CERT_REQUIRED`).
- Nie przechowują kluczy prywatnych, nie podpisują ani nie wysyłają żadnych transakcji blockchain.
- Zapisują niezmienne (append-only) dzienniki JSONL: `uptime_sessions_log.jsonl`, `signals_log.jsonl`, `position_events_log.jsonl` oraz `late_discoveries_log.jsonl`.
- Blokują otwieranie pozycji bez wykonywalnej ceny wejścia (`NO_EXECUTABLE_ENTRY`, zero pozycji z ceną `0.0000`).

## 2. Dotychczasowy stan rzeczywistego działania (`paper_trading/paper_status_summary_v2_2.json`)
- **Status:** **`PAPER_TRADING_STATUS = IN_PROGRESS`**
- **Rzeczywisty zebrany czas testu:** `0.0002` dnia z wymaganych **`30` kolejnych dni** (zarejestrowane przerwy: `0.0s`).
- **Wykryte tokeny w cyklu startowym:** `20`
- **Podział decyzji skanera:** `{"BELOW_CONFLUENCE_THRESHOLD": 19, "PAPER_POSITION_OPENED": 1}`
- **Otwarte pozycje paper łącznie:** `1` (aktywne: `1`, zamknięte: `0`).

## 3. Zarejestrowane kandydatury live (w tym tokeny odrzucone i bez wzrostu)
| token_symbol | token_age_seconds | discovery_status | liquidity_sol | total_score | confluence_class | signal_decision | decision_reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SillyFrog | 3.4400 | ON_TIME_LIVE | 60.19 | 8.0000 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=8.0 < 34.0 |
| rock | 4.2600 | ON_TIME_LIVE | 63.89 | 13.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=13.0 < 34.0 |
| SYBA | 9.8000 | ON_TIME_LIVE | 94.82 | 31.58 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=31.58 < 34.0 |
| MIA | 14.48 | ON_TIME_LIVE | 60.04 | 8.0000 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=8.0 < 34.0 |
| ch | 15.12 | ON_TIME_LIVE | 54.04 | 32.34 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=32.34 < 34.0 |
| LONG | 19.81 | ON_TIME_LIVE | 60.01 | 8.0000 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=8.0 < 34.0 |
| Reddit | 24.36 | ON_TIME_LIVE | 61.05 | 50.28 | MEDIUM_CONFLUENCE | PAPER_POSITION_OPENED | Valid live confluence & executable curve liquidity |
| SKIP2027 | 28.40 | ON_TIME_LIVE | 60.43 | 26.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=26.0 < 34.0 |
| KOLD | 31.04 | ON_TIME_LIVE | 60.68 | 25.17 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=25.17 < 34.0 |
| CHAROC | 32.56 | ON_TIME_LIVE | 105.94 | 20.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=20.0 < 34.0 |
| $Queen | 35.13 | ON_TIME_LIVE | 96.03 | 20.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=20.0 < 34.0 |
| Greg | 37.80 | ON_TIME_LIVE | 60.00 | 15.00 | HIGH_RISK | BELOW_CONFLUENCE_THRESHOLD | class=HIGH_RISK, score=15.0 < 34.0 |
| Moonvember | 40.37 | ON_TIME_LIVE | 60.00 | 15.00 | HIGH_RISK | BELOW_CONFLUENCE_THRESHOLD | class=HIGH_RISK, score=15.0 < 34.0 |
| $GOAT | 41.02 | ON_TIME_LIVE | 60.00 | 23.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=23.0 < 34.0 |
| MIEZI | 47.10 | ON_TIME_LIVE | 18.03 | 31.00 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=31.0 < 34.0 |
| kittylick | 50.77 | ON_TIME_LIVE | 72.04 | 24.88 | HIGH_RISK | BELOW_CONFLUENCE_THRESHOLD | class=HIGH_RISK, score=24.88 < 34.0 |
| PAIRLYCAT | 53.32 | ON_TIME_LIVE | 102195.21 | 8.0000 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=8.0 < 34.0 |
| Goku | 56.06 | ON_TIME_LIVE | 69.68 | 24.61 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=24.61 < 34.0 |
| ANSEM | 59.81 | ON_TIME_LIVE | 61.08 | 24.73 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=24.73 < 34.0 |
| Kyc | 66.38 | ON_TIME_LIVE | 87.29 | 6.0000 | LOW_CONFLUENCE | BELOW_CONFLUENCE_THRESHOLD | class=LOW_CONFLUENCE, score=6.0 < 34.0 |

## 4. Instrukcja kontynuacji 30-dniowego testu i Status
Aby kontynuować zbieranie 30 dni ciągłych obserwacji na żywo z automatycznym pomiarem przerw (`uptime_sessions_log.jsonl`) i aktualizacjami `15m / 1h / 4h / 24h`, należy utrzymywać uruchomiony proces:
`python PUMPFUN_ALPHA_RESEARCH_V2_2/paper_trading/run_30d_paper_daemon.py`
- **Status:** `PAPER_TRADING_STATUS = IN_PROGRESS` (brak ukończonych 30 dni rzeczywistego czasu zegarowego).
