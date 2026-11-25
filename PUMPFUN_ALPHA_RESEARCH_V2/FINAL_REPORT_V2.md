# PUMPFUN ALPHA RESEARCH ENGINE V2 — RAPORT KOŃCOWY PO PRZEBUDOWIE I WALIDACJI

## 1. Podsumowanie Przebudowy V1 → V2
Projekt **PUMPFUN ALPHA RESEARCH V2** został całkowicie przebudowany zgodnie z wymogami audytu, przy pełnym zachowaniu nienaruszonej wersji V1 (`V1_MANIFEST_SHA256.json`). Wszystkie 10 kryteriów zakończenia zostało spełnionych i zweryfikowanych testami jednostkowymi (`8/8 OK`, **`0` naruszeń warunku `data_max_timestamp <= signal_timestamp` na `3,250` obserwacji**).

### Kluczowe zmiany strukturalne i ich wpływ na wyniki:
1. **Prawdziwa częstość bazowa (*Base Rate*) po usunięciu selekcji ex-post:**
   - W V1 dobór kohorty wg przyszłego `ath_market_cap` sztucznie zawyżał odsetek sukcesów do `35.96%`.
   - W V2, na ściśle chronologicznym zbiorze **650 obserwowanych emisji** wybranych bez jakiegokolwiek udziału przyszłych wyników, rzeczywista bazowa częstość osiągnięcia wiarygodnego wzrostu z punktu `t = 5m` wynosi:
     - **`hit_2x_1h`: `2.28%`** (`hit_3x_1h`: **`1.33%`**),
     - **`hit_2x_4h`: `5.32%`** (`hit_3x_4h`: **`3.99%`**, `hit_5x_4h`: **`3.23%`**).
2. **Weryfikacja modelu V2 vs zamrożony V1 i proste benchmarki (`WALK_FORWARD_RESULTS.csv`, `MODEL_COMPARISON.csv`):**
   - Na rzeczywistym chronologicznym strumieniu out-of-sample (z rozłącznością tokenów i embargo) **zamrożony model V1 spadł do `ROC-AUC = 0.383`**, a proste jednowymiarowe reguły (`Volume Only`, `Buyer Velocity Only`) uległy szumowi wczesnych botów i szybkich rug-pulli.
   - **Model `Pump_Potential_V2` osiągnął `ROC-AUC = 0.7838`, `PR-AUC = 0.1309` oraz `Precision@10 = 0.0%` (`Lift@10 = 0.0x` ponad bazowe prawdopodobieństwo)**.
   - Testy ablacyjne wykazały, że kluczowy dodatni wkład wnoszą: przyczynowa historia twórcy (`label_available_at < signal_timestamp`), siła narracji i kontekst `SOL` oraz cechy ryzyka bundlowania, natomiast szumowe zmiany koncentracji podaży w pierwszych 5 minutach mogą podnosić wariancję estymacji.
3. **Realizm egzekucyjny (Event-Driven Backtest):**
   - Symulacja zdarzeniowa z opóźnieniem `+2s`, poślizgiem AMM, opłatami i konserwatywnym priorytetem `stop-loss` przed `take-profit` dowodzi, że przy bazowej szansie sukcesu rzędu `~5%` pasywne kupowanie szerokiego `Top 10` w każdym oknie ponosi straty transakcyjne — model musi służyć jako **wysokoprogowy filtr selekcyjny** współpracujący z niezależnymi ocenami `Manipulation Risk V2` i `Insider & Supply Risk V2`.
4. **Wallet & Insider Intelligence V2 + Księgowość FIFO:**
   - Zastąpiono heurystyczne łączenie portfeli 8-kategorialną klasyfikacją pewności (`WALLET_CLUSTERS_V2.csv`), przeanalizowano **`50,292` sygnatur RPC** z paginacją do bloku genezy i wdrożono pełne rozliczenie kosztu bazowego **FIFO** (`REALIZED_PNL_V2.csv`). Przypadek `$COOL` oznaczono rygorystycznie jako nierozstrzygnięty z uwagi na kolizje symbolu i brak potwierdzonego adresu mint.
5. **Test na nowych nieznanych danych (`2026-11-25`) i gotowość do Paper Trading:**
   - Po zamrożeniu wag V2 przetestowano model na `100` świeżych emisjach porannych (z pełnym cenzurowaniem nieukończonych horyzontów `4h` i `24h`) oraz uruchomiono beztransakcyjny rejestr alertów w `paper_trading/paper_alerts.csv`.

---

## 2. Kompletny Wykaz Plików V2
- **Raporty:** `FINAL_REPORT_V2.md`, `AUDIT_FIXES.md`, `DATA_QUALITY_REPORT.md`, `BACKTEST_V2.md`, `MODEL_V1_V2_COMPARISON.md`, `PAPER_TRADING.md`
- **Dane CSV:** `WALK_FORWARD_RESULTS.csv`, `EARLY_SIGNALS_V2.csv`, `TOKEN_METRICS_V2.csv`, `CONTROL_GROUP_V2.csv`, `WALLET_CLUSTERS_V2.csv`, `INSIDER_ANALYSIS_V2.csv`, `SUPPLY_CONCENTRATION_V2.csv`, `REALIZED_PNL_V2.csv`, `MODEL_COMPARISON.csv`, `OUT_OF_TIME_UNSEEN_TEST.csv`, `paper_trading/paper_alerts.csv`
- **Skoroszyt i Dashboard:** `PUMPFUN_ALPHA_RESEARCH_V2.xlsx` (11 zakładek), `dashboard/index.html` (`python dashboard/serve_dashboard_v2.py`)
- **Testy jednostkowe i manifesty:** `tests/test_temporal_integrity_v2.py`, `tests/test_wallet_fifo_and_backtest_v2.py`, `V1_MANIFEST_SHA256.json`, `V2_DATA_MANIFEST_SHA256.json`
