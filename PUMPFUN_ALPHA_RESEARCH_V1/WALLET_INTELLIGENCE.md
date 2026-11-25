# WALLET INTELLIGENCE — KLASYFIKACJA UCZESTNIKÓW I WYKRYWANIE SMART MONEY

## 1. Struktura Przebadanych Portfeli ($N = 4,630$ aktywnych / powtarzalnych adresów)
Zgodnie z metodyką nie utożsamiano liczby adresów z liczbą niezależnych osób oraz wykluczono wszystkie adresy techniczne (`Pump.fun Bonding Curve`, `PumpSwap`, `Raydium AMM v4`, `Token Program`, `Jupiter`):

| Klasa uczestnika rynku (Sekcja 8) | Liczba portfeli (min. wielokrotna aktywność) |
| --- | --- |
| 3_BUNDLE_BUYER | 1827 |
| 8_LATE_MOMENTUM_BUYER | 1788 |
| 9_RETAIL_SMALL_INVESTOR | 510 |
| 1_REPEAT_EARLY_BUYER | 206 |
| 6_CREATOR_WALLET | 112 |
| 4_HIGH_FREQ_TRADING_BOT | 91 |
| 10_PROFIT_REALIZER | 54 |
| 2_AUTOMATED_SNIPER | 19 |
| 7_CREATOR_OR_CLUSTER_LINKED | 18 |
| 5_EXPERIENCED_SMART_MONEY | 5 |


---

## 2. Ranking Smart Money Discovery (Wymóg $\ge 3$ analizowanych tokenów)
Żaden portfel nie został uznany za *Smart Money* na podstawie pojedynczej szczęśliwej transakcji. Poniżej przedstawiono portfele z powtarzalnymi wczesnymi wejściami (`TOP 25` kupujących) przed wystąpieniem zweryfikowanych pumpów:

| wallet | participant_class | tokens_analyzed | early_entries_top25 | pre_pump_entries | pre_pump_hit_rate | median_max_multiple_after_entry | observed_net_sol_flow | smart_money_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fs9RN3wAsuJKPbTmtX5eek1bhW5krNH8RkQxkFAtgNfR | 3_BUNDLE_BUYER | 29 | 19 | 19 | 1 | 453.028 | 0.0047 | 100 |
| 7777778BKXiCUVorHkq6m4dbae1gJL2ZHtte23vJ2tuP | 3_BUNDLE_BUYER | 10 | 6 | 6 | 1 | 202.041 | 2.287 | 100 |
| EHZrLMpP9qQpKrRhrfmwjEj8FETFBarSA7CouXCXAQgM | 3_BUNDLE_BUYER | 9 | 5 | 5 | 1 | 368.741 | 0.7967 | 100 |
| 63ScL9V6ywE1DeXyeLFFwozmgXa33rGv8cZtUejGyEYg | 3_BUNDLE_BUYER | 8 | 5 | 5 | 1 | 171.486 | 0.9426 | 100 |
| H9SaZazTkfFYgqXoEYDzfQNVLnDLph7C65BB4vX9c9Sw | 3_BUNDLE_BUYER | 9 | 3 | 3 | 1 | 503.472 | 0.0099 | 100 |
| BUKRPDX9ven15YkqN8ZecugfJt55uT2C8H9qDFx4SL63 | 3_BUNDLE_BUYER | 8 | 3 | 3 | 1 | 107.125 | 0.0743 | 100 |
| 5RvyGVXhBdqyrrMSZoGJa5SYEqPuA1nfq2BwuegMo4k4 | 3_BUNDLE_BUYER | 7 | 7 | 7 | 1 | 200.546 | 0.1257 | 95.83 |
| Fn9n3ftUzjhcmoLwXbTqJdATzamCp3xPEu4LmLSS8ELr | 3_BUNDLE_BUYER | 31 | 15 | 13 | 0.8667 | 503.472 | 0.0097 | 95.33 |
| s8JpJYAYgocSpKG2fyGEMrxvx9oKVvW3XyUKPukjJJF | 3_BUNDLE_BUYER | 6 | 5 | 5 | 1 | 145.785 | 3.232 | 91.67 |
| B39LrkZhEbMpu6GdgYD5v18ZyNChjVzyqm1N9FnNQ4Py | 2_AUTOMATED_SNIPER | 6 | 4 | 4 | 1 | 368.741 | 1.85 | 91.67 |
| 2zA5XfzHyAgK1HX7v4n8naEbhvfpZvFcgUK1CVKPmxBo | 3_BUNDLE_BUYER | 6 | 3 | 3 | 1 | 136.082 | 0.4104 | 91.67 |
| 3Vggwn3LPougvnGa8zpYJMEN9L38tSRa45gv9odiSVF1 | 3_BUNDLE_BUYER | 7 | 6 | 5 | 0.8333 | 216.531 | 0.0543 | 90 |
| HTVZVEQMBsNanubDPTs3CxDAEGNFQHJY8c1441iy2S5r | 3_BUNDLE_BUYER | 38 | 23 | 23 | 1 | 235.331 | -1,138.95 | 89.5 |
| 27HFmP7ccLadGswvQfvea4o3juLw75cPF4V6jWpHM3MX | 3_BUNDLE_BUYER | 24 | 16 | 16 | 1 | 627.274 | -0.0004 | 89.5 |
| 7NNzakXLFv2VfhUuoZ9i4Uy4f63BDJcR96tMCucXa6KL | 3_BUNDLE_BUYER | 22 | 13 | 13 | 1 | 453.028 | -0.0017 | 89.5 |
| 7FPqg7MpJwvGneBPvkBrCDjAvZhFnAvoiUw9LF91nsN | 3_BUNDLE_BUYER | 20 | 9 | 9 | 1 | 591.845 | -1.072 | 89.5 |
| M3rrormwkUUHAKdviFPqniRrva4h3d5xw8j1uo31ZpH | 3_BUNDLE_BUYER | 16 | 8 | 8 | 1 | 591.845 | -4.659 | 89.5 |
| 3SkBCx49BsK64h6tssBBJZ1WNvpiLdnhnXNmJtP46d7b | 3_BUNDLE_BUYER | 14 | 6 | 6 | 1 | 308.01 | -3.22 | 89.5 |
| 3KcPSJ8ouE7H1feoWHmhDwXhLnXhpxP6R6713uytFmBM | 3_BUNDLE_BUYER | 9 | 6 | 6 | 1 | 2,904.91 | -0.0003 | 89.5 |
| q2iQvvxJ58Z27Kr3iuzQWqJS8HVZRdgzEVER5SyxUT5 | 3_BUNDLE_BUYER | 11 | 5 | 5 | 1 | 236.903 | -3.834 | 89.5 |


---

## 3. Kluczowe Wnioski dot. Powtarzalnych Portfeli
1. **Snajperzy blokowi (`2_AUTOMATED_SNIPER` i `3_BUNDLE_BUYER`) vs Selektywne Smart Money (`5_EXPERIENCED_SMART_MONEY`):** Boty snajperskie wchodzące w pierwszych $0–4$ sekundach wykazują ogromną liczbę wejść, ale niską selektywność (kupują dziesiątki martwych tokenów i realizują szybki obrót o krótkim czasie utrzymania pozycji).
2. **Test przyczynowy Out-of-Sample (Hipoteza H12):** Gdy oceniamy portfele **ściśle bez przecieku z przyszłości** (`causal_smart_wallets_in` w pierwszych 5 minutach), sama obecność wcześniej skutecznego portfela daje dodatni wkład w modelu wieloczynnikowym (`waga +` w regresji logistycznej), lecz jako samodzielna reguła wymaga łączenia z dynamiką napływu nowych kupujących, ponieważ nawet najlepsze portfele memecoinowe notują znaczący odsetek nietrafionych wejść (`losing_or_failed_entries`).
