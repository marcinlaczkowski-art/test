# DATA QUALITY REPORT — KOMPLETNOŚĆ DANYCH, CENZUROWANIE I OGRANICZENIA API

## 1. Status Uniwersum: Obserwowane Uniwersum Chronologiczne vs Pełna Historia Pump.fun
Publiczne API `frontend-api-v3.pump.fun/coins` ogranicza głębokość paginacji `offset` do ok. `1 000–1 500` rekordów na zapytanie (co przy tempie ~19 premier/minutę odpowiada ok. 50–75 minutom ciągłego strumienia). Z tego powodu zbiór V2 jest **jawnie oznaczony jako obserwowane uniwersum chronologiczne (*observed chronological sample*)**, a nie pełny rejestr wszystkich setek tysięcy premier z 30 dni.

Kluczowa własność statystyczna V2: **żaden token w zbiorze (650 tokenów treningowo-walidacyjnych oraz 100 nowych tokenów post-freeze) nie został wybrany na podstawie przyszłego ATH, kapitalizacji, migracji ani wolumenu:**
- **Warstwa A (`A_30d_outcome_blind_panel`, $N = 320$):** Chronologiczne emisje z pełnych 30 dni utworzone przez twórców zidentyfikowanych wyłącznie przed oknem badawczym lub ze strumienia czasu utworzenia.
- **Warstwa B (`B_nov24_contiguous_arrival_stream`, $N = 330$):** Ciągły blok wszystkich kolejnych emisji zarejestrowanych prospektywnie wg `created_timestamp` wieczorem `2026-11-24` (ponad 8,5h przed pobraniem świec V2 — pełne horyzonty `1h` i `4h`, a horyzont `24h` jawnie oznaczony jako `censored`).
- **Warstwa C (`OUT_OF_TIME_UNSEEN_TEST.csv`, $N = 100$):** Świeże emisje z poranka `2026-11-25` pobrane **po zamrożeniu wag modelu V2**.

---

## 2. Rozkład Kompletności i Prawostronnego Cenzurowania Etykiet (`status_1h`, `status_4h`, `status_24h`)
Żaden niepełny horyzont nie został zamieniony na fałszywe zero (`porażkę`):
- **Horyzont `1h`:** `{'complete': 526, 'unknown': 124}`
- **Horyzont `4h`:** `{'complete': 526, 'unknown': 124}`
- **Horyzont `24h`:** `{'censored': 335, 'complete': 191, 'unknown': 124}` *(tokeny z Warstwy B mają ok. 8,5–9h historii, więc ich etykiety `24h` posiadają status `censored`)*

---

## 3. Kompletność Rekonstrukcji Podaży, Portfeli RPC i Księgowości FIFO
1. **Paginacja Solana RPC (`WALLETS_V2_DIR`):** Przeanalizowano łącznie **`50,292` sygnatur** dla `140` priorytetowych portfeli (do 600 sygnatur na portfel zamiast limitu 40 z V1). Dla **`68` portfeli** osiągnięto dokładny blok genezy (`COMPLETE_GENESIS_REACHED`). Pozostałe portfele o bardzo wysokiej aktywności oznaczono jako `PARTIAL_PAGINATED_600_SIGS`.
2. **Ograniczenia RPC na darmowym węźle publicznym:** Metoda indeksowana `getTokenLargestAccounts` zwraca na `publicnode` kod `403`, dlatego koncentrację podaży odtworzono z księgi transakcji i transferów SPL, jawnie rozróżniając pełną taśmę od taśmy obciętej przy bardzo wysokiej aktywności:

| Jakość rekonstrukcji podaży | Liczba tokenów |
| --- | --- |
| EXACT_LEDGER_FROM_GENESIS | 509 |
| APPROXIMATE_PARTIAL_TAPE | 141 |


3. **Kompletność kosztu bazowego FIFO (`REALIZED_PNL_V2.csv`):** Gdy portfel sprzedaje tokeny nabyte poza zindeksowanym oknem swapów (np. nieuchwycony transfer zewnętrzny), przychód trafia do kolumny `unattributed_sell_proceeds_sol`, a nie do zysku FIFO:

| Status kompletności księgowania FIFO | Liczba par (portfel, token) |
| --- | --- |
| EXACT_FIFO_VERIFIED | 1482 |
| APPROXIMATE_TRUNCATED_TAPE | 676 |
| PARTIAL_UNMATCHED_INVENTORY | 362 |


---

## 4. Weryfikacja Studium Przypadku `$COOL` (Sekcja 9)
W materiale referencyjnym o `$COOL` nie podano kanonicznego adresu `mint`, natomiast w ekosystemie `pump.fun` funkcjonuje kilkadziesiąt odrębnych kontraktów o symbolu `COOL` / `$COOL`. Ponieważ identyfikacja po samym symbolu jest metodologicznie błędna, wszystkie tokeny o symbolu `COOL` oznaczono w `INSIDER_ANALYSIS_V2.csv` statusem **`UNVERIFIED_TICKER_COLLISION_NOT_CONFIRMED` (`NIEROZSTRZYGNIĘTY`)** i wykluczono jako potwierdzone studium przypadku.
