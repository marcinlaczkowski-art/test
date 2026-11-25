# PATTERN DISCOVERY — PROFILE PUMPÓW I NIEOCZYWISTE ZALEŻNOŚCI W DANYCH

## 1. Znormalizowane Profile Pumpów (Rozdział 18 — 11 Mechanizmów + Grupa Kontrolna)
Dane jednoznacznie dowodzą, że **nie istnieje jeden uniwersalny mechanizm dużego pumpa**. Wyodrębniono i skwantyfikowano strukturę poszczególnych profili:

| pump_profile | tokens | median_mult | median_realizable | median_mcap_max | median_liq | median_buyers_30m | median_insider_risk | median_dd_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0_NO_PUMP_CONTROL | 259 | 1.052 | 0.979 | 3,947.98 | 5,398.20 | 3 | 17.04 | 31.48 |
| 11_MULTI_WAVE_PUMP | 78 | 245.12 | 224.37 | 883,619.31 | 21,781.35 | 62.5 | 79.61 | 92.315 |
| 9_INSIDER_CLUSTER_DRIVEN_PUMP | 68 | 86.67 | 82.066 | 335,881.82 | 12,000.00 | 57.5 | 81.4 | 92.795 |
| 2_GRADUAL_ACCUMULATION_PUMP | 42 | 13.213 | 12.127 | 199,858.65 | 12,000.00 | 0 | 6.24 | 91.965 |
| 4_POST_CORRECTION_ABSORPTION_PUMP | 15 | 3.487 | 3.18 | 6,535.43 | 6,037.80 | 8 | 22.02 | 68.91 |
| 8_HIGH_SUPPLY_CONCENTRATION_PUMP | 13 | 12.474 | 11.376 | 260,909.22 | 12,000.00 | 15 | 64.93 | 82.22 |
| 1_ULTRA_FAST_IGNITION_PUMP | 7 | 26.385 | 24.063 | 490,775.21 | 12,000.00 | 38 | 65 | 97.41 |
| 3_POST_STAGNATION_PUMP | 7 | 61.797 | 56.359 | 313,388.50 | 12,000.00 | 0 | 2.4 | 99.38 |
| 5_RETAIL_SMALL_BUY_SWARM | 4 | 67.993 | 61.822 | 169,997.61 | 8,079.90 | 33.5 | 35.845 | 87.035 |


---

## 2. Najmocniejsze Potwierdzone Wzorce (Ocena Dowodu: A)
| id | question | median_winners | median_controls | effect_size_cliffs_d | q_value_bh_fdr |
| --- | --- | --- | --- | --- | --- |
| H02 | Czy tempo napływu NIEZALEŻNYCH kupujących (po odjęciu bundlerów i twórcy) w 5 min wyprzedza pump? | 2.4 | 0.6 | 0.2813 | 0 |
| H04 | Czy przewaga dolarowa kupna nad sprzedażą (buy/sell USD ratio) w 5 min zwiastuje dalszy wzrost >=3x? | 1.731 | 1 | 0.4504 | 0 |
| H06 | Czy absorpcja pierwszej korekty (dip_absorption_ratio podczas spadku >=12%) odróżnia przyszłych zwycięzców 5x+ od przegranych? | 2.459 | 0.804 | 0.5965 | 0 |
| H07 | Czy mierzalny indeks przejścia w FOMO (fomo_transition_index) jest istotnie wyższy w tokenach 5x+ niż w grupie kontrolnej? | 19.99 | 10 | 0.5454 | 0 |
| H08 | Czy średnia wartość pierwszych 10 zakupów (early10_avg_buy_usd) jest wyższa w pumpach niż w tokenach kontrolnych? | 95.755 | 31.51 | 0.409 | 0 |
| H11 | Czy odsetek kupujących dokupujących pozycję (scale_in_buyer_share >=2 zakupy) jest wyższy u zwycięzców? | 0.1644 | 0.05 | 0.2522 | 0 |
| H12 | Czy obecność historycznie skutecznych portfeli (causal_smart_wallets_in) w pierwszych 5 min zwiększa szansę na dalsze 3x+? | 2 | 0 | 0.3123 | 0 |
| H14 | Czy szczytowa koncentracja TOP 10 holderów różni się między tokenami 5x+ a grupą kontrolną? | 32.303 | 4.781 | 0.5279 | 0 |
| H15 | Czy utrzymywanie części podaży przez potencjalnych insiderów (potential_insiders_retained_pct) wiąże się z kolejnymi falami wzrostu (multi-wave)? | 31.369 | 4.157 | 0.2443 | 0.0032 |
| H16 | Czy liczba wykrytych klastrów powiązanych portfeli jest wyższa w dużych pumpach niż w tokenach martwych? | 3 | 1 | 0.4572 | 0 |
| H18 | Czy wczesna sprzedaż tokenów przez twórcę (creator_dumped_at_T w 5 min) obniża przyszły mnożnik wzrostu? | 3.131 | 1 | 0.2913 | 0 |
| H23 | Czy łatwość wymowy tickera (pronounceability_score) ma istotny związek ze skalą wzrostu? | 0.741 | 0.663 | 0.2511 | 0 |
| H25 | Czy pierwszy token używający danego tickera (is_ticker_first_mover=1) osiąga wyższe mnożniki niż jego późniejsi naśladowcy (copycats)? | 7.252 | 1.908 | 0.2362 | 0 |
| H26 | Czy wysoka saturacja klastra semantycznego w ostatnich 24h (>15 podobnych premier) obniża wyniki kolejnych tokenów? | 11.304 | 2.368 | 0.2474 | 0 |
| H33 | Czy dodatnia 24-godzinna zmiana ceny SOL w momencie startu tokena sprzyja większym wzrostom memecoinów? | 2.204 | 1.001 | 0.2608 | 0 |


---

## 3. Obiegiowe Mity i Hipotezy Obalone Przez Dane (Ocena Dowodu: D)
Zgodnie z naczelną zasadą badania (*„Nie potwierdzaj moich założeń. Jeżeli jakaś hipoteza jest błędna, pokaż to”*), poniższe popularne przekonania rynkowe **nie znalazły potwierdzenia** lub wykazały zależność odwrotną:

| id | question | median_winners | median_controls | effect_size_cliffs_d | verdict_pl |
| --- | --- | --- | --- | --- | --- |
| H01 | Czy przyspieszenie napływu kupujących (2. połowa vs 1. połowa pierwszych 5 min) różnicuje przyszłe pumpy 3x+? | 0.1111 | 0.3333 | -0.2508 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H03 | Czy przyspieszenie liczby transakcji (tx_acceleration_ratio) w 5 min przewyższa zwykłą liczbę wczesnych zakupów? | 0.1518 | 0.2857 | -0.1889 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H05 | Czy relacja wolumenu do kapitalizacji (vol/mcap) w 5 min wyprzedza wybicie z bonding curve? | 0.3543 | 0.1842 | 0.0628 | ODRZUCONY — brak potwierdzenia statystycznego względem grupy kontrolnej |
| H09 | Czy udział drobnych zakupów (<$25) różni się między zwycięzcami a przegranymi? | 0.5148 | 0.5 | -0.0058 | ODRZUCONY — kierunek niezgodny z hipotezą / brak przewagi nad grupą kontrolną |
| H10 | Czy zmiana średniego rozmiaru zakupu w czasie pierwszych 5 min (buy_size_shift_ratio) zwiastuje dołączanie kapitału? | 0.818 | 1 | -0.0968 | ODRZUCONY — kierunek niezgodny z hipotezą / brak przewagi nad grupą kontrolną |
| H13 | Czy zmiana koncentracji TOP 5 w pierwszych 5 min (wallet_concentration_change < 0, czyli dekoncentracja) sprzyja trwałemu pumpowi? | 0 | 0 | 0.1273 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H19 | Czy wcześniejszy odsetek sukcesów twórcy (creator_prior_win_rate) pozwala przewidzieć kolejny pump? | 0 | 0 | -0.1224 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H20 | Czy seryjni spamerzy (>10 wcześniejszych tokenów) osiągają gorsze mnożniki niż selektywni twórcy (1-3 tokeny)? | - | - | 0 | ODRZUCONY — kierunek niezgodny z hipotezą / brak przewagi nad grupą kontrolną |
| H21 | Czy włączenie trybu AI Mayhem Mode (sztuczny wolumen bota przez 24h) zwiększa realną szansę na trwały pump >=3x? | 1.52 | 7.371 | -0.2941 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H22 | Czy sama krótka długość tickera (ticker_len) odróżnia zwycięzców 5x+ od przegranych w całej populacji 30 dni? | 5 | 4 | 0.1737 | ODRZUCONY (ZALEŻNOŚĆ ODWROTNA!) — dane wykazują istotny efekt w przeciwnym kierunku |
| H27 | Czy tokeny z narracji AI & Agents różnią się mnożnikiem wzrostu od tokenów Absurd/Toilet Humor? | 8.756 | 23.16 | -0.1061 | ODRZUCONY — kierunek niezgodny z hipotezą / brak przewagi nad grupą kontrolną |
| H28 | Czy kontrowersyjność / wulgarność nazwy (controversy_score > 0) zwiększa czy obniża prawdopodobieństwo dużego wzrostu? | 2.993 | 2.926 | 0.0443 | ODRZUCONY — brak potwierdzenia statystycznego względem grupy kontrolnej |


---

## 4. Pięć Najciekawszych Nieoczywistych Odkryć Badawczych
1. **Obalenie Mitu Sztucznego Wolumenu `Mayhem Mode` (`799` tokenów w uniwersum, $p = 7.8 \times 10^{-27}$!) oraz `ATH Wash-Pools` (`193` tokeny):** Włączenie autonomicznego agenta handlowego AI w `Mayhem Mode` (emitującego dodatkowe 1 mld tokenów na 24h sztucznego obrotu) **obniża medianę mnożnika z `7.37x` do `1.52x`** względem standardowych premier (H21 — sfalsyfikowana z ogromną mocą statystyczną!). Równocześnie odseparowano 193 zmanipulowane pule o zerowej płynności kanonicznej raportujące miliardowe `ath_market_cap` przy realnej wycenie $\sim\$1\,300$.
2. **Tempo Niezależnych Kupujących (`H02`) i Absorpcja Pierwszej Korekty (`H06`) decydują o wybiciu:** W prawdziwych runnerach Solany pierwsze 150 sekund generuje gwałtowny zryw popytu (`independent_buyer_velocity`: mediana `2.4/min` vs `0.6/min` w grupie kontrolnej, waga modelu `+1.125`), a o przejściu w wielką falę wzrostową decyduje **absorpcja pierwszego cofnięcia o $\ge 12\%$ (`dip_absorption_ratio`: mediana `2.46x` vs `0.80x`, `Cliff's d = +0.597`, $p = 5.3 \times 10^{-11}$)**.
3. **Pułapka Migracji na DEX (`H34` — Efekt „Sell-the-Graduation”):** Tokeny po migracji na DEX notują wyższe historyczne obsunięcie od szczytu (`mediana 96.4%`) niż tokeny w fazie aktywnej wspinaczki na krzywej (`58.4%`), co ujawnia masową realizację zysków przez wczesne klastry po uzyskaniu płynności DEX.
4. **Premia Pierwszeństwa (`H25`) i Śmierć przez Saturację Semantyczną (`H26`):** Pierwszy token używający danego tickera osiąga medianę `7.25x` wobec `1.91x` dla klonów ($p = 1.9 \times 10^{-26}$), a start w nienasyconym klastrze semantycznym ($\le 5$ podobnych premier w 24h) daje medianę `11.30x` wobec `2.37x` w przegrzanym trendzie ($>15$ klonów/24h).
5. **Dychotomia Koncentracji Podaży:** Umiarkowana akumulacja przez wczesne klastry pomaga pokonać próg migracji z bonding curve (H14, H16), lecz jednoczesne bundlowanie w bloku 0 dramatycznie podnosi ryzyko późniejszego krachu $>85\%$ (H17).
