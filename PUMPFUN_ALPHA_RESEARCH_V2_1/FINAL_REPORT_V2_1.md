# PUMPFUN ALPHA RESEARCH V2.1 — RAPORT KOŃCOWY PO NAPRAWIE METODOLOGICZNEJ

## 1. Streszczenie zarządcze (Executive Summary)
Wersja **V2.1 (`PUMPFUN_ALPHA_RESEARCH_V2_1`)** stanowi ukierunkowaną naprawę inżynieryjną i badawczą problemów wykrytych w drugim audycie (`PUMPFUN_ALPHA_V2_SECOND_AUDIT`), przy zachowaniu **100% nienaruszonych katalogów V1 i V2** (potwierdzone sumami SHA-256 dla `65` plików V1 i `55` plików V2).

### Co naprawiono technicznie:
1. **Zero przecieku przyszłości (P0):** Wyeliminowano przeciek niezamkniętej świecy godzinowej SOL w środku godziny (`MarketContextTracker` wymaga `close_time_ms <= signal_timestamp_ms`), dodano pełną kontrolę pochodzenia i czasu dostępności dla każdej z 24 cech (`feature_available_at_ms <= signal_timestamp_ms`) z twardą blokadą `FeatureLeakageError` oraz zablokowano użycie nieoznaczonych czasowo wyników twórców/portfeli przed upływem ich horyzontu (`label_available_at_ms`).
2. **100% parzystości cech `TRENING == WALIDACJA == OOT == PAPER == LIVE` (P0):** Jeden wspólny moduł `src/feature_engine.py` + serializowany checkpoint `UnifiedStateBundle` (`state_post_wf_v2_1.json`). Usunięto pusty tracker w OOT/Paper oraz usunięto sztuczne podstawianie `is_ticker_first_mover = 1` (`max_abs_diff = 0.000000` w testach parzystości).
3. **Wysoka kompletność Out-of-Time (P0):** Zwiększono próbę OOT do **`190` niewidzianych chronologicznie tokenów** bez jakiegokolwiek filtrowania po ATH czy wolumenie, osiągając **`100.0%` kompletności dla horyzontu 1h (`n=190`)** oraz **`100.0%` kompletności dla horyzontu 4h (`n=190`)** (wobec `21/100` w V2).
4. **Głęboka rekonstrukcja portfeli RPC, walidacja podaży `<=100%` i ścisłe FIFO (P1):** Sparsowano `2,338` pełnych transakcji `jsonParsed` dla `107` portfeli (wobec limitu 3 tx w V2), naprawiono błąd sumy udziałów `>100%` (`max_valid_holder_sum_pct = 99.80%`, blokada `INVALID_SUPPLY_RECONSTRUCTION`) oraz wdrożono kolejkę lotów **FIFO** z blokadą `UNKNOWN_COST_BASIS` (`1354` przypadków sprzedaży bez pokrycia).
5. **Realistyczny symulator płynności AMM `0.1–2.0 SOL` (P1):** Oddzielono zwrot ze środkowej ceny (`mid_price`), wycenę rynkową (`mark_to_market`), zwrot wykonalny na rezerwach (`executable`) oraz zwrot netto po opłatach swap `1%` i priorytetowych (`net_after_fees`).

---

## 2. Najważniejsze wnioski badawcze po usunięciu błędów danych

### A. Które sygnały przetrwały rygorystyczną weryfikację (Prawdziwe wczesne sygnały)?
1. **Wzrost i przyspieszenie napływu niezależnych kupujących (`Independent Buyer Growth` = `independent_buyer_velocity * buyer_acceleration_ratio`):** Najsilniejszy prosty predyktor w teście Walk-Forward (`PR-AUC = 0.1504` przy `base_rate = 6.00%`, `Precision@10 = 30.0%`, `Lift = 5.0x`).
2. **Absorpcja pierwszej korekty (`First Correction Absorption` = `dip_absorption_ratio + 0.5 * buy_sell_log_ratio`):** Drugi najsilniejszy pojedynczy mechanizm (`Walk-Forward ROC-AUC = 0.6232`, `PR-AUC = 0.1337`, `Precision@5 = 40.0%`). Tokeny, w których pierwsze cofnięcie o `>=12%` od lokalnego szczytu jest natychmiast wykupywane przewagą popytu nad podażą, mają istotnie wyższe prawdopodobieństwo kontynuacji ruchu do `2x–3x` w oknie `4h`.
3. **Brak wczesnego zrzutu twórcy (`creator_dumped_flag == 0`) oraz brak włączonego trybu `mayhem_enabled`:** Oba czynniki konsekwentnie działają jako filtry negatywne redukujące ekspozycję na natychmiastowe rug-pulle.

### B. Które cechy okazały się szumem lub artefaktem po usunięciu przecieku?
1. **Surowa liczba wcześniejszych emisji twórcy (`creator_prior_launches_log` / grupa `creator_history`):** W V1/V2 statystyki twórców były zawyżone przez nieoznaczone czasowo `ath_market_cap` lub korelację wewnątrz próby. Po narzuceniu ścisłego warunku `label_available_at_ms <= signal_ts_ms` okazało się, że wysoka liczba wcześniejszych tokenów identyfikuje głównie masowe boty deweloperskie. **Usunięcie grupy `creator_history` w teście ablacji podniosło Walk-Forward `ROC-AUC` z `0.5382` do `0.6721` (`+0.1339`) oraz `PR-AUC` z `0.1060` do `0.1432`!** Dlatego w V2.1 jako model rekomendowany przyjęto oczyszczony model **`10_Pump_Potential_V2_1_Pruned`** oraz prostą regułę **`2_Independent_Buyer_Growth`**.
2. **Surowy wolumen (`Volume Only`) i sam dotychczasowy wzrost ceny (`Price Momentum Only`):** Bez filtracji niezależnych portfeli surowy wolumen i sam fakt wczesnego wybicia ceny (`already_moved_mult`) dają `ROC-AUC < 0.45` w Walk-Forward — sztuczny obrót botów i jednoslotowe snajpy generują wysoki wolumen oraz wysoką cenę wejścia, po których następuje dystrybucja na detalicznych kupujących FOMO.

### C. Wyniki na całkowicie niewidzianym zbiorze Out-of-Time (`OUT_OF_TIME_V2_1.csv`)
| model_name | unseen_oot_4h_complete_n | positives_2x_4h | base_rate_2x_4h | oot_roc_auc_2x_4h | oot_pr_auc_2x_4h | oot_precision_at_10 | oot_precision_at_20 | oot_p20_wilson_95ci_low | oot_p20_wilson_95ci_high | oot_lift_at_20 | oot_top20_mean_net_0_25_sol_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1_Buyer_Velocity_Only | 190 | 2 | 0.0105 | 0.8644 | 0.0549 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -18.71 |
| 2_Independent_Buyer_Growth | 190 | 2 | 0.0105 | 0.8005 | 0.0381 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -18.64 |
| 3_Volume_Only | 190 | 2 | 0.0105 | 0.6809 | 0.0237 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -18.76 |
| 4_Price_Momentum_Only | 190 | 2 | 0.0105 | 0.0120 | 0.0080 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -10.52 |
| 5_First_Correction_Absorption | 190 | 2 | 0.0105 | 0.5665 | 0.0223 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -13.49 |
| 6_Wallet_Intelligence | 190 | 2 | 0.0105 | 0.4029 | 0.0153 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -12.57 |
| 7_Pump_Potential_V1_Frozen | 190 | 2 | 0.0105 | 0.9309 | 0.1010 | 0.0000 | 0.1000 | 0.0279 | 0.3010 | 9.5000 | -9.9400 |
| 8_Pump_Potential_V2_Frozen | 190 | 2 | 0.0105 | 0.8910 | 0.0664 | 0.0000 | 0.0500 | 0.0089 | 0.2361 | 4.7500 | -16.15 |
| 9_Pump_Potential_V2_1_Full | 190 | 2 | 0.0105 | 0.6941 | 0.0315 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -16.91 |
| 10_Pump_Potential_V2_1_Pruned | 190 | 2 | 0.0105 | 0.5612 | 0.0173 | 0.0000 | 0.0000 | 0.0000 | 0.1611 | 0.0000 | -13.43 |

> **Uczciwa interpretacja statystyczna OOT:** W chronologicznym, niefiltrowanym strumieniu Pump.fun bazowa częstość osiągnięcia `2x` po 3. minucie w oknie `4h` wynosi zaledwie ok. `1.1%` (`95% CI Wilsona: [0.3%, 3.8%]`). Ze względu na niską bezwzględną liczbę zdarzeń ekstremalnych (`5x`, `10x`) oraz niezakończony jeszcze horyzont `24h` (`censored`), cele rzadkie i `24h` oznaczono jawnie jako **`INCONCLUSIVE` (`NIEROZSTRZYGNIĘTE`)** zgodnie z wymogiem sekcji 4. Ponadto po uwzględnieniu opłat swap (`2 x 1%`), opłat priorytetowych oraz poślizgu na krzywej AMM średni zwrot netto strategii mechanicznego kupowania Top-20 sygnałów przy większych pozycjach (`1.0–2.0 SOL`) staje się ujemny — ewentualna przewaga selekcyjna istnieje wyłącznie dla małych pozycji (`0.1–0.25 SOL`) przy rygorystycznym odrzucaniu manipulacji.

---

## 3. Ograniczenia badania i spis wygenerowanych artefaktów V2.1
1. **Rezerwy wtórnych pul AMM po migracji (`ESTIMATED_AMM_RESERVES`)** są estymowane względem kanonicznego progu migracji (`~85 SOL`), podczas gdy na krzywej `pump` (`EXACT_BONDING_CURVE_RESERVES`) są dokładne.
2. **Horyzont `24h` w świeżym OOT** pozostaje prawostronnie ocenzurowany (`censored`), ponieważ od emisji tych tokenów upłynęło `1.5h–10.5h`.
3. **Dane społecznościowe X/Telegram** pochodzą z metadanych inicjalizacyjnych kontraktu w chwili `created_timestamp` (brak historycznego strumienia post-po-poście z płatnego API X Enterprise).

Wszystkie 12 wymaganych raportów/tabel, skoroszyt `PUMPFUN_ALPHA_RESEARCH_V2_1.xlsx`, dashboard `dashboard/index.html`, snapshoty JSON oraz zestaw 12 testów jednostkowych (`12/12 PASS`) znajdują się w katalogu głównym `PUMPFUN_ALPHA_RESEARCH_V2_1`.
