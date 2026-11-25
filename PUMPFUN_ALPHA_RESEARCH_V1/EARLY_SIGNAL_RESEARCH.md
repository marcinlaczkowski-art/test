# EARLY SIGNAL RESEARCH — WYKRYWANIE SYGNAŁÓW PRZED GŁÓWNYM RUCHEM CENY

## 1. Ewolucja Punktów Obserwacji (30s – 30m) Bez Przecieku z Przyszłości
Dla każdego z **427** tokenów z 30-dniowej kohorty Grupy A (zarówno pumpów, jak i tokenów kontrolnych) zamrożono stan wiedzy dokładnie w chwilach $T \in \{30\text{s}, 1\text{m}, 3\text{m}, 5\text{m}, 10\text{m}, 15\text{m}, 30\text{m}\}$, mierząc wyłącznie **przyszły wzrost pozostały po chwili $T$** (`future_max_multiple_from_signal`):

| horizon | horizon_sec | tokens | median_already_moved | rate_future_3x | rate_future_5x | median_future_max_mult |
| --- | --- | --- | --- | --- | --- | --- |
| 30s | 30 | 427 | 1.007 | 38.64 | 37.7 | 1.777 |
| 1m | 60 | 427 | 1.001 | 38.41 | 37 | 1.522 |
| 3m | 180 | 427 | 1 | 37.94 | 36.3 | 1.256 |
| 5m | 300 | 427 | 1 | 37.7 | 36.07 | 1.256 |
| 10m | 600 | 427 | 1 | 36.53 | 35.13 | 1.199 |
| 15m | 900 | 427 | 1 | 36.3 | 34.43 | 1.145 |
| 30m | 1800 | 427 | 1 | 34.89 | 32.32 | 1.051 |


> **Wniosek praktyczny:** Okno **`3m – 5m`** stanowi optymalny „złoty punkt” (*sweet spot*) wczesnej detekcji: mediana dotychczasowego ruchu ceny wynosi jeszcze blisko punktu startowego, co pozwala wejść **zanim** rynek wykona główną falę wzrostu, podczas gdy trajektoria przyspieszenia kupujących (`buyer_acceleration_ratio`) i zachowanie twórcy (`creator_dumped_at_T`) są już czytelne on-chain!

---

## 2. TOP 10 Najważniejszych Sygnałów Wczesnego Wykrywania (1–15 min — Rozdział 25)
Wszystkie sygnały oceniono wyłącznie na obserwacjach, w których cena nie uciekła jeszcze powyżej $3\times$ od startu (`already_moved_multiple <= 3.0`), eliminując wskaźniki spóźnione (*lagging indicators*):

| signal_name | definition | measurement_formula | availability_window | n_tokens_triggered | hit_rate_future_3x | lift_vs_baseline | median_future_multiple | mean_future_multiple | median_max_drawdown_pct | manipulation_resilience_and_risk | evidence_grade |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Institutional-Size Initial Conviction Ticket | Mediana pojedynczego zakupu >= $60 przy min. 6 kupujących i braku sprzedaży twórcy. | median_buy_usd >= 60 & new_buyers_cum >= 6 & creator_dumped_at_T == 0 | 1m–5m | 6 | 0.6667 | 2.49 | 77.82 | 163.8 | 63.19 | Średnie — wymaga weryfikacji klastrów finansowania | B |
| 2. Positive Macro SOL Regime + Buyer Flow | Start tokena w dodatnim reżimie SOL (24h > 0%) połączony z >= 5 niezależnymi kupującymi i brakiem sprzedaży twórcy. | sol_ret_24h_pct > 0 & independent_buyers_cum >= 5 & creator_dumped_at_T == 0 | 3m–10m | 24 | 0.625 | 2.34 | 44.76 | 1,834.12 | 49.16 | Bardzo niskie — zewnętrzny czynnik makro SOL | A |
| 3. First Pullback Absorption Surge | Po pierwszym cofnięciu ceny o >=12%, wolumen kupna na spadku przewyższa sprzedaż >= 1.35x (cena nadal <=3x od startu). | had_early_dip_at_T == 1 & dip_absorption_ratio_at_T >= 1.35 | 3m–15m | 26 | 0.5769 | 2.16 | 31.69 | 80.14 | 34.53 | Niskie — trudne do taniego sfabrykowania przy realnej podaży | A |
| 4. Asymmetric Buy-to-Sell Dollar Pressure | Stosunek wolumenu kupna do sprzedaży USD >= 2.2x przy min. 8 transakcjach kupna przed ucieczką ceny (>3x). | buy_sell_usd_ratio >= 2.2 & buy_tx_count >= 8 & mayhem_enabled == 0 | 1m–5m | 43 | 0.5349 | 2 | 4.55 | 158.89 | 29.23 | Niskie po odfiltrowaniu Mayhem AI | A |
| 5. Volume-to-MarketCap Ignition Ratio | Skumulowany obrót przekracza 35% bieżącej kapitalizacji przy braku sprzedaży twórcy i wyłączonym Mayhem. | vol_to_mcap_ratio_at_T >= 0.35 & creator_dumped_at_T == 0 & mayhem_enabled == 0 | 3m–10m | 37 | 0.5135 | 1.92 | 23.01 | 220.39 | 28.25 | Średnie — wymaga kontroli niezależnych portfeli | A |
| 6. Causal Smart Money Early Entry | Wejście min. 1 portfela z historyczną skutecznością >=45% (wyliczoną ściśle przed startem bieżącego tokena). | causal_smart_wallets_in >= 1 & creator_dumped_at_T == 0 | 1m–5m | 57 | 0.4912 | 1.84 | 4.32 | 152.32 | 19.35 | Niskie — oparte na wielokrotnej historii portfela | B |
| 7. Independent Buyer Velocity Surge | Napływ >= 2.5 niezależnych kupujących na minutę (po wykluczeniu bundlerów z bloku 0 i twórcy) bez zrzutu dewelopera. | independent_buyer_velocity >= 2.5 & creator_dumped_at_T == 0 | 1m–5m | 72 | 0.4444 | 1.66 | 2.74 | 396.63 | 29.62 | Niskie — odporne na bundlowanie w jednym bloku | A |
| 8. First-Mover Viral Narrative + Early Demand | Oryginalny pierwszy ticker narracji (is_ticker_first_mover=1) z linkami X/WWW i napływem >=1.5 niezależnych kupujących/min. | is_ticker_first_mover == 1 & has_social_links == 1 & independent_buyer_velocity >= 1.5 | 1m–5m | 91 | 0.4176 | 1.56 | 1.52 | 90.93 | 7.84 | Niskie — łączy przewagę narracyjną z popytem on-chain | A |
| 9. Low Manipulation Guardrail + Liquidity Lift | Wzrost płynności krzywej >= +12% przy niskim ryzyku manipulacji (<35 pkt) i wyłączonym Mayhem Mode. | liquidity_growth_pct_at_T >= 12 & realtime_manipulation_risk < 35 & mayhem_enabled == 0 | 3m–10m | 21 | 0.381 | 1.42 | 1.71 | 66.5 | 36.59 | Niskie — wbudowany filtr anty-manipulacyjny | B |
| 10. Healthy Supply De-Concentration | Stabilna lub malejąca koncentracja TOP 5 holderów (<= +0.5 pp) przy min. 5 niezależnych kupujących. | wallet_concentration_change <= 0.5 & independent_buyers_cum >= 5 | 5m–15m | 105 | 0.3048 | 1.14 | 1.06 | 98.29 | 3.34 | Niskie — mierzy realne rozproszenie tokenów | B |
